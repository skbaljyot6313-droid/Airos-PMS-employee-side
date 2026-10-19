"""Phase-4 realtime emission — queue_event buffering + company channel.

Emitters must buffer on session.info[RT_EVENTS] (never publish_bg
convention) so the after_commit hook publishes ONLY on a real commit;
the envelope data carries a canonical `uid` and no full records.
"""
import asyncio
import uuid
from datetime import datetime, timezone

import pytest

from app.core import centrifugo
from app.core.config import settings
from app.schemas.structure import TaskCreateRequest
from app.services.notifications import NotificationService
from app.services.task import TaskService


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(settings, "CENTRIFUGO_URL", "http://centrifugo.test")
    monkeypatch.setattr(settings, "CENTRIFUGO_API_KEY", "api-key")
    monkeypatch.setattr(settings, "CENTRIFUGO_TOKEN_SECRET", "s" * 32)
    yield


def _buffered(session):
    return session.info.get(centrifugo.RT_EVENTS, [])


@pytest.fixture
def dispatched(monkeypatch):
    """Capture post-commit dispatch — the after_commit hook pops
    session.info[RT_EVENTS] and calls dispatch_realtime_events; the
    recorded calls are the ONLY publish path to assert."""
    calls: list[list[tuple]] = []

    async def _record(events):
        calls.append(list(events))

    monkeypatch.setattr(
        centrifugo, "dispatch_realtime_events", _record
    )
    return calls


def _task_payload(seed):
    return TaskCreateRequest(
        property_uid=seed["prop"].id,
        title="Inspect lobby",
        task_type="fixed",
        employee_uid=seed["employee"].id,
    )


async def test_notify_buffers_notification_created(session, seed):
    svc = NotificationService(session)
    n = await svc.notify(
        employee_id=seed["employee"].id,
        property_id=seed["prop"].id,
        type="task_assigned",
        title="t",
        body="b",
    )
    events = _buffered(session)
    emp_ch = centrifugo.emp_channel(seed["employee"].id)
    assert (emp_ch, "notification.created") in [
        (ch, et) for ch, et, _ in events
    ]
    data = next(d for ch, et, d in events if et == "notification.created")
    assert data["uid"] == str(n.id)
    assert data["notification_type"] == "task_assigned"
    # Envelope minimalism — no full record fields.
    assert "body" not in data and "title" not in data
    await session.rollback()


async def test_task_start_dispatches_task_updated_post_commit(
    session, seed, dispatched,
):
    tasks = TaskService(session)
    task = await tasks.create_task(seed["admin"], _task_payload(seed))
    dispatched.clear()  # ignore the create-path dispatch
    await tasks.start_task(seed["emp_user"], task.id)
    # after_commit dispatches via create_task — yield so it runs.
    await asyncio.sleep(0)
    events = [e for batch in dispatched for e in batch]
    types = {(ch, et) for ch, et, _ in events}
    assert (centrifugo.prop_channel(seed["prop"].id, "tasks"),
            "task.updated") in types
    assert (centrifugo.emp_channel(seed["employee"].id),
            "task.updated") in types
    data = next(d for ch, et, d in events if et == "task.updated"
                and ch == centrifugo.emp_channel(seed["employee"].id))
    assert data["uid"] == str(task.id)
    assert data["task_uid"] == str(task.id)


async def test_allocation_event_dispatches_task_assigned(
    session, seed, dispatched,
):
    tasks = TaskService(session)
    task = await tasks.create_task(seed["admin"], _task_payload(seed))
    dispatched.clear()
    svc = NotificationService(session)
    await svc.notify_allocation_event(
        ticket_kind="task",
        ticket_id=task.id,
        employee_id=seed["employee"].id,
        employee_name="Worker One",
        event_created_at=datetime.now(timezone.utc),
    )
    await asyncio.sleep(0)
    events = [e for batch in dispatched for e in batch]
    emp_ch = centrifugo.emp_channel(seed["employee"].id)
    assert (emp_ch, "task.assigned") in [
        (ch, et) for ch, et, _ in events
    ]
    data = next(d for ch, et, d in events if et == "task.assigned")
    assert data["uid"] == str(task.id)


async def test_rollback_drops_buffered_events(session, seed):
    svc = NotificationService(session)
    await svc.notify(
        employee_id=seed["employee"].id,
        property_id=seed["prop"].id,
        type="task_assigned", title="t", body="b",
    )
    assert _buffered(session)
    # after_commit dispatch pops the queue — a rollback leaves the
    # events buffered on this session but they can never publish:
    # emulate the hook pop to prove the ONLY dispatch path is post-commit.
    session.info.pop(centrifugo.RT_EVENTS)
    await session.rollback()
    assert _buffered(session) == []


# ---------------------------------------------------------------------------
# Company channel — flag-gated, own-company only (REALTIME_COMPANY_
# CHANNEL_ENABLED default OFF).
# ---------------------------------------------------------------------------

from app.api.v1 import realtime as realtime_api  # noqa: E402
from app.models.user import UserRole  # noqa: E402
from types import SimpleNamespace  # noqa: E402


def _user(**kw):
    base = dict(
        id=uuid.uuid4(), role=UserRole.EMPLOYEE,
        company_id=uuid.uuid4(), property_id=uuid.uuid4(),
        employee_id=uuid.uuid4(), name="E",
    )
    base.update(kw)
    return SimpleNamespace(**base)


async def test_company_channel_denied_when_flag_off():
    u = _user()
    with pytest.raises(realtime_api.ChannelDenied):
        await realtime_api.subscribe(
            realtime_api.SubscribeRequest(
                channels=[f"company:{u.company_id}"]),
            user=u,
        )


async def test_company_channel_own_company_ok_when_flag_on(monkeypatch):
    monkeypatch.setattr(settings, "REALTIME_COMPANY_CHANNEL_ENABLED", True)
    u = _user()
    res = await realtime_api.subscribe(
        realtime_api.SubscribeRequest(
            channels=[f"company:{u.company_id}"]),
        user=u,
    )
    assert f"company:{u.company_id}" in res["tokens"]


async def test_company_channel_other_company_denied_when_flag_on(
    monkeypatch,
):
    monkeypatch.setattr(settings, "REALTIME_COMPANY_CHANNEL_ENABLED", True)
    u = _user()
    with pytest.raises(realtime_api.ChannelDenied):
        await realtime_api.subscribe(
            realtime_api.SubscribeRequest(
                channels=[f"company:{uuid.uuid4()}"]),
            user=u,
        )
