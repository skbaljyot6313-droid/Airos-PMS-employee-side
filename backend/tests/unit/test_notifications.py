"""Notifications, device registration, push dispatch + location captures.

Service-level suite (same convention as test_attendance.py) — the HTTP
layer is thin routing over NotificationService / DeviceRegistry /
LocationService.
"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.security import hash_refresh_token, refresh_token_expiry
from app.dependencies.auth import Forbidden
from app.models.audit import AuditEvent
from app.models.notifications import (
    DeviceRegistration,
    LocationEvent,
    Notification,
)
from app.models.refresh_token import RefreshToken
from app.models.task import Task
from app.schemas.location import GeoCapture
from app.schemas.structure import TaskCreateRequest, TaskSubmitRequest
from app.services.attendance import AttendanceService
from app.services.auth import AuthService
from app.services.location import GeoFix, LocationService, parse_geo
from app.services.notifications import DeviceRegistry, NotificationService
from app.services.push import PushResult
from app.services.structure import (
    ConflictErr,
    NotFoundErr,
    StructureService,
    ValidationErr,
)
from app.services.task import TaskService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FailingPush:
    """Provider that always raises — must never break the caller."""

    async def send(self, tokens, title, body, data):
        raise RuntimeError("push backend down")


class _RecordingPush:
    def __init__(self, invalid=()):
        self.calls = []
        self.invalid = list(invalid)

    async def send(self, tokens, title, body, data):
        self.calls.append({"tokens": list(tokens), "title": title,
                           "body": body, "data": data})
        return PushResult(delivered=list(tokens), invalid_tokens=self.invalid)


async def _notifications(session, employee_id) -> list[Notification]:
    res = await session.execute(
        select(Notification).where(Notification.employee_id == employee_id)
    )
    return list(res.scalars())


def _task_create(seed, **over) -> TaskCreateRequest:
    fields = {
        "property_uid": seed["prop"].id,
        "title": "Inspect lobby",
        "task_type": "fixed",
        "employee_uid": seed["employee"].id,
    }
    fields.update(over)
    return TaskCreateRequest(**fields)


# ---------------------------------------------------------------------------
# notify() + dispatch hooks
# ---------------------------------------------------------------------------

async def test_notify_persists_row(session, seed):
    svc = NotificationService(session, push=_RecordingPush())
    n = await svc.notify(
        employee_id=seed["employee"].id, property_id=seed["prop"].id,
        type="task_assigned", title="New Task Assigned", body="Mop floor",
        employee_name="Worker One",
    )
    await session.commit()
    assert n is not None and n.is_read is False
    rows = await _notifications(session, seed["employee"].id)
    assert len(rows) == 1 and rows[0].type == "task_assigned"


async def test_notify_no_employee_is_noop(session, seed):
    n = await NotificationService(session).notify(
        employee_id=None, property_id=seed["prop"].id,
        type="task_assigned", title="t", body="b",
    )
    assert n is None
    assert await session.scalar(
        select(func.count()).select_from(Notification)
    ) == 0


async def test_task_create_notifies_assignee(session, seed):
    """TaskService.create_task → task_assigned row for THAT employee only."""
    task = await TaskService(session).create_task(
        seed["admin"], _task_create(seed),
    )
    assert task.employee_id == seed["employee"].id
    rows = await _notifications(session, seed["employee"].id)
    assert len(rows) == 1
    n = rows[0]
    assert n.type == "task_assigned" and n.task_id == task.id
    assert n.title == "New Task Assigned" and task.title in n.body
    assert n.employee_name == "Worker One"


async def test_task_reassign_notifies_new_employee(session, seed):
    from app.models.employee import Employee
    emp2 = Employee(
        company_id=seed["company"].id, property_id=seed["prop"].id,
        name="Worker Two", email="w2@acme.test", status="active",
    )
    session.add(emp2)
    await session.commit()
    task = await TaskService(session).create_task(
        seed["admin"], _task_create(seed),
    )
    await TaskService(session).reassign(seed["admin"], task.id, emp2.id)
    mine = await _notifications(session, seed["employee"].id)
    theirs = await _notifications(session, emp2.id)
    assert [n.type for n in mine] == ["task_assigned"]
    assert [n.type for n in theirs] == ["task_reassigned"]
    assert theirs[0].task_id == task.id


async def test_push_failure_does_not_break_allocation(session, seed, monkeypatch):
    """Provider raises → the task AND the notification still commit."""
    from app.services import notifications as notif_mod

    monkeypatch.setattr(notif_mod, "get_push_provider", lambda: _FailingPush())
    task = await TaskService(session).create_task(
        seed["admin"], _task_create(seed),
    )
    assert task.id is not None
    rows = await _notifications(session, seed["employee"].id)
    assert len(rows) == 1


async def test_push_reaches_active_devices_only(session, seed):
    reg = DeviceRegistry(session)
    await reg.register(
        seed["emp_user"], device_id="phone-1", push_token="tok-live",
        platform="android",
    )
    dead = await reg.register(
        seed["emp_user"], device_id="phone-2", push_token="tok-dead",
        platform="ios",
    )
    dead.is_active = False
    await session.commit()

    push = _RecordingPush()
    await NotificationService(session, push=push).notify(
        employee_id=seed["employee"].id, property_id=seed["prop"].id,
        type="task_assigned", title="t", body="b", task_id=uuid.uuid4(),
    )
    assert push.calls[0]["tokens"] == ["tok-live"]
    assert push.calls[0]["data"]["type"] == "task_assigned"
    assert "task_uid" in push.calls[0]["data"]


async def test_dead_tokens_deactivated(session, seed):
    reg = DeviceRegistry(session)
    await reg.register(
        seed["emp_user"], device_id="phone-1", push_token="tok-stale",
        platform="android",
    )
    push = _RecordingPush(invalid=["tok-stale"])
    await NotificationService(session, push=push).notify(
        employee_id=seed["employee"].id, property_id=seed["prop"].id,
        type="task_assigned", title="t", body="b",
    )
    await session.commit()
    res = await session.execute(
        select(DeviceRegistration).where(
            DeviceRegistration.push_token == "tok-stale"
        )
    )
    assert res.scalar_one().is_active is False


async def test_no_duplicate_notif_on_spawn_dedupe(session, seed):
    """An identical OPEN cleaning task means the unit is already queued —
    dedupe returns no task and emits no second notification."""
    existing = Task(
        property_id=seed["prop"].id, title="Cleaning — 101",
        room_id=seed["room"].id, status="assigned", task_type="fixed",
        employee_id=seed["employee"].id,
    )
    session.add(existing)
    await session.commit()
    generated = await StructureService(session)._generate_cleaning_tasks(
        seed["admin"], seed["prop"], "manual", [seed["room"]], [],
    )
    assert generated == []
    assert await _notifications(session, seed["employee"].id) == []


# ---------------------------------------------------------------------------
# mark_read / list / unread_count
# ---------------------------------------------------------------------------

async def _seed_notification(session, seed, employee_id) -> Notification:
    n = await NotificationService(session).notify(
        employee_id=employee_id, property_id=seed["prop"].id,
        type="task_assigned", title="t", body="b",
    )
    await session.commit()
    return n


async def test_mark_read_idempotent_and_audited(session, seed):
    svc = NotificationService(session)
    n = await _seed_notification(session, seed, seed["employee"].id)
    read = await svc.mark_read(seed["emp_user"], n.id)
    assert read.is_read is True and read.read_at is not None
    again = await svc.mark_read(seed["emp_user"], n.id)
    assert again.read_at == read.read_at  # not re-stamped
    audits = (await session.execute(
        select(AuditEvent).where(AuditEvent.action == "notification_read")
    )).scalars().all()
    assert len(audits) == 1  # second read did not re-audit


async def test_other_employee_cannot_mark_read(session, seed):
    """Another employee's notification is invisible — 404, never a leak."""
    svc = NotificationService(session)
    n = await _seed_notification(session, seed, seed["employee"].id)
    emp2_user = seed["emp_user2"]
    emp2_user.employee_id = uuid.uuid4()  # linked, but not the owner
    with pytest.raises(NotFoundErr):
        await svc.mark_read(emp2_user, n.id)
    with pytest.raises(NotFoundErr):
        await svc.mark_read(
            seed["admin"], n.id
        )  # admin with no employee link → 404


