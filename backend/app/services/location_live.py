"""Live employee location — current fix + history ingest in Redis.

This is a deliberately separate feature from the location_events table
(attendance/task taps): Postgres owns session metadata only; Redis
holds each employee's LATEST fix (TTL self-evicts stale state) plus
day-partitioned history and a GEO index (see services/location_tracking
for the full key schema). Every POST overwrites the hash, re-arms the
TTL, appends the fix to today's ZSET partition and the daily GEO index —
one pipeline, one round trip after validation.

Active index: ZSET `mt:location` — member=str(employee_id),
score=expiry epoch (write-time server now + TTL). Server-to-server
readers list the live set by score without a SCAN.

Degradation: Redis is the ONLY store. POST with no usable Redis → clean
503 (LiveLocationUnavailable); GET degrades to {is_live: false} so the
polling client never hard-fails. employee_id comes from the authed user —
never from the request body.

Coordinates are never logged — only the employee id.
"""

import json
import math
import time
import uuid
from datetime import datetime, timezone

from app.core import redis as redis_core
from app.core.config import settings
from app.core.exceptions import LiveLocationUnavailable
from app.core.logging import get_logger
from app.core.rate_limit import RateLimited, check_rate_limit
from app.models.user import User
from app.schemas.location import LocationUpdate
from app.services import location_tracking as tracking
from app.services.structure import ValidationErr

logger = get_logger("app.location_live")

LIVE_INDEX_KEY = "mt:location"

# Numeric hash fields — _parse coerces these; string fields are read
# through verbatim.
_HASH_FIELDS = (
    "latitude",
    "longitude",
    "accuracy",
    "speed",
    "heading",
    "altitude",
    "device_timestamp",
    "server_timestamp",
    "sequence_number",
)
_STR_FIELDS = (
    "captured_at",
    "received_at",
    "tracking_session_id",
    "quality",
    "source",
)


def location_key(employee_id: uuid.UUID) -> str:
    return f"mt:location:emp:{employee_id}"


# Back-compat name — the live TTL is configured
# (LOCATION_CURRENT_TTL_SECONDS); tests import this symbol.
LIVE_TTL_SECONDS = settings.LOCATION_CURRENT_TTL_SECONDS


def _require_employee(user: User) -> uuid.UUID:
    from app.dependencies.auth import Forbidden

    if user.employee_id is None:
        raise Forbidden("Your account is not linked to an employee record.")
    return user.employee_id


def _validate(payload: LocationUpdate) -> None:
    """Belt-and-braces re-check (the route's Pydantic layer already
    enforced the same ranges — direct service callers get them too).
    Minor GPS noise is fine; only malformed/out-of-range values fail."""
    speed = (
        payload.speed_mps
        if payload.speed_mps is not None
        else payload.speed
    )
    bearing = (
        payload.bearing_deg
        if payload.bearing_deg is not None
        else payload.heading
    )
    ts = (
        payload.captured_at.timestamp()
        if payload.captured_at is not None
        else payload.timestamp
    )
    checks = (
        (-90.0 <= payload.latitude <= 90.0),
        (-180.0 <= payload.longitude <= 180.0),
        (payload.accuracy >= 0.0),
        (speed is None or speed >= 0.0),
        (bearing is None or 0.0 <= bearing <= 360.0),
        (
            payload.altitude_m is None
            or math.isfinite(payload.altitude_m)
        ),
        (ts is not None and math.isfinite(ts) and ts > 0.0),
    )
    if not all(checks):
        raise ValidationErr("Invalid location update.", field="latitude")


def _num(value) -> str:
    """Compact decimal string for Redis — repr keeps float precision."""
    return repr(float(value))


