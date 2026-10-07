"""GET /admin/live-locations — server-to-server live-position snapshot.

Same harness as test_live_location.py (httpx ASGI + fakeredis at the
get_redis seam) but the auth under test is the SERVICE key, not a user
JWT: LOCATION_SERVICE_API_KEY via Authorization: Bearer, verified
constant-time. No DB session anywhere in the request path.

Index under test: ZSET `mt:location` member=str(employee_id),
score=expiry epoch — the admin read purges dead scores, ranges the
live ones, and pipelined-HGETALLs the hashes (skipping any that
race-expired between the two round trips).
"""

import inspect
import time
import uuid

import fakeredis.aioredis
import httpx
import pytest

from app.api.v1.admin import get_live_locations
from app.core import redis as redis_core
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token
from app.dependencies.auth import require_location_service
from app.main import app
from app.services.location_live import (
    LIVE_INDEX_KEY,
    LIVE_TTL_SECONDS,
    location_key,
)

ADMIN = "/api/v1/admin/live-locations"
POST = "/api/v1/location/current"
SERVICE_KEY = "test-service-key"


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
    async def _get():
        return None

    monkeypatch.setattr(redis_core, "get_redis", _get)


@pytest.fixture
def service_key(monkeypatch):
    monkeypatch.setattr(settings, "LOCATION_SERVICE_API_KEY", SERVICE_KEY)


@pytest.fixture
def no_service_key(monkeypatch):
    monkeypatch.setattr(settings, "LOCATION_SERVICE_API_KEY", None)


@pytest.fixture
async def api(session):
    async def _db():
        yield session

    app.dependency_overrides[get_db] = _db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        yield client
    app.dependency_overrides.pop(get_db, None)


def _key_auth(key: str = SERVICE_KEY) -> dict:
    return {"Authorization": f"Bearer {key}"}


def _user_auth(user) -> dict:
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


async def _seed_fix(redis, employee_id: uuid.UUID, live: bool = True, **fields):
    """Plant a hash + index member directly, as a POST would."""
    mapping = {
        "latitude": "1.5",
        "longitude": "2.5",
        "accuracy": "10.0",
        "device_timestamp": "1760000000",
        "server_timestamp": str(time.time()),
    }
    mapping.update({k: str(v) for k, v in fields.items()})
    await redis.hset(location_key(employee_id), mapping=mapping)
    score = time.time() + (LIVE_TTL_SECONDS if live else -LIVE_TTL_SECONDS)
    await redis.zadd(LIVE_INDEX_KEY, {str(employee_id): score})


# ---------------------------------------------------------------------------
# Auth — service key only, never employee JWT, fail closed when unset
# ---------------------------------------------------------------------------


async def test_valid_service_key_returns_200(api, service_key, fake_redis):
    res = await api.get(ADMIN, headers=_key_auth())
    assert res.status_code == 200


async def test_missing_authorization_header_is_401(
    api, service_key, fake_redis
):
    res = await api.get(ADMIN)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_wrong_key_is_401(api, service_key, fake_redis):
    res = await api.get(ADMIN, headers=_key_auth("wrong-key"))
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_employee_jwt_is_not_accepted(api, seed, service_key, fake_redis):
    """This endpoint is server-to-server — a valid EMPLOYEE token must
    fail. The JWT is never decoded; it's simply a wrong key."""
    res = await api.get(ADMIN, headers=_user_auth(seed["emp_user"]))
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_non_bearer_scheme_is_401(api, service_key, fake_redis):
    res = await api.get(ADMIN, headers={"Authorization": f"Basic {SERVICE_KEY}"})
    assert res.status_code == 401


async def test_unset_key_fails_closed_503(api, no_service_key, fake_redis):
    """Fail closed: an unconfigured key is a loud 503, never open auth
    and never a silent 401 for every caller."""
    res = await api.get(ADMIN, headers=_key_auth())
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "LIVE_LOCATION_UNAVAILABLE"


# ---------------------------------------------------------------------------
# Snapshot contents
# ---------------------------------------------------------------------------


async def test_empty_index_returns_empty_list(api, service_key, fake_redis):
    res = await api.get(ADMIN, headers=_key_auth())
    assert res.status_code == 200
    assert res.json() == {"employees": []}


async def test_posted_fix_appears_with_exact_fields(
    api, seed, service_key, fake_redis
):
    await api.post(
        POST,
        json=_payload(speed=1.2, heading=90.0),
        headers=_user_auth(seed["emp_user"]),
    )
    res = await api.get(ADMIN, headers=_key_auth())
    assert res.status_code == 200
    employees = res.json()["employees"]
    assert len(employees) == 1
    emp = employees[0]
    assert emp["employee_id"] == str(seed["employee"].id)
    assert emp["latitude"] == 12.9716
    assert emp["longitude"] == 77.5946
    assert emp["accuracy"] == 8.0
    assert emp["device_timestamp"] == 1_760_000_000.0
    assert emp["server_timestamp"] > 0
    assert emp["speed"] == 1.2
    assert emp["heading"] == 90.0
    assert emp["is_live"] is True
    # UUIDs only — no employee/user metadata leaks into the contract
    assert "name" not in emp and "email" not in emp


