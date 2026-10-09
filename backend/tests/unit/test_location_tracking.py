"""Tracking sessions + historical location + admin filters.

Same harness as the other location suites (httpx ASGI + fakeredis at
the get_redis seam, get_db overridden to the in-memory session).
Covered: session lifecycle, ingestion dedup, day-partitioned history,
GEO index writes, quality flags, rate limit, stale semantics, and the
admin history contract.
"""

import json
import time
import uuid
from datetime import datetime, timedelta, timezone

import fakeredis.aioredis
import httpx
import pytest

from app.core import rate_limit as rate_limit_mod
from app.core import redis as redis_core
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.services import location_tracking as tracking
from app.services.location_live import LIVE_INDEX_KEY, location_key

BASE = "/api/v1/location"
ADMIN = "/api/v1/admin"
SERVICE_KEY = "test-service-key"


@pytest.fixture
async def fake_redis(monkeypatch):
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def _get():
        return client

    # The rate limiter holds its own `get_redis` binding — patch both or
    # it fails open against the real client and never limits.
    monkeypatch.setattr(redis_core, "get_redis", _get)
    monkeypatch.setattr(rate_limit_mod, "get_redis", _get)
    yield client
    await client.aclose()


@pytest.fixture
def service_key(monkeypatch):
    monkeypatch.setattr(settings, "LOCATION_SERVICE_API_KEY", SERVICE_KEY)


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


def _auth(user) -> dict:
    token = create_access_token(
        user_id=str(user.id),
        company_id=str(user.company_id),
        role=user.role.value,
    )
    return {"Authorization": f"Bearer {token}"}


def _key() -> dict:
    return {"Authorization": f"Bearer {SERVICE_KEY}"}


def _svc_header() -> dict:
    return {"X-Location-Service-Key": SERVICE_KEY}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fix(sid, seq, lat=12.9716, lng=77.5946, captured=None, **over):
    body = {
        "latitude": lat,
        "longitude": lng,
        "accuracy_m": 8.0,
        "accuracy": 8.0,
        "captured_at": captured or _now_iso(),
        "tracking_session_id": str(sid),
        "sequence_number": seq,
        "source": "fused",
    }
    body.update(over)
    return body


async def _start(api, seed) -> uuid.UUID:
    res = await api.post(f"{BASE}/start", headers=_auth(seed["emp_user"]))
    assert res.status_code == 200, res.text
    return uuid.UUID(res.json()["tracking_session_id"])


# ---------------------------------------------------------------------------
# POST /location/start + /location/stop
# ---------------------------------------------------------------------------


async def test_start_returns_session(api, seed, fake_redis):
    sid = await _start(api, seed)
    marker = json.loads(
        await fake_redis.get(tracking.session_key(sid))
    )
    assert marker["e"] == str(seed["employee"].id)
    assert marker["s"] == "active"


async def test_start_requires_auth(api, fake_redis):
    assert (await api.post(f"{BASE}/start")).status_code == 401


async def test_multiple_sessions_per_employee(api, seed, fake_redis):
    a = await _start(api, seed)
    b = await _start(api, seed)
    assert a != b