async def post_current(user: User, payload: LocationUpdate) -> dict:
    """Ingest one fix: validate → dedupe → pipeline-write all views.

    Round trips: (1) event dedup SET NX + HGETALL of the previous fix
    (speed sanity), (2) the write pipeline — current HASH + TTL, live
    index ZADD, history ZSET append (score=captured ms), daily GEOADD,
    partition TTLs, session marker refresh. No Postgres — the employee
    scope is already on the authed user.

    Delayed/offline points keep their captured_at ordering inside the
    ZSET; a delayed fix NEVER overwrites a newer live position.
    """
    employee_id = _require_employee(user)
    _validate(payload)

    client = await redis_core.get_redis()
    if client is None:
        raise LiveLocationUnavailable()

    # Per-employee fixed-window limit — tolerates 15–30 s tracking plus
    # reconnect bursts, rejects floods.
    if not await check_rate_limit(
        "location", str(employee_id),
        settings.LOCATION_RATE_LIMIT_PER_MINUTE, 60,
    ):
        raise RateLimited(code="LOCATION_RATE_LIMITED")

    # Session check when the tracker supplies one — Redis marker only.
    if payload.tracking_session_id is not None:
        await tracking.validate_session(
            client, employee_id, payload.tracking_session_id
        )

    server_ts = time.time()
    captured_ts = tracking.resolve_capture(payload)
    # Future-timestamp rejection happens here; old captures return a flag.
    tracking.validate_capture_window(captured_ts, server_ts)

    dedup_key = None
    if (
        payload.tracking_session_id is not None
        and payload.sequence_number is not None
    ):
        dedup_key = tracking.event_key(
            employee_id,
            payload.tracking_session_id,
            payload.sequence_number,
        )

    key = location_key(employee_id)
    try:
        # Round trip 1 — dedup claim + previous fix (speed sanity).
        pipe = client.pipeline(transaction=False)
        if dedup_key:
            pipe.set(
                dedup_key, "1", nx=True,
                ex=settings.LOCATION_EVENT_DEDUP_TTL_SECONDS,
            )
        pipe.hgetall(key)
        results = await pipe.execute()
        prev = results[-1]
        if dedup_key and not results[0]:
            # Retried delivery of an already-ingested event — idempotent ack.
            logger.debug(
                "duplicate location event employee=%s seq=%s",
                employee_id, payload.sequence_number,
            )
            return _ack(captured_ts, server_ts, duplicate=True)
    except Exception as exc:
        logger.warning(
            "live location pre-write failed for employee %s: %s",
            employee_id, type(exc).__name__,
        )
        raise LiveLocationUnavailable() from exc

    quality = tracking.quality_flag(payload, captured_ts, server_ts, prev)
    speed = (
        payload.speed_mps
        if payload.speed_mps is not None
        else payload.speed
    )
    bearing = (
        payload.bearing_deg
        if payload.bearing_deg is not None
        else payload.heading
    )
    captured_iso = (
        datetime.fromtimestamp(captured_ts, tz=timezone.utc).isoformat()
    )
    received_iso = (
        datetime.fromtimestamp(server_ts, tz=timezone.utc).isoformat()
    )
    fields = {
        "latitude": _num(payload.latitude),
        "longitude": _num(payload.longitude),
        "accuracy": _num(payload.accuracy),
        "device_timestamp": _num(captured_ts),
        "server_timestamp": _num(server_ts),
        "captured_at": captured_iso,
        "received_at": received_iso,
        "quality": quality,
    }
    if speed is not None:
        fields["speed"] = _num(speed)
    if bearing is not None:
        fields["heading"] = _num(bearing)
    if payload.altitude_m is not None:
        fields["altitude"] = _num(payload.altitude_m)
    if payload.tracking_session_id is not None:
        fields["tracking_session_id"] = str(payload.tracking_session_id)
    if payload.sequence_number is not None:
        fields["sequence_number"] = _num(payload.sequence_number)
    if payload.source:
        fields["source"] = payload.source

    day = datetime.fromtimestamp(captured_ts, tz=timezone.utc)
    hist_key = tracking.history_key(employee_id, day)
    gkey = tracking.geo_key(day)
    member = tracking.history_member(
        employee_id, payload, captured_ts, server_ts, quality
    )
    geo_member = (
        f"{employee_id}:{payload.tracking_session_id or 'legacy'}:"
        f"{payload.sequence_number or int(server_ts * 1000)}"
    )
    history_ttl = (
        settings.LOCATION_HISTORY_RETENTION_DAYS + 1
    ) * 86_400
    # A delayed fix must not downgrade the live position — only touch
    # the live hash/index when this fix is not older than the current one.
    prev_captured = None
    if prev:
        try:
            prev_captured = float(prev.get("device_timestamp") or 0)
        except (TypeError, ValueError):
            prev_captured = None

    try:
        pipe = client.pipeline(transaction=False)
        if prev_captured is None or captured_ts >= prev_captured:
            pipe.delete(key)
            pipe.hset(key, mapping=fields)
            pipe.expire(key, settings.LOCATION_CURRENT_TTL_SECONDS)
            pipe.zadd(
                LIVE_INDEX_KEY,
                {str(employee_id): server_ts
                 + settings.LOCATION_CURRENT_TTL_SECONDS},
            )
        pipe.zadd(hist_key, {member: int(captured_ts * 1000)})
        pipe.expire(hist_key, history_ttl)
        pipe.geoadd(
            gkey, [payload.longitude, payload.latitude, geo_member]
        )
        pipe.expire(gkey, history_ttl)
        if payload.tracking_session_id is not None:
            pipe.expire(
                tracking.session_key(payload.tracking_session_id),
                settings.LOCATION_SESSION_TTL_SECONDS,
            )
        await pipe.execute()
    except Exception as exc:
        # Redis client present but the write failed — no fallback store.
        logger.warning(
            "live location write failed for employee %s: %s",
            employee_id, type(exc).__name__,
        )
        raise LiveLocationUnavailable() from exc

    logger.debug(
        "live location updated for employee %s (quality=%s)",
        employee_id, quality,
    )
    return _ack(captured_ts, server_ts, quality=quality)