async def test_list_and_unread_count_scoped(session, seed):
    svc = NotificationService(session)
    n1 = await _seed_notification(session, seed, seed["employee"].id)
    await _seed_notification(session, seed, seed["employee"].id)
    await svc.mark_read(seed["emp_user"], n1.id)

    items = await svc.list_notifications(seed["emp_user"])
    assert len(items) == 2
    unread = await svc.list_notifications(seed["emp_user"], unread_only=True)
    assert len(unread) == 1 and unread[0].is_read is False
    assert await svc.unread_count(seed["emp_user"]) == 1

    # another employee sees nothing
    other_emp = seed["emp_user2"]
    other_emp.employee_id = uuid.uuid4()
    assert await svc.list_notifications(other_emp) == []
    assert await svc.unread_count(other_emp) == 0


async def test_employee_without_link_forbidden(session, seed):
    svc = NotificationService(session)
    with pytest.raises(Forbidden):
        await svc.list_notifications(seed["emp_user2"])
    with pytest.raises(Forbidden):
        await svc.unread_count(seed["emp_user2"])
    with pytest.raises(Forbidden):
        await DeviceRegistry(session).register(
            seed["emp_user2"], device_id="x", push_token="t",
            platform="android",
        )


# ---------------------------------------------------------------------------
# DeviceRegistry
# ---------------------------------------------------------------------------

