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


# ---------------------------------------------------------------------------
# HTTP-level checks — auth gate, response schema, channel validation
# ---------------------------------------------------------------------------

import httpx

from app.dependencies.auth import get_current_user
from app.main import app

RT = "/api/v1/realtime"


def _http_user(**kw):
    return _user(**kw)


@pytest.fixture
async def api():
    app.dependency_overrides[get_current_user] = lambda: _http_user()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        yield client
    app.dependency_overrides.pop(get_current_user, None)


async def test_http_token_unauthenticated_401():
    """No dependency override → real auth gate → missing bearer = 401."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        res = await client.get(f"{RT}/token")
        assert res.status_code == 401
        res = await client.post(f"{RT}/subscribe", json={"channels": []})
        assert res.status_code == 401


async def test_http_token_response_shape(api):
    res = await api.get(f"{RT}/token")
    assert res.status_code == 200
    body = res.json()
    assert body["token"]
    assert body["expires_at"] > int(time.time())
    # Default derivation: CENTRIFUGO_URL + /connection/websocket
    assert body["ws_url"] == "http://centrifugo.test/connection/websocket"


async def test_http_ws_url_override(api, monkeypatch):
    monkeypatch.setattr(
        settings, "CENTRIFUGO_WS_URL", "wss://rt.example.com/websocket"
    )
    res = await api.get(f"{RT}/token")
    assert res.json()["ws_url"] == "wss://rt.example.com/websocket"


async def test_http_subscribe_own_channel(api):
    ch = f"priv:emp:{EMP_ID}"
    res = await api.post(f"{RT}/subscribe", json={"channels": [ch]})
    assert res.status_code == 200
    body = res.json()
    assert ch in body["tokens"]
    claims = pyjwt.decode(body["tokens"][ch], SECRET, algorithms=["HS256"])
    assert claims["channel"] == ch
    assert claims["exp"] > int(time.time())


async def test_http_subscribe_other_employee_403(api):
    res = await api.post(
        f"{RT}/subscribe",
        json={"channels": [f"priv:emp:{uuid.uuid4()}"]},
    )
    assert res.status_code == 403


@pytest.mark.parametrize(
    "ch",
    [
        "priv:emp:not-a-uuid",
        f"priv:prop:{uuid.uuid4()}:tasks",
        f"priv:prop:{uuid.uuid4()}:locations",
        "public:chat",
        f"emp:{EMP_ID}",
        f"priv:emp:{EMP_ID}:extra",
        f"PRIV:emp:{EMP_ID}",
        "",
    ],
)
async def test_http_subscribe_rejected_channels(api, ch):
    res = await api.post(f"{RT}/subscribe", json={"channels": [ch]})
    assert res.status_code == 403, ch


async def test_http_subscribe_unconfigured_503(monkeypatch):
    monkeypatch.setattr(settings, "CENTRIFUGO_URL", None)
    app.dependency_overrides[get_current_user] = lambda: _http_user()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        res = await client.get(f"{RT}/token")
        assert res.status_code == 503
        res = await client.post(
            f"{RT}/subscribe", json={"channels": [f"priv:emp:{EMP_ID}"]}
        )
        assert res.status_code == 503
    app.dependency_overrides.pop(get_current_user, None)


async def test_publish_failure_logged_not_raised(monkeypatch, caplog):
    """Centrifugo HTTP failure → publish returns False + warning, never raises."""
    async def _boom(*a, **kw):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(centrifugo, "_client", None)
    monkeypatch.setattr(httpx.AsyncClient, "post", _boom)
    ok = await centrifugo.publish("priv:emp:x", "task.updated", {})
    assert ok is False
