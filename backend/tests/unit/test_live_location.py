"""Live location — current-position-only Redis store.

Route-level suite (httpx ASGI transport, dependency-overridden get_db)
because the contract under test is mostly HTTP: auth gates, 422s, the
503 degrade, and "no Postgres in the POST path". Redis is faked at the
app.core.redis.get_redis seam — no server needed.

Invariant under test: Redis holds the LATEST fix per employee
(mt:location:emp:<uuid>, TTL 60 s refreshed per write) — no history,
no Postgres writes.
"""

import inspect
import uuid

import fakeredis.aioredis
import httpx
import pytest

from app.api.v1.location import post_current_location
from app.core import redis as redis_core
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.services.location_live import LIVE_TTL_SECONDS, location_key

BASE = "/api/v1/location/current"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def fake_redis(monkeypatch):
    """Swap the shared-client seam for an in-memory fakeredis."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def _get():
        return client

    monkeypatch.setattr(redis_core, "get_redis", _get)
    yield client
    await client.aclose()


@pytest.fixture
async def no_redis(monkeypatch):
    """get_redis() returns None — unconfigured/unreachable Redis."""

    async def _get():
        return None

    monkeypatch.setattr(redis_core, "get_redis", _get)


@pytest.fixture
async def api(session):
    """ASGI client with get_db overridden to the in-memory session."""

    async def _db():
        yield session

    app.dependency_overrides[get_db] = _db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        yield client
    app.dependency_overrides.pop(get_db, None)


def _auth(user) -> dict:
    token = create_access_token(
        user_id=str(user.id),
        company_id=str(user.company_id),
        role=user.role.value,
    )
    return {"Authorization": f"Bearer {token}"}


def _payload(**over) -> dict:
    body = {
        "latitude": 12.9716,
        "longitude": 77.5946,
        "accuracy": 8.0,
        "timestamp": 1_760_000_000.0,
    }
    body.update(over)
    return body


# ---------------------------------------------------------------------------
# POST /location/current
# ---------------------------------------------------------------------------


async def test_post_writes_hash_with_ttl(api, seed, fake_redis):
    res = await api.post(
        BASE, json=_payload(speed=1.2, heading=90.0),
        headers=_auth(seed["emp_user"]),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["recorded"] is True
    assert body["expires_in"] == LIVE_TTL_SECONDS
    assert body["server_timestamp"] > 0

    key = location_key(seed["employee"].id)
    raw = await fake_redis.hgetall(key)
    assert float(raw["latitude"]) == 12.9716
    assert float(raw["longitude"]) == 77.5946
    assert float(raw["accuracy"]) == 8.0
    assert float(raw["speed"]) == 1.2
    assert float(raw["heading"]) == 90.0
    assert float(raw["device_timestamp"]) == 1_760_000_000.0
    assert float(raw["server_timestamp"]) > 0
    ttl = await fake_redis.ttl(key)
    assert 0 < ttl <= LIVE_TTL_SECONDS


async def test_post_requires_auth(api, seed, fake_redis):
    assert (await api.post(BASE, json=_payload())).status_code == 401
    assert (await api.get(BASE)).status_code == 401


async def test_post_forbidden_roles(api, seed, fake_redis):
    """require_attendance_participant: SA+EMPLOYEE only; and the service
    additionally requires a linked employee_id (SA has none → 403)."""
    for who in ("pm", "hr", "admin", "emp_user2"):
        res = await api.post(
            BASE, json=_payload(), headers=_auth(seed[who])
        )
        assert res.status_code == 403, who
        res = await api.get(BASE, headers=_auth(seed[who]))
        assert res.status_code == 403, who


async def test_body_employee_id_is_ignored(api, seed, fake_redis):
    """Identity comes from the token — a spoofed employee_id in the body
    must not write another employee's key."""
    other = uuid.uuid4()
    res = await api.post(
        BASE,
        json=_payload(employee_id=str(other)),
        headers=_auth(seed["emp_user"]),
    )
    assert res.status_code == 200
    assert await fake_redis.exists(location_key(seed["employee"].id)) == 1
    assert await fake_redis.exists(location_key(other)) == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("latitude", 91.0),
        ("latitude", -90.5),
        ("longitude", 180.5),
        ("longitude", -181.0),
        ("accuracy", -1.0),
        ("speed", -0.5),
        ("heading", 361.0),
        ("heading", -1.0),
        ("timestamp", 0.0),
        ("timestamp", -500.0),
        ("timestamp", "garbage"),
        ("latitude", "north"),
    ],
)
async def test_invalid_fix_rejected_422(api, seed, fake_redis, field, value):
    res = await api.post(
        BASE, json=_payload(**{field: value}), headers=_auth(seed["emp_user"])
    )
    assert res.status_code == 422
    assert await fake_redis.dbsize() == 0  # nothing written