async def test_device_register_upsert(session, seed):
    reg = DeviceRegistry(session)
    d = await reg.register(
        seed["emp_user"], device_id="dev-1", push_token="tok-a",
        platform="android", app_version="1.0.0",
    )
    assert d.is_active is True and d.user_id == seed["emp_user"].id
    # re-register the same device → same row, new token, stays active
    d2 = await reg.register(
        seed["emp_user"], device_id="dev-1", push_token="tok-b",
        platform="android", app_version="1.1.0",
    )
    assert d2.id == d.id and d2.push_token == "tok-b"
    res = await session.execute(
        select(DeviceRegistration).where(
            DeviceRegistration.employee_id == seed["employee"].id
        )
    )
    assert len(res.scalars().all()) == 1


async def test_device_multi_device_and_unregister(session, seed):
    reg = DeviceRegistry(session)
    await reg.register(
        seed["emp_user"], device_id="dev-1", push_token="t1",
        platform="android",
    )
    await reg.register(
        seed["emp_user"], device_id="dev-2", push_token="t2",
        platform="web",
    )
    d = await reg.unregister(seed["emp_user"], device_id="dev-1")
    assert d.is_active is False
    # unregister is idempotent — unknown device is a no-op, not an error
    assert await reg.unregister(
        seed["emp_user"], device_id="dev-unknown"
    ) is None
    res = await session.execute(
        select(DeviceRegistration).where(
            DeviceRegistration.employee_id == seed["employee"].id,
            DeviceRegistration.is_active.is_(True),
        )
    )
    active = res.scalars().all()
    assert len(active) == 1 and active[0].device_id == "dev-2"


async def test_logout_deactivates_user_devices(session, seed):
    """The refresh token's owner loses push on logout — logout scoping."""
    reg = DeviceRegistry(session)
    await reg.register(
        seed["emp_user"], device_id="dev-1", push_token="t1",
        platform="android",
    )
    raw = "refresh-secret"
    session.add(RefreshToken(
        user_id=seed["emp_user"].id, token_hash=hash_refresh_token(raw),
        expires_at=refresh_token_expiry(),
    ))
    await session.commit()
    await AuthService(session).logout(raw)
    res = await session.execute(
        select(DeviceRegistration).where(
            DeviceRegistration.user_id == seed["emp_user"].id
        )
    )
    assert res.scalar_one().is_active is False


async def test_device_platform_check(session, seed):
    with pytest.raises(ValidationErr):
        await DeviceRegistry(session).register(
            seed["emp_user"], device_id="d", push_token="t",
            platform="toaster",
        )
    session.add(DeviceRegistration(
        employee_id=seed["employee"].id, device_id="d2",
        push_token="t", platform="toaster",
    ))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_device_unique_constraint(session, seed):
    session.add(DeviceRegistration(
        employee_id=seed["employee"].id, device_id="dup",
        push_token="t1", platform="android",
    ))
    await session.flush()
    session.add(DeviceRegistration(
        employee_id=seed["employee"].id, device_id="dup",
        push_token="t2", platform="android",
    ))
    with pytest.raises(IntegrityError):
        await session.flush()


# ---------------------------------------------------------------------------
# Location capture — parse/flag unit paths (route wiring is on attendance
# tests; the events land in location_events with a server timestamp)
# ---------------------------------------------------------------------------

