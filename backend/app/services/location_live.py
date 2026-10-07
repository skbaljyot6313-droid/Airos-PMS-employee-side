"""Live employee location — CURRENT-STATE-ONLY positions in Redis.

This is a deliberately separate feature from the location_events table
(attendance/task taps): Postgres owns event history; Redis holds each
employee's LATEST fix and nothing else. There is no history here —
every POST overwrites the hash and re-arms a 60 s TTL, so a stale fix
self-evicts.

Key: mt:location:emp:{employee_id}  (project convention mt:{domain}:{scope}:{id})
Fields: latitude, longitude, accuracy, speed?, heading?,
        device_timestamp (client clock), server_timestamp (utcnow epoch)

Active index: ZSET `mt:location` — member=str(employee_id),
score=expiry epoch (write-time server now + TTL). Server-to-server
readers list the live set by score without a SCAN: members whose score
<= now are dead and get purged on read; members whose hash raced to
expiry are skipped on the existence check.

Degradation: Redis is the ONLY store. POST with no usable Redis → clean
503 (LiveLocationUnavailable); GET degrades to {is_live: false} so the
polling client never hard-fails. employee_id comes from the authed user —
never from the request body.

Coordinates are never logged — only the employee id.
"""

import math
import time
import uuid

from app.core import redis as redis_core
from app.core.exceptions import LiveLocationUnavailable
from app.core.logging import get_logger
from app.models.user import User
from app.schemas.location import LocationUpdate
from app.services.structure import ValidationErr

logger = get_logger("app.location_live")

LIVE_TTL_SECONDS = 60
LIVE_INDEX_KEY = "mt:location"

_HASH_FIELDS = (
    "latitude",
    "longitude",
    "accuracy",
    "speed",
    "heading",
    "device_timestamp",
    "server_timestamp",
)


def location_key(employee_id: uuid.UUID) -> str:
    return f"mt:location:emp:{employee_id}"


def _require_employee(user: User) -> uuid.UUID:
    from app.dependencies.auth import Forbidden

    if user.employee_id is None:
        raise Forbidden("Your account is not linked to an employee record.")
    return user.employee_id


def _validate(payload: LocationUpdate) -> None:
    """Belt-and-braces re-check (the route's Pydantic layer already
    enforced the same ranges — direct service callers get them too).
    Minor GPS noise is fine; only malformed/out-of-range values fail."""
    checks = (
        (-90.0 <= payload.latitude <= 90.0),
        (-180.0 <= payload.longitude <= 180.0),
        (payload.accuracy >= 0.0),
        (payload.speed is None or payload.speed >= 0.0),
        (payload.heading is None or 0.0 <= payload.heading <= 360.0),
        (math.isfinite(payload.timestamp) and payload.timestamp > 0.0),
    )
    if not all(checks):
        raise ValidationErr("Invalid location update.", field="latitude")


def _num(value) -> str:
    """Compact decimal string for Redis — repr keeps float precision."""
    return repr(float(value))


async def post_current(user: User, payload: LocationUpdate) -> dict:
    """Overwrite the caller's current fix and re-arm the TTL.

    One pipelined round trip: DEL (stale optional fields must not leak
    between fixes) + HSET + EXPIRE + ZADD into the active-location index
    (score = expiry epoch, same clock/TTL source as the hash so the two
    can't diverge beyond write races — the reader's existence check
    covers those). No Postgres in this path — the employee scope is
    already on the authed user.
    """
    employee_id = _require_employee(user)
    _validate(payload)

    client = await redis_core.get_redis()
    if client is None:
        raise LiveLocationUnavailable()

    server_ts = time.time()
    fields = {
        "latitude": _num(payload.latitude),
        "longitude": _num(payload.longitude),
        "accuracy": _num(payload.accuracy),
        "device_timestamp": _num(payload.timestamp),
        "server_timestamp": _num(server_ts),
    }
    if payload.speed is not None:
        fields["speed"] = _num(payload.speed)
    if payload.heading is not None:
        fields["heading"] = _num(payload.heading)

    key = location_key(employee_id)
    try:
        pipe = client.pipeline(transaction=False)
        pipe.delete(key)
        pipe.hset(key, mapping=fields)
        pipe.expire(key, LIVE_TTL_SECONDS)
        pipe.zadd(LIVE_INDEX_KEY, {str(employee_id): server_ts + LIVE_TTL_SECONDS})
        await pipe.execute()
    except Exception as exc:
        # Redis client present but the write failed — no fallback store.
        logger.warning(
            "live location write failed for employee %s: %s",
            employee_id, type(exc).__name__,
        )
        raise LiveLocationUnavailable() from exc

    logger.debug("live location updated for employee %s", employee_id)
    return {
        "recorded": True,
        "server_timestamp": server_ts,
        "expires_in": LIVE_TTL_SECONDS,
    }