async def test_second_write_overwrites_latest_only(api, seed, fake_redis):
    """Latest-only: a second POST replaces the hash — including dropping
    optional fields the new fix doesn't carry (no stale speed leak)."""
    await api.post(BASE, json=_payload(speed=3.3), headers=_auth(seed["emp_user"]))
    res = await api.post(
        BASE,
        json=_payload(latitude=13.0, longitude=78.0),
        headers=_auth(seed["emp_user"]),
    )
    assert res.status_code == 200

    got = await api.get(BASE, headers=_auth(seed["emp_user"]))
    body = got.json()
    assert body["is_live"] is True
    assert body["latitude"] == 13.0 and body["longitude"] == 78.0
    assert body["speed"] is None  # first fix's speed must not leak


async def test_ttl_refreshed_on_each_write(api, seed, fake_redis):
    await api.post(BASE, json=_payload(), headers=_auth(seed["emp_user"]))
    key = location_key(seed["employee"].id)
    await fake_redis.expire(key, 10)  # simulate a nearly-expired key
    await api.post(BASE, json=_payload(), headers=_auth(seed["emp_user"]))
    assert await fake_redis.ttl(key) > 10


# ---------------------------------------------------------------------------
# GET /location/current
# ---------------------------------------------------------------------------


async def test_get_missing_key_is_not_live(api, seed, fake_redis):
    res = await api.get(BASE, headers=_auth(seed["emp_user"]))
    assert res.status_code == 200
    body = res.json()
    assert body["is_live"] is False
    assert body["latitude"] is None and body["longitude"] is None


async def test_get_returns_own_fix(api, seed, fake_redis):
    await api.post(
        BASE, json=_payload(heading=180.0), headers=_auth(seed["emp_user"])
    )
    res = await api.get(BASE, headers=_auth(seed["emp_user"]))
    assert res.status_code == 200
    body = res.json()
    assert body["is_live"] is True
    assert body["employee_uid"] == str(seed["employee"].id)
    assert body["latitude"] == 12.9716
    assert body["heading"] == 180.0
    assert body["age_seconds"] is not None and body["age_seconds"] >= 0


async def test_cannot_read_other_employees_key(api, seed, fake_redis):
    """The GET path only ever reads the caller's own key — a foreign key
    already in Redis is invisible to this caller."""
    foreign = location_key(uuid.uuid4())
    await fake_redis.hset(foreign, mapping={
        "latitude": "1.0", "longitude": "2.0", "accuracy": "5.0",
        "device_timestamp": "1", "server_timestamp": "1",
    })
    res = await api.get(BASE, headers=_auth(seed["emp_user"]))
    body = res.json()
    assert body["is_live"] is False and body["latitude"] is None


# ---------------------------------------------------------------------------
# Degradation — Redis is the only store; no Postgres fallback
# ---------------------------------------------------------------------------


async def test_post_returns_clean_503_when_redis_down(api, seed, no_redis):
    res = await api.post(
        BASE, json=_payload(), headers=_auth(seed["emp_user"])
    )
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "LIVE_LOCATION_UNAVAILABLE"


async def test_get_degrades_to_not_live_when_redis_down(api, seed, no_redis):
    res = await api.get(BASE, headers=_auth(seed["emp_user"]))
    assert res.status_code == 200
    assert res.json()["is_live"] is False


async def test_post_503_when_redis_write_fails(api, seed, monkeypatch):
    """Client exists but the pipeline raises → clean 503, not a 500."""
    class _BrokenRedis:
        def pipeline(self, transaction=False):
            raise ConnectionError("redis gone")

    async def _get():
        return _BrokenRedis()

    monkeypatch.setattr(redis_core, "get_redis", _get)

    res = await api.post(
        BASE, json=_payload(), headers=_auth(seed["emp_user"])
    )
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "LIVE_LOCATION_UNAVAILABLE"


# ---------------------------------------------------------------------------
# No Postgres in the POST path
# ---------------------------------------------------------------------------


def test_post_route_takes_no_db_session():
    """The route depends on auth only — no get_db/session parameter.
    (get_current_user internally loads the User once; that's existing
    auth-middleware behavior, not a location write path.)"""
    params = inspect.signature(post_current_location).parameters
    assert "session" not in params
    assert all(
        getattr(p.default, "dependency", None) is not get_db
        for p in params.values()
    )


async def test_post_performs_no_db_writes(api, seed, fake_redis, session):
    res = await api.post(
        BASE, json=_payload(), headers=_auth(seed["emp_user"])
    )
    assert res.status_code == 200
    assert len(session.new) == 0 and len(session.dirty) == 0