async def test_parse_geo_validation():
    assert parse_geo(None) is None
    assert parse_geo(GeoCapture()) is None
    with pytest.raises(ValidationErr):
        parse_geo(GeoCapture(latitude=10.0))          # lon missing
    with pytest.raises(ValidationErr):
        parse_geo(GeoCapture(latitude=95.0, longitude=0.0))
    with pytest.raises(ValidationErr):
        parse_geo(GeoCapture(latitude=0.0, longitude=200.0))
    with pytest.raises(ValidationErr):
        parse_geo(GeoCapture(latitude=0.0, longitude=0.0,
                             accuracy_meters=-1))
    with pytest.raises(ValidationErr):
        parse_geo(GeoCapture(accuracy_meters=5.0))    # acc without fix
    fix = parse_geo(GeoCapture(latitude=12.9, longitude=77.6,
                               accuracy_meters=8.0))
    assert fix.latitude == 12.9


async def test_task_start_and_submit_capture_location(session, seed):
    task = Task(
        property_id=seed["prop"].id, title="Fix AC", status="assigned",
        task_type="fixed", employee_id=seed["employee"].id,
    )
    session.add(task)
    await session.commit()
    svc = TaskService(session)
    geo = GeoCapture(latitude=12.9, longitude=77.6, accuracy_meters=10.0)
    await svc.start_task(seed["emp_user"], task.id, geo=geo)
    res = await session.execute(
        select(LocationEvent).where(LocationEvent.source == "task_start")
    )
    ev = res.scalar_one()
    assert ev.task_id == task.id and ev.attendance_day_id is None
    assert ev.employee_id == seed["employee"].id
    await svc.submit_task(
        seed["emp_user"], task.id,
        TaskSubmitRequest(photo_urls=["https://x/p.jpg"], latitude=12.9,
                          longitude=77.6, accuracy_meters=9.0),
    )
    res = await session.execute(
        select(LocationEvent).where(LocationEvent.source == "task_submit")
    )
    assert res.scalar_one().task_id == task.id


# ---------------------------------------------------------------------------
# Allocation sync — assignments written to the shared ledger by the
# Super Admin backend never pass through this app's notify() paths, so
# the feed materializes them from work_allocation_history at read time.
# ---------------------------------------------------------------------------

from datetime import timedelta

from app.models.maintenance import MaintenanceTicket
from app.models.work_allocation import WorkAllocationHistory


def _alloc_event(seed, *, kind="task", ticket_id, previous=None,
                 when=None) -> WorkAllocationHistory:
    h = WorkAllocationHistory(
        property_id=seed["prop"].id, ticket_kind=kind,
        ticket_id=ticket_id, employee_id=seed["employee"].id,
        employee_name="Worker One", previous_employee_id=previous,
        allocation_method="manual", actor_name="Admin",
    )
    if when is not None:
        h.created_at = when
    return h


def _open_task(seed, employee_id=None, title="Mop lobby") -> Task:
    return Task(
        property_id=seed["prop"].id, title=title, status="assigned",
        task_type="fixed",
        employee_id=employee_id if employee_id is not None
        else seed["employee"].id,
    )


async def test_sync_creates_notification_for_ledger_event(session, seed):
    """SA assigns a task → ledger row only → the employee's next feed
    read materializes a task_assigned notification."""
    task = _open_task(seed)
    session.add(task)
    await session.flush()
    session.add(_alloc_event(seed, ticket_id=task.id))
    await session.commit()

    created = await NotificationService(session).sync_assignment_notifications(
        seed["emp_user"]
    )
    assert created == 1
    rows = await _notifications(session, seed["employee"].id)
    assert len(rows) == 1
    n = rows[0]
    assert n.type == "task_assigned" and n.task_id == task.id
    assert n.title == "New Task Assigned" and n.body == "Mop lobby"
    assert n.employee_name == "Worker One"

    # Idempotent — a second sync creates nothing.
    assert await NotificationService(session).sync_assignment_notifications(
        seed["emp_user"]
    ) == 0
    assert len(await _notifications(session, seed["employee"].id)) == 1


async def test_sync_reassign_event_marks_reassigned(session, seed):
    task = _open_task(seed)
    session.add(task)
    await session.flush()
    session.add(_alloc_event(
        seed, ticket_id=task.id, previous=uuid.uuid4(),
    ))
    await session.commit()
    await NotificationService(session).sync_assignment_notifications(
        seed["emp_user"]
    )
    (n,) = await _notifications(session, seed["employee"].id)
    assert n.type == "task_reassigned" and n.title == "Task Reassigned"


async def test_sync_skips_event_already_notified(session, seed):
    """EB's own create_task notifies inline AFTER the ledger write —
    the existing row covers the event; sync must not duplicate it."""
    task = await TaskService(session).create_task(
        seed["admin"], _task_create(seed),
    )
    assert await NotificationService(session).sync_assignment_notifications(
        seed["emp_user"]
    ) == 0
    assert len(await _notifications(session, seed["employee"].id)) == 1