def _parse(raw: dict) -> dict:
    """Hash strings → typed response; unknown/missing fields → None."""
    out = {name: None for name in _HASH_FIELDS}
    for name in _HASH_FIELDS:
        if name in raw:
            try:
                out[name] = float(raw[name])
            except (TypeError, ValueError):
                out[name] = None
    return out


async def get_current(user: User) -> dict:
    """The caller's own latest fix — {is_live: false} when absent or
    Redis is unreachable (latest-only: a missed/expired key is simply
    'not live'). No other employee's key is ever read."""
    employee_id = _require_employee(user)
    base = {"is_live": False, "employee_uid": str(employee_id)}

    client = await redis_core.get_redis()
    if client is None:
        return {**base, **{name: None for name in _HASH_FIELDS},
                "age_seconds": None}

    try:
        raw = await client.hgetall(location_key(employee_id))
    except Exception as exc:
        logger.warning(
            "live location read failed for employee %s: %s",
            employee_id, type(exc).__name__,
        )
        return {**base, **{name: None for name in _HASH_FIELDS},
                "age_seconds": None}

    if not raw:
        return {**base, **{name: None for name in _HASH_FIELDS},
                "age_seconds": None}

    parsed = _parse(raw)
    server_ts = parsed.pop("server_timestamp")
    age = time.time() - server_ts if server_ts is not None else None
    return {
        **base,
        "is_live": True,
        "latitude": parsed["latitude"],
        "longitude": parsed["longitude"],
        "accuracy": parsed["accuracy"],
        "speed": parsed["speed"],
        "heading": parsed["heading"],
        "device_timestamp": parsed["device_timestamp"],
        "server_timestamp": server_ts,
        "age_seconds": age,
    }


async def get_all_live() -> dict:
    """Server-to-server snapshot: every employee whose fix is still live.

    The ZSET `mt:location` is the index — member=str(employee_id),
    score=expiry epoch. One pipeline: ZREMRANGEBYSCORE purges dead
    members (keeps the index small — it's the only cleanup it gets,
    since members have no TTL of their own), then ZRANGEBYSCORE returns
    the survivors. A second pipeline HGETALLs each surviving hash in ONE
    round trip regardless of count — no SCAN, no Postgres, no N+1.
    A member can race-expire between the ZRANGE and the HGETALL, so an
    empty hash is skipped, not emitted.

    Response carries employee UUIDs and coordinates ONLY — no names or
    employee metadata. The SA backend joins identity on its side; doing
    it here would be an N+1 users/employees lookup across properties
    (and this path deliberately never opens a DB session).

    Redis down → LiveLocationUnavailable (503) — same contract as POST.
    Only the member count and latency are logged, never coordinates.
    """
    client = await redis_core.get_redis()
    if client is None:
        raise LiveLocationUnavailable()

    started = time.monotonic()
    now = time.time()
    try:
        pipe = client.pipeline(transaction=False)
        pipe.zremrangebyscore(LIVE_INDEX_KEY, "-inf", now)
        pipe.zrangebyscore(LIVE_INDEX_KEY, now, "+inf")
        _, member_ids = await pipe.execute()

        if member_ids:
            pipe = client.pipeline(transaction=False)
            for member_id in member_ids:
                pipe.hgetall(f"mt:location:emp:{member_id}")
            hashes = await pipe.execute()
        else:
            hashes = []
    except Exception as exc:
        logger.warning(
            "live location index read failed: %s", type(exc).__name__
        )
        raise LiveLocationUnavailable() from exc

    employees = []
    for member_id, raw in zip(member_ids, hashes):
        if not raw:
            continue  # hash expired between ZRANGE and HGETALL
        try:
            parsed = _parse(raw)
        except Exception:
            # _parse already degrades bad field values to None — this belt
            # covers a corrupt record shape. One malformed member must
            # never take down the whole snapshot.
            logger.warning(
                "skipping malformed live-location record for member %s",
                member_id,
            )
            continue
        if any(
            parsed[field] is None
            for field in (
                "latitude",
                "longitude",
                "accuracy",
                "device_timestamp",
                "server_timestamp",
            )
        ):
            # Missing/non-numeric required field — skip this entry rather
            # than emit a half-populated record to the SA backend.
            logger.warning(
                "skipping live-location record with malformed fields "
                "for member %s",
                member_id,
            )
            continue
        employees.append({
            "employee_id": str(member_id),
            "latitude": parsed["latitude"],
            "longitude": parsed["longitude"],
            "accuracy": parsed["accuracy"],
            "device_timestamp": parsed["device_timestamp"],
            "server_timestamp": parsed["server_timestamp"],
            "speed": parsed["speed"],      # null when absent — same as GET /current
            "heading": parsed["heading"],  # null when absent
            "is_live": True,
        })

    logger.debug(
        "live location snapshot: %d live of %d indexed in %.1fms",
        len(employees), len(member_ids),
        (time.monotonic() - started) * 1000,
    )
    return {"employees": employees}
