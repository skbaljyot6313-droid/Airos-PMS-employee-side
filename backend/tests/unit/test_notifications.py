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