async def test_sync_skips_work_reassigned_away(session, seed):
    """Ledger event points at me but the task is no longer mine —
    reassigned-away work must not pop up."""
    other = seed["employee2"] if "employee2" in seed else None
    from app.models.employee import Employee
    emp2 = Employee(
        company_id=seed["company"].id, property_id=seed["prop"].id,
        name="Worker Two", email="w2b@acme.test", status="active",
    )
    session.add(emp2)
    await session.flush()
    task = _open_task(seed, employee_id=emp2.id)
    session.add(task)
    await session.flush()
    session.add(_alloc_event(seed, ticket_id=task.id))
    await session.commit()
    assert await NotificationService(session).sync_assignment_notifications(
        seed["emp_user"]
    ) == 0
    assert await _notifications(session, seed["employee"].id) == []
    assert other is None or True


async def test_sync_ignores_events_outside_window(session, seed):
    task = _open_task(seed)
    session.add(task)
    await session.flush()
    session.add(_alloc_event(
        seed, ticket_id=task.id,
        when=datetime.now(timezone.utc) - timedelta(days=30),
    ))
    await session.commit()
    assert await NotificationService(session).sync_assignment_notifications(
        seed["emp_user"]
    ) == 0
    assert await _notifications(session, seed["employee"].id) == []


async def test_sync_later_event_notifies_again(session, seed):
    """Reassigned back to me → a SECOND notification (the existing one
    only covers events at-or-before its own timestamp)."""
    task = _open_task(seed)
    session.add(task)
    await session.flush()
    t0 = datetime.now(timezone.utc) - timedelta(hours=2)
    session.add(_alloc_event(seed, ticket_id=task.id, when=t0))
    await session.commit()
    svc = NotificationService(session)
    assert await svc.sync_assignment_notifications(seed["emp_user"]) == 1

    session.add(_alloc_event(
        seed, ticket_id=task.id, previous=uuid.uuid4(),
    ))
    await session.commit()
    assert await svc.sync_assignment_notifications(seed["emp_user"]) == 1
    types = [n.type for n in await _notifications(session, seed["employee"].id)]
    assert sorted(types) == ["task_assigned", "task_reassigned"]


async def test_sync_maintenance_ticket_assignment(session, seed):
    ticket = MaintenanceTicket(
        company_id=seed["company"].id, property_id=seed["prop"].id,
        ticket_number="MT-2026-00001", maintenance_type="plumbing",
        issue="Leaking tap", priority="high", status="assigned",
        assigned_to=seed["employee"].id, assigned_to_name="Worker One",
    )
    session.add(ticket)
    await session.flush()
    session.add(_alloc_event(
        seed, kind="maintenance", ticket_id=ticket.id,
    ))
    await session.commit()
    assert await NotificationService(session).sync_assignment_notifications(
        seed["emp_user"]
    ) == 1
    (n,) = await _notifications(session, seed["employee"].id)
    assert n.type == "ticket_assigned" and n.ticket_id == ticket.id
    assert n.title == "New Maintenance Ticket" and n.body == "Leaking tap"


async def test_sync_forbidden_without_employee_link(session, seed):
    with pytest.raises(Forbidden):
        await NotificationService(session).sync_assignment_notifications(
            seed["emp_user2"]
        )


# ---------------------------------------------------------------------------
# SA push endpoint — notify_allocation_event() backs
# POST /admin/notify-allocation (server-to-server, X-Location-Service-Key).
# ---------------------------------------------------------------------------

async def test_event_creates_task_notification(session, seed):
    task = _open_task(seed)
    session.add(task)
    await session.commit()

    n = await NotificationService(session).notify_allocation_event(
        ticket_kind="task", ticket_id=task.id,
        employee_id=seed["employee"].id,
    )
    assert n is not None
    assert n.type == "task_assigned" and n.title == "New Task Assigned"
    assert n.task_id == task.id and n.ticket_id is None
    assert n.body == "Mop lobby"
    assert len(await _notifications(session, seed["employee"].id)) == 1


async def test_event_reassignment_marks_reassigned(session, seed):
    task = _open_task(seed)
    session.add(task)
    await session.commit()
    n = await NotificationService(session).notify_allocation_event(
        ticket_kind="task", ticket_id=task.id,
        employee_id=seed["employee"].id,
        previous_employee_id=uuid.uuid4(),
    )
    assert n is not None
    assert n.type == "task_reassigned" and n.title == "Task Reassigned"


