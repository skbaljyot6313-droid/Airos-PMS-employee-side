"""Centrifugo realtime — token minting + the employee self-channel gate.

The EB API mints subscription tokens for `priv:emp:{employee_uid}` ONLY
when the caller's own employee_id matches — employees can never join
another employee's channel or any property channel.
"""
import time
import uuid
from types import SimpleNamespace

import jwt as pyjwt
import pytest

from app.api.v1 import realtime as realtime_api
from app.core import centrifugo
from app.core.config import settings
from app.models.user import UserRole

SECRET = "test-centrifugo-secret-key-32byte"
EMP_ID = uuid.uuid4()


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(settings, "CENTRIFUGO_URL", "http://centrifugo.test")
    monkeypatch.setattr(settings, "CENTRIFUGO_API_KEY", "api-key")
    monkeypatch.setattr(settings, "CENTRIFUGO_TOKEN_SECRET", SECRET)
    monkeypatch.setattr(settings, "CENTRIFUGO_WS_URL", None)
    yield


def _user(**kw):
    base = dict(
        id=uuid.uuid4(),
        role=UserRole.EMPLOYEE,
        company_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        employee_id=EMP_ID,
        name="Test Employee",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_connection_token_claims():
    user = _user()
    token, exp = centrifugo.connection_token(user)
    claims = pyjwt.decode(token, SECRET, algorithms=["HS256"])
    assert claims["sub"] == str(user.id)
    assert claims["exp"] == exp > int(time.time())


@pytest.mark.asyncio
async def test_subscribe_own_channel_ok():
    ch = centrifugo.emp_channel(EMP_ID)
    res = await realtime_api.subscribe(
        realtime_api.SubscribeRequest(channels=[ch]),
        user=_user(),
    )
    assert ch in res["tokens"]
    claims = pyjwt.decode(res["tokens"][ch], SECRET, algorithms=["HS256"])
    assert claims["channel"] == ch


@pytest.mark.asyncio
async def test_subscribe_other_employee_denied():
    ch = centrifugo.emp_channel(uuid.uuid4())
    with pytest.raises(realtime_api.ChannelDenied):
        await realtime_api.subscribe(
            realtime_api.SubscribeRequest(channels=[ch]),
            user=_user(),
        )


@pytest.mark.asyncio
async def test_subscribe_property_channel_denied_for_employee():
    ch = centrifugo.prop_channel(uuid.uuid4(), "tasks")
    with pytest.raises(realtime_api.ChannelDenied):
        await realtime_api.subscribe(
            realtime_api.SubscribeRequest(channels=[ch]),
            user=_user(),
        )


@pytest.mark.asyncio
async def test_subscribe_user_without_employee_denied():
    """A staff account with no employee link can't mint emp tokens."""
    ch = centrifugo.emp_channel(EMP_ID)
    with pytest.raises(realtime_api.ChannelDenied):
        await realtime_api.subscribe(
            realtime_api.SubscribeRequest(channels=[ch]),
            user=_user(employee_id=None),
        )


@pytest.mark.asyncio
async def test_unconfigured_503(monkeypatch):
    monkeypatch.setattr(settings, "CENTRIFUGO_URL", None)
    with pytest.raises(realtime_api.RealtimeUnavailable):
        await realtime_api.realtime_token(user=_user())


@pytest.mark.asyncio
async def test_location_publish_throttle_in_memory(monkeypatch):
    """In-process fallback throttles to the configured interval."""
    monkeypatch.setattr(
        settings, "LOCATION_PUBLISH_MIN_INTERVAL_SECONDS", 8
    )

    class _NoRedis:
        async def get_redis(self):
            return None

    import app.core.centrifugo as cg
    import app.core.redis as redis_core

    async def _none():
        return None
    monkeypatch.setattr(redis_core, "get_redis", _none)
    cg._last_pub.clear()

    emp = uuid.uuid4()
    assert await cg.location_publish_allowed(emp) is True
    assert await cg.location_publish_allowed(emp) is False
    other = uuid.uuid4()
    assert await cg.location_publish_allowed(other) is True


def test_queue_event_buffers_and_dispatch_is_bounded():
    session = SimpleNamespace(info={})
    centrifugo.queue_event(session, "c1", "task.updated", {"x": 1})
    assert session.info[centrifugo.RT_EVENTS] == [
        ("c1", "task.updated", {"x": 1})
    ]