async def test_stop_marks_session_and_rejects_further_ingest(
    api, seed, fake_redis
):
    sid = await _start(api, seed)
    res = await api.post(
        f"{BASE}/stop",
        json={"tracking_session_id": str(sid)},
        headers=_auth(seed["emp_user"]),
    )
    assert res.status_code == 200
    assert res.json()["stopped"] is True
    assert await fake_redis.exists(tracking.session_key(sid)) == 0
    res = await api.post(
        f"{BASE}/current", json=_fix(sid, 1), headers=_auth(seed["emp_user"])
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_TRACKING_SESSION"


async def test_stop_rejects_foreign_session(api, seed, fake_redis):
    sid = await _start(api, seed)
    other = uuid.uuid4()
    res = await api.post(
        f"{BASE}/stop",
        json={"tracking_session_id": str(other)},
        headers=_auth(seed["emp_user"]),
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "TRACKING_SESSION_NOT_FOUND"


async def test_location_with_unknown_session_rejected(
    api, seed, fake_redis, monkeypatch
):
    # The limiter writes a counter key before session validation; this
    # test asserts no location keys are persisted, so pin the limiter
    # off instead of depending on ambient env.
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    res = await api.post(
        f"{BASE}/current",
        json=_fix(uuid.uuid4(), 1),
        headers=_auth(seed["emp_user"]),
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_TRACKING_SESSION"
    assert await fake_redis.dbsize() == 0  # nothing written


# ---------------------------------------------------------------------------
# Ingest — history, geo, dedup, quality
# ---------------------------------------------------------------------------


async def test_ingest_writes_all_views(api, seed, fake_redis):
    sid = await _start(api, seed)
    res = await api.post(
        f"{BASE}/current", json=_fix(sid, 1), headers=_auth(seed["emp_user"])
    )
    assert res.status_code == 200
    body = res.json()
    assert body["accepted"] is True
    assert body["duplicate"] is False
    assert body["quality"] == "valid"
    assert body["received_at"] and body["location_timestamp"]

    emp = seed["employee"].id
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # live hash
    raw = await fake_redis.hgetall(location_key(emp))
    assert raw["tracking_session_id"] == str(sid)
    assert raw["quality"] == "valid"
    assert 0 < await fake_redis.ttl(location_key(emp)) <= \
        settings.LOCATION_CURRENT_TTL_SECONDS
    # index
    assert await fake_redis.zscore(LIVE_INDEX_KEY, str(emp)) is not None
    # history partition
    members = await fake_redis.zrange(
        tracking.history_key(emp, datetime.now(timezone.utc)), 0, -1
    )
    assert len(members) == 1
    rec = json.loads(members[0])
    assert rec["seq"] == 1 and rec["sid"] == str(sid)
    # geo index
    gkey = tracking.geo_key(datetime.now(timezone.utc))
    assert await fake_redis.zcard(gkey) == 1


async def test_duplicate_event_is_idempotent(api, seed, fake_redis):
    """Retrying the same (session, seq) acks as a duplicate and writes
    exactly one history point."""
    sid = await _start(api, seed)
    fix = _fix(sid, 7)
    await api.post(
        f"{BASE}/current", json=fix, headers=_auth(seed["emp_user"])
    )
    res = await api.post(
        f"{BASE}/current", json=fix, headers=_auth(seed["emp_user"])
    )
    assert res.status_code == 200
    assert res.json()["duplicate"] is True

    emp = seed["employee"].id
    members = await fake_redis.zrange(
        tracking.history_key(emp, datetime.now(timezone.utc)), 0, -1
    )
    assert len(members) == 1


async def test_delayed_point_uses_captured_order(api, seed, fake_redis):
    """A point replayed after reconnect lands in history at its captured
    position and does not clobber the fresher live hash."""
    sid = await _start(api, seed)
    now = datetime.now(timezone.utc)
    old = (now - timedelta(hours=2)).isoformat()
    # fresh point first
    await api.post(
        f"{BASE}/current",
        json=_fix(sid, 2, lat=13.0, captured=now.isoformat()),
        headers=_auth(seed["emp_user"]),
    )
    # delayed older point arrives second
    res = await api.post(
        f"{BASE}/current",
        json=_fix(sid, 1, lat=10.0, captured=old),
        headers=_auth(seed["emp_user"]),
    )
    assert res.status_code == 200

    emp = seed["employee"].id
    live = await fake_redis.hgetall(location_key(emp))
    assert float(live["latitude"]) == 13.0  # older fix did not clobber
    members = await fake_redis.zrange(
        tracking.history_key(emp, now), 0, -1, withscores=True
    )
    scores = [s for _, s in members]
    assert scores == sorted(scores)  # chronological by capture time


async def test_future_timestamp_rejected(api, seed, fake_redis):
    sid = await _start(api, seed)
    future = (
        datetime.now(timezone.utc)
        + timedelta(seconds=settings.LOCATION_MAX_FUTURE_SKEW_SECONDS + 60)
    ).isoformat()
    res = await api.post(
        f"{BASE}/current",
        json=_fix(sid, 1, captured=future),
        headers=_auth(seed["emp_user"]),
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_TIMESTAMP"


async def test_low_accuracy_flagged_not_dropped(api, seed, fake_redis):
    sid = await _start(api, seed)
    res = await api.post(
        f"{BASE}/current",
        json=_fix(sid, 1, accuracy_m=10_000.0, accuracy=10_000.0),
        headers=_auth(seed["emp_user"]),
    )
    assert res.status_code == 200
    assert res.json()["quality"] == "low_accuracy"
    members = await fake_redis.zrange(
        tracking.history_key(
            seed["employee"].id, datetime.now(timezone.utc)
        ),
        0, -1,
    )
    assert len(members) == 1


async def test_impossible_speed_flagged(api, seed, fake_redis):
    sid = await _start(api, seed)
    await api.post(
        f"{BASE}/current",
        json=_fix(sid, 1),
        headers=_auth(seed["emp_user"]),
    )
    # ~111 km away 30 s later — physically impossible
    res = await api.post(
        f"{BASE}/current",
        json=_fix(sid, 2, lat=14.0, lng=78.0,
                  captured=(datetime.now(timezone.utc)
                            + timedelta(seconds=30)).isoformat()),
        headers=_auth(seed["emp_user"]),
    )
    assert res.status_code == 200
    assert res.json()["quality"] == "suspicious_speed"


async def test_ingest_rate_limit(api, seed, fake_redis, monkeypatch):
    # The dev .env disables limiting — enable it for this assertion.
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "LOCATION_RATE_LIMIT_PER_MINUTE", 2)
    sid = await _start(api, seed)
    for seq in (1, 2):
        res = await api.post(
            f"{BASE}/current",
            json=_fix(sid, seq),
            headers=_auth(seed["emp_user"]),
        )
        assert res.status_code == 200
    res = await api.post(
        f"{BASE}/current", json=_fix(sid, 3), headers=_auth(seed["emp_user"])
    )
    assert res.status_code == 429
    assert res.json()["error"]["code"] == "LOCATION_RATE_LIMITED"


async def test_ingest_503_when_redis_down(api, seed, monkeypatch):
    async def _none():
        return None

    monkeypatch.setattr(redis_core, "get_redis", _none)
    res = await api.post(
        f"{BASE}/current",
        json={
            "latitude": 1.0, "longitude": 2.0, "accuracy": 5.0,
            "timestamp": time.time(),
        },
        headers=_auth(seed["emp_user"]),
    )
    assert res.status_code == 503


# ---------------------------------------------------------------------------
# Admin — live filters + history contract
# ---------------------------------------------------------------------------


async def test_live_locations_employee_filter(api, seed, service_key, fake_redis):
    sid = await _start(api, seed)
    await api.post(
        f"{BASE}/current", json=_fix(sid, 1), headers=_auth(seed["emp_user"])
    )
    emp = seed["employee"].id
    res = await api.get(
        f"{ADMIN}/live-locations?employee_id={emp}", headers=_key()
    )
    locs = res.json()["locations"]
    assert len(locs) == 1
    assert locs[0]["employee_id"] == str(emp)
    assert locs[0]["is_stale"] is False

    res = await api.get(
        f"{ADMIN}/live-locations?employee_id={uuid.uuid4()}",
        headers=_key(),
    )
    assert res.json() == {"locations": []}


async def test_live_locations_stale_entry(api, seed, service_key, fake_redis):
    emp = seed["employee"].id
    res = await api.get(
        f"{ADMIN}/live-locations?employee_id={emp}&is_active=false",
        headers=_key(),
    )
    locs = res.json()["locations"]
    assert len(locs) == 1
    assert locs[0]["is_stale"] is True
    assert locs[0]["latitude"] is None


async def test_live_locations_property_filter(api, seed, service_key, fake_redis):
    sid = await _start(api, seed)
    await api.post(
        f"{BASE}/current", json=_fix(sid, 1), headers=_auth(seed["emp_user"])
    )
    prop = seed["prop"].id
    res = await api.get(
        f"{ADMIN}/live-locations?property_id={prop}", headers=_key()
    )
    ids = {e["employee_id"] for e in res.json()["locations"]}
    assert ids == {str(seed["employee"].id)}
    # a different property sees nobody
    res = await api.get(
        f"{ADMIN}/live-locations?property_id={uuid.uuid4()}",
        headers=_key(),
    )
    assert res.json() == {"locations": []}


async def test_history_endpoint(api, seed, service_key, fake_redis):
    sid = await _start(api, seed)
    for seq, lat in ((1, 12.9), (2, 12.95), (3, 13.0)):
        await api.post(
            f"{BASE}/current",
            json=_fix(sid, seq, lat=lat),
            headers=_auth(seed["emp_user"]),
        )
    emp = seed["employee"].id
    frm = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    to = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    res = await api.get(
        f"{ADMIN}/location-history/{emp}",
        params={"from": frm, "to": to},
        headers=_key(),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["employee_id"] == str(emp)
    assert body["total_points"] == 3
    assert body["returned_points"] == 3
    assert body["downsampled"] is False
    assert [p["sequence_number"] for p in body["points"]] == [1, 2, 3]
    assert all(
        p["latitude"] and p["captured_at"] and p["received_at"]
        for p in body["points"]
    )


async def test_history_session_filter(api, seed, service_key, fake_redis):
    a = await _start(api, seed)
    b = await _start(api, seed)
    await api.post(
        f"{BASE}/current", json=_fix(a, 1), headers=_auth(seed["emp_user"])
    )
    await api.post(
        f"{BASE}/current", json=_fix(b, 1), headers=_auth(seed["emp_user"])
    )
    emp = seed["employee"].id
    frm = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    to = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    res = await api.get(
        f"{ADMIN}/location-history/{emp}",
        params={"from": frm, "to": to, "tracking_session_id": str(a)},
        headers=_key(),
    )
    points = res.json()["points"]
    assert len(points) == 1
    assert points[0]["tracking_session_id"] == str(a)


async def test_history_crosses_day_partition(api, seed, service_key, fake_redis):
    """A range spanning midnight reads both day partitions — captured_at
    midnight-adjacent points land under their capture date."""
    sid = await _start(api, seed)
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)
    await api.post(
        f"{BASE}/current",
        json=_fix(sid, 1, captured=yesterday.isoformat()),
        headers=_auth(seed["emp_user"]),
    )
    await api.post(
        f"{BASE}/current",
        json=_fix(sid, 2, captured=now.isoformat()),
        headers=_auth(seed["emp_user"]),
    )
    emp = seed["employee"].id
    res = await api.get(
        f"{ADMIN}/location-history/{emp}",
        params={
            "from": (yesterday - timedelta(hours=1)).isoformat(),
            "to": (now + timedelta(hours=1)).isoformat(),
        },
        headers=_key(),
    )
    assert res.json()["total_points"] == 2
    # narrow range covering only yesterday's point
    res = await api.get(
        f"{ADMIN}/location-history/{emp}",
        params={
            "from": (yesterday - timedelta(minutes=30)).isoformat(),
            "to": (yesterday + timedelta(minutes=30)).isoformat(),
        },
        headers=_key(),
    )
    assert res.json()["total_points"] == 1


async def test_history_rejects_inverted_range(api, seed, service_key, fake_redis):
    emp = seed["employee"].id
    now = datetime.now(timezone.utc).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    res = await api.get(
        f"{ADMIN}/location-history/{emp}",
        params={"from": now, "to": past},
        headers=_key(),
    )
    assert res.status_code == 400


async def test_live_locations_x_service_key_header(
    api, seed, service_key, fake_redis
):
    """The canonical SA-backend contract is the X-Location-Service-Key
    header — Bearer remains accepted for compatibility."""
    sid = await _start(api, seed)
    await api.post(
        f"{BASE}/current", json=_fix(sid, 1), headers=_auth(seed["emp_user"])
    )
    res = await api.get(f"{ADMIN}/live-locations", headers=_svc_header())
    assert res.status_code == 200
    assert len(res.json()["locations"]) == 1
    # wrong value via the header still fails
    res = await api.get(
        f"{ADMIN}/live-locations",
        headers={"X-Location-Service-Key": "nope"},
    )
    assert res.status_code == 401


async def test_history_requires_service_key(
    api, seed, service_key, fake_redis
):
    emp = seed["employee"].id
    res = await api.get(
        f"{ADMIN}/location-history/{emp}"
        "?from=2026-01-01T00:00:00Z&to=2026-01-02T00:00:00Z",
        headers=_auth(seed["emp_user"]),
    )
    assert res.status_code == 401


async def test_history_downsamples_over_cap(
    api, seed, service_key, fake_redis, monkeypatch
):
    monkeypatch.setattr(settings, "LOCATION_MAX_HISTORY_POINTS", 2)
    sid = await _start(api, seed)
    for seq in (1, 2, 3, 4):
        await api.post(
            f"{BASE}/current",
            json=_fix(sid, seq, captured=(
                datetime.now(timezone.utc) - timedelta(minutes=4 - seq)
            ).isoformat()),
            headers=_auth(seed["emp_user"]),
        )
    emp = seed["employee"].id
    frm = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    to = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    res = await api.get(
        f"{ADMIN}/location-history/{emp}",
        params={"from": frm, "to": to},
        headers=_key(),
    )
    body = res.json()
    assert body["total_points"] == 4
    assert body["returned_points"] == 2
    assert body["downsampled"] is True