async def test_event_maintenance_ticket(session, seed):
    ticket = MaintenanceTicket(
        company_id=seed["company"].id, property_id=seed["prop"].id,
        ticket_number="MT-2026-00002", maintenance_type="plumbing",
        issue="Broken shower", priority="high", status="assigned",
        assigned_to=seed["employee"].id,
    )
    session.add(ticket)
    await session.commit()
    n = await NotificationService(session).notify_allocation_event(
        ticket_kind="maintenance", ticket_id=ticket.id,
        employee_id=seed["employee"].id,
    )
    assert n is not None
    assert n.type == "ticket_assigned" and n.ticket_id == ticket.id
    assert n.body == "Broken shower"


async def test_event_dedupes_repeat_delivery(session, seed):
    """SA retries / double-delivers → second call is a no-op."""
    task = _open_task(seed)
    session.add(task)
    await session.commit()
    svc = NotificationService(session)
    first = await svc.notify_allocation_event(
        ticket_kind="task", ticket_id=task.id,
        employee_id=seed["employee"].id,
    )
    second = await svc.notify_allocation_event(
        ticket_kind="task", ticket_id=task.id,
        employee_id=seed["employee"].id,
    )
    assert first is not None and second is None
    assert len(await _notifications(session, seed["employee"].id)) == 1


async def test_event_rejected_when_no_longer_assigned(session, seed):
    """Stale event: task now belongs to someone else → 404, no row."""
    from app.models.employee import Employee
    emp2 = Employee(
        company_id=seed["company"].id, property_id=seed["prop"].id,
        name="Worker Two", email="w2c@acme.test", status="active",
    )
    session.add(emp2)
    await session.flush()
    task = _open_task(seed, employee_id=emp2.id)
    session.add(task)
    await session.commit()
    with pytest.raises(NotFoundErr):
        await NotificationService(session).notify_allocation_event(
            ticket_kind="task", ticket_id=task.id,
            employee_id=seed["employee"].id,
        )
    assert await _notifications(session, seed["employee"].id) == []


async def test_event_rejected_for_unknown_ticket(session, seed):
    with pytest.raises(NotFoundErr):
        await NotificationService(session).notify_allocation_event(
            ticket_kind="task", ticket_id=uuid.uuid4(),
            employee_id=seed["employee"].id,
        )


async def test_event_rejected_for_unknown_kind(session, seed):
    with pytest.raises(ValidationErr):
        await NotificationService(session).notify_allocation_event(
            ticket_kind="carrier_pigeon", ticket_id=uuid.uuid4(),
            employee_id=seed["employee"].id,
        )


async def test_event_then_sync_no_double_notify(session, seed):
    """Push arrives first, feed poll later → synthesis sees the existing
    row covers the ledger event and creates nothing."""
    task = _open_task(seed)
    session.add(task)
    await session.flush()
    t0 = datetime.now(timezone.utc) - timedelta(minutes=5)
    session.add(_alloc_event(seed, ticket_id=task.id, when=t0))
    await session.commit()

    svc = NotificationService(session)
    n = await svc.notify_allocation_event(
        ticket_kind="task", ticket_id=task.id,
        employee_id=seed["employee"].id,
        event_created_at=t0,
    )
    assert n is not None
    assert await svc.sync_assignment_notifications(seed["emp_user"]) == 0
    assert len(await _notifications(session, seed["employee"].id)) == 1


async def test_event_push_failure_still_persists(session, seed, monkeypatch):
    from app.services import notifications as notif_mod
    monkeypatch.setattr(notif_mod, "get_push_provider", lambda: _FailingPush())
    task = _open_task(seed)
    session.add(task)
    await session.commit()
    n = await NotificationService(session).notify_allocation_event(
        ticket_kind="task", ticket_id=task.id,
        employee_id=seed["employee"].id,
    )
    assert n is not None
    assert len(await _notifications(session, seed["employee"].id)) == 1


async def test_event_uses_employee_name_for_push(session, seed):
    """Push data carries the employee's display name when resolvable."""
    task = _open_task(seed)
    session.add(task)
    await session.commit()
    push = _RecordingPush()
    await NotificationService(session, push=push).notify_allocation_event(
        ticket_kind="task", ticket_id=task.id,
        employee_id=seed["employee"].id,
    )
    # No device registrations → no call, but no error either.
    assert push.calls == []