async def test_absent_optional_fields_are_null(
    api, seed, service_key, fake_redis
):
    await api.post(POST, json=_payload(), headers=_user_auth(seed["emp_user"]))
    res = await api.get(ADMIN, headers=_key_auth())
    emp = res.json()["employees"][0]
    assert emp["speed"] is None and emp["heading"] is None


async def test_expired_member_excluded_and_purged(
    api, service_key, fake_redis
):
    stale = uuid.uuid4()
    await _seed_fix(fake_redis, stale, live=False)  # score in the past
    res = await api.get(ADMIN, headers=_key_auth())
    assert res.json() == {"employees": []}
    # The read purged the dead member — index stays small.
    assert await fake_redis.zcard(LIVE_INDEX_KEY) == 0


async def test_member_whose_hash_expired_is_skipped(
    api, service_key, fake_redis
):
    """Race belt: index says live (score > now) but the hash is gone —
    HGETALL returns {} and the member is omitted, not emitted empty."""
    ghost = uuid.uuid4()
    await fake_redis.zadd(
        LIVE_INDEX_KEY, {str(ghost): time.time() + LIVE_TTL_SECONDS}
    )  # no hash written
    res = await api.get(ADMIN, headers=_key_auth())
    assert res.status_code == 200
    assert res.json() == {"employees": []}


async def test_multiple_employees_listed(api, seed, service_key, fake_redis):
    other = uuid.uuid4()
    await _seed_fix(fake_redis, other, speed="3.0")
    await api.post(
        POST, json=_payload(), headers=_user_auth(seed["emp_user"])
    )
    res = await api.get(ADMIN, headers=_key_auth())
    employees = res.json()["employees"]
    ids = {e["employee_id"] for e in employees}
    assert ids == {str(seed["employee"].id), str(other)}


async def test_dead_member_filtered_from_mixed_set(
    api, seed, service_key, fake_redis
):
    stale = uuid.uuid4()
    await _seed_fix(fake_redis, stale, live=False)
    await api.post(
        POST, json=_payload(), headers=_user_auth(seed["emp_user"])
    )
    res = await api.get(ADMIN, headers=_key_auth())
    ids = {e["employee_id"] for e in res.json()["employees"]}
    assert ids == {str(seed["employee"].id)}


async def test_malformed_member_skipped_not_emitted(
    api, seed, service_key, fake_redis
):
    """A corrupt hash (non-numeric lat, missing fields, stray garbage)
    is skipped per-entry — it must neither crash the response nor reach
    the client as a half-populated record. Valid members still appear."""
    bad = uuid.uuid4()
    await fake_redis.hset(
        location_key(bad),
        mapping={
            "latitude": "north-by-northwest",  # non-numeric
            "longitude": "2.5",
            "junk_field": "💥",
        },
    )
    await fake_redis.zadd(
        LIVE_INDEX_KEY, {str(bad): time.time() + LIVE_TTL_SECONDS}
    )
    await api.post(
        POST, json=_payload(), headers=_user_auth(seed["emp_user"])
    )
    res = await api.get(ADMIN, headers=_key_auth())
    assert res.status_code == 200
    employees = res.json()["employees"]
    assert [e["employee_id"] for e in employees] == [
        str(seed["employee"].id)
    ]
    assert all(e["latitude"] is not None for e in employees)


async def test_malformed_only_member_yields_empty_list(
    api, service_key, fake_redis
):
    bad = uuid.uuid4()
    await fake_redis.hset(location_key(bad), mapping={"wat": "?"})
    await fake_redis.zadd(
        LIVE_INDEX_KEY, {str(bad): time.time() + LIVE_TTL_SECONDS}
    )
    res = await api.get(ADMIN, headers=_key_auth())
    assert res.status_code == 200
    assert res.json() == {"employees": []}


# ---------------------------------------------------------------------------
# Degradation
# ---------------------------------------------------------------------------


async def test_503_when_redis_unconfigured(api, service_key, no_redis):
    res = await api.get(ADMIN, headers=_key_auth())
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "LIVE_LOCATION_UNAVAILABLE"


async def test_503_when_redis_read_fails(api, service_key, monkeypatch):
    class _BrokenRedis:
        def pipeline(self, transaction=False):
            raise ConnectionError("redis gone")

    async def _get():
        return _BrokenRedis()

    monkeypatch.setattr(redis_core, "get_redis", _get)
    res = await api.get(ADMIN, headers=_key_auth())
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "LIVE_LOCATION_UNAVAILABLE"


# ---------------------------------------------------------------------------
# No Postgres in the admin path
# ---------------------------------------------------------------------------


def test_admin_route_takes_no_db_session():
    """Neither the route nor its service-auth guard may depend on get_db
    — the read path is Redis-only (same trick as the POST test)."""
    for fn in (get_live_locations, require_location_service):
        params = inspect.signature(fn).parameters
        assert "session" not in params
        assert all(
            getattr(p.default, "dependency", None) is not get_db
            for p in params.values()
        )


async def test_admin_performs_no_db_writes(
    api, seed, service_key, fake_redis, session
):
    await api.post(POST, json=_payload(), headers=_user_auth(seed["emp_user"]))
    res = await api.get(ADMIN, headers=_key_auth())
    assert res.status_code == 200
    assert len(session.new) == 0 and len(session.dirty) == 0