def _ack(
    captured_ts: float,
    server_ts: float,
    *,
    duplicate: bool = False,
    quality: str = "valid",
) -> dict:
    return {
        "accepted": True,
        "recorded": True,  # legacy contract for the installed app
        "received_at": datetime.fromtimestamp(
            server_ts, tz=timezone.utc
        ).isoformat(),
        "location_timestamp": datetime.fromtimestamp(
            captured_ts, tz=timezone.utc
        ).isoformat(),
        "server_timestamp": server_ts,  # legacy
        "expires_in": settings.LOCATION_CURRENT_TTL_SECONDS,  # legacy
        "duplicate": duplicate,
        "quality": quality,
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
        "altitude_m": parsed["altitude"],
        "device_timestamp": parsed["device_timestamp"],
        "server_timestamp": server_ts,
        "captured_at": raw.get("captured_at"),
        "received_at": raw.get("received_at"),
        "tracking_session_id": raw.get("tracking_session_id"),
        "sequence_number": parsed["sequence_number"],
        "quality": raw.get("quality"),
        "age_seconds": age,
    }


def _live_entry(member_id: str, raw: dict, parsed: dict) -> dict:
    """One snapshot entry — canonical fields (accuracy_m, speed_mps,
    bearing_deg, captured_at, received_at, is_stale) plus the legacy
    names the original contract emitted (accuracy, speed, heading,
    device_timestamp, server_timestamp, is_live)."""
    return {
        "employee_id": str(member_id),
        "latitude": parsed["latitude"],
        "longitude": parsed["longitude"],
        "accuracy": parsed["accuracy"],
        "accuracy_m": parsed["accuracy"],
        "device_timestamp": parsed["device_timestamp"],
        "server_timestamp": parsed["server_timestamp"],
        "captured_at": raw.get("captured_at"),
        "received_at": raw.get("received_at"),
        "tracking_session_id": raw.get("tracking_session_id"),
        "sequence_number": parsed["sequence_number"],
        "speed": parsed["speed"],
        "speed_mps": parsed["speed"],
        "heading": parsed["heading"],
        "bearing_deg": parsed["heading"],
        "altitude_m": parsed["altitude"],
        "quality": raw.get("quality"),
        "source": raw.get("source"),
        "is_live": True,
        "is_stale": False,
    }


def _parsed_entry(member_id: str, raw: dict) -> dict | None:
    """Hash → entry, or None when the record is corrupt — a malformed
    member must never take down the whole snapshot."""
    try:
        parsed = _parse(raw)
    except Exception:
        logger.warning(
            "skipping malformed live-location record for member %s",
            member_id,
        )
        return None
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
        # Missing/non-numeric required field — skip rather than emit a
        # half-populated record to the SA backend.
        logger.warning(
            "skipping live-location record with malformed fields "
            "for member %s",
            member_id,
        )
        return None
    return _live_entry(member_id, raw, parsed)


async def get_all_live(
    employee_id: uuid.UUID | None = None,
    include_stale: bool = False,
    scoped_ids: set[str] | None = None,
) -> dict:
    """Server-to-server snapshot: every employee whose fix is still live.

    employee_id → read that one hash directly (no index scan); with
    include_stale an absent/expired key still yields an entry marked
    is_stale=true so the SA backend can distinguish 'missing' from
    'absent from the list'.
    scoped_ids → intersect the live index with a caller-resolved
    employee set (property/zone filters land here).

    The ZSET `mt:location` is the index — member=str(employee_id),
    score=expiry epoch. One pipeline: ZREMRANGEBYSCORE purges dead
    members, ZRANGEBYSCORE returns survivors; a second pipeline
    HGETALLs each hash in one round trip — no SCAN, no N+1.

    Response carries employee UUIDs and coordinates ONLY — no names or
    employee metadata. Redis down → LiveLocationUnavailable (503).
    Only the member count and latency are logged, never coordinates.
    """
    client = await redis_core.get_redis()
    if client is None:
        raise LiveLocationUnavailable()

    started = time.monotonic()
    now = time.time()
    try:
        if employee_id is not None:
            raw = await client.hgetall(location_key(employee_id))
            if raw:
                entry = _parsed_entry(str(employee_id), raw)
                return {"locations": [entry] if entry else []}
            if include_stale:
                return {
                    "locations": [
                        {
                            "employee_id": str(employee_id),
                            "latitude": None,
                            "longitude": None,
                            "accuracy_m": None,
                            "speed_mps": None,
                            "bearing_deg": None,
                            "altitude_m": None,
                            "captured_at": None,
                            "received_at": None,
                            "tracking_session_id": None,
                            "is_live": False,
                            "is_stale": True,
                        }
                    ]
                }
            return {"locations": []}

        pipe = client.pipeline(transaction=False)
        pipe.zremrangebyscore(LIVE_INDEX_KEY, "-inf", now)
        pipe.zrangebyscore(LIVE_INDEX_KEY, now, "+inf")
        _, member_ids = await pipe.execute()

        if scoped_ids is not None:
            member_ids = [m for m in member_ids if m in scoped_ids]

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

    locations = []
    for member_id, raw in zip(member_ids, hashes):
        if not raw:
            continue  # hash expired between ZRANGE and HGETALL
        entry = _parsed_entry(member_id, raw)
        if entry is not None:
            locations.append(entry)

    logger.debug(
        "live location snapshot: %d live of %d indexed in %.1fms",
        len(locations), len(member_ids),
        (time.monotonic() - started) * 1000,
    )
    return {"locations": locations}
