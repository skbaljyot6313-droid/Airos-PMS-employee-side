"""Location tracking — sessions, idempotent ingest, history.

Owns the location Redis schema beyond the live hash (live hash/index
stay in services/location_live.py — this module is imported BY it):

    mt:location:emp:{employee_id}                    HASH   live fix (TTL)
    mt:location                                    ZSET   live index (score=expiry epoch)
    mt:location:history:{employee_id}:{YYYY-MM-DD} ZSET   day partition (score=captured ms, member=compact JSON)
    mt:location:geo:{YYYY-MM-DD}                   GEO    spatial index (member=event id)
    mt:location:session:{session_uuid}             STRING JSON {e, s, started} (TTL)
    mt:location:event:{employee_id}:{sid}:{seq}    STRING dedup marker (TTL)

Hot path (POST /location/current) is DB-free: sessions are validated
against the Redis session key written by /location/start; raw points
never touch Postgres. Session rows in location_tracking_sessions are
lifecycle metadata only (start/stop/status/count).

Quality flags preserve every fix — GPS noise is data: 'delayed'
(capture older than the acceptance window), 'low_accuracy', and
'suspicious_speed' (implied speed vs the previous fix > the configured
max) mark the point instead of dropping it.

No KEYS/SCAN anywhere: history reads enumerate date partitions derived
from the requested range; live reads go through the index ZSET.
"""

import json
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import redis as redis_core
from app.core.config import settings
from app.core.exceptions import AppError, LiveLocationUnavailable
from app.core.logging import get_logger
from app.models.location_session import (
    SESSION_STATUS_ACTIVE,
    SESSION_STATUS_STOPPED,
    LocationTrackingSession,
)
from app.models.user import User
from app.schemas.location import LocationUpdate

logger = get_logger("app.location_tracking")

QUALITY_VALID = "valid"
QUALITY_LOW_ACCURACY = "low_accuracy"
QUALITY_SUSPICIOUS_SPEED = "suspicious_speed"
QUALITY_DELAYED = "delayed"

TRACKING_INTERVAL_SECONDS = 30

_DAY = timedelta(days=1)


# ---------------------------------------------------------------------------
# Errors — consistent contract, no raw exceptions leak
# ---------------------------------------------------------------------------


class InvalidTrackingSession(AppError):
    status_code = 400
    code = "INVALID_TRACKING_SESSION"
    message = (
        "Invalid or expired tracking session. Start a new tracking session."
    )


class TrackingSessionNotFound(AppError):
    status_code = 404
    code = "TRACKING_SESSION_NOT_FOUND"
    message = "Tracking session not found."


class InvalidHistoryQuery(AppError):
    status_code = 400
    code = "INVALID_HISTORY_RANGE"
    message = "Invalid history range."


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------


def history_key(employee_id: uuid.UUID, day: datetime) -> str:
    return f"mt:location:history:{employee_id}:{day:%Y-%m-%d}"


def geo_key(day: datetime) -> str:
    return f"mt:location:geo:{day:%Y-%m-%d}"


def session_key(session_id: uuid.UUID) -> str:
    return f"mt:location:session:{session_id}"


def event_key(
    employee_id: uuid.UUID, session_id: uuid.UUID, seq: int
) -> str:
    return f"mt:location:event:{employee_id}:{session_id}:{seq}"


def _utc(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _day_bounds(from_dt: datetime, to_dt: datetime):
    d = from_dt.date()
    end = to_dt.date()
    while d <= end:
        yield datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        d += _DAY


# ---------------------------------------------------------------------------
# Sessions — Postgres lifecycle row + Redis hot-path marker
# ---------------------------------------------------------------------------


async def _redis_required():
    client = await redis_core.get_redis()
    if client is None:
        raise LiveLocationUnavailable()
    return client


async def start_session(
    user: User, employee_id: uuid.UUID, session: AsyncSession
) -> LocationTrackingSession:
    """Create the session row + the Redis marker the ingest path checks.

    A Redis restart loses only the marker — the employee just calls
    /start again; the Postgres row remains the audit record.
    """
    row = LocationTrackingSession(employee_id=employee_id)
    session.add(row)
    await session.commit()
    await session.refresh(row)

    client = await _redis_required()
    try:
        await client.set(
            session_key(row.id),
            json.dumps(
                {
                    "e": str(employee_id),
                    "s": SESSION_STATUS_ACTIVE,
                    "started": row.started_at.timestamp(),
                }
            ),
            ex=settings.LOCATION_SESSION_TTL_SECONDS,
        )
    except Exception as exc:
        logger.warning(
            "session marker write failed for %s: %s",
            row.id, type(exc).__name__,
        )
        raise LiveLocationUnavailable() from exc
    logger.info(
        "tracking session started employee=%s session=%s",
        employee_id, row.id,
    )
    return row


async def validate_session(
    client, employee_id: uuid.UUID, session_id: uuid.UUID
) -> None:
    """Hot-path check — Redis session marker only, no Postgres.

    Missing marker → INVALID_TRACKING_SESSION (the tracker re-calls
    /start and keeps going). A stopped marker is rejected the same way —
    a stopped session must not accept new points (§57).
    """
    try:
        raw = await client.get(session_key(session_id))
    except Exception as exc:
        raise LiveLocationUnavailable() from exc
    if not raw:
        raise InvalidTrackingSession()
    try:
        marker = json.loads(raw)
    except ValueError:
        raise InvalidTrackingSession()
    if (
        marker.get("s") != SESSION_STATUS_ACTIVE
        or marker.get("e") != str(employee_id)
    ):
        raise InvalidTrackingSession()


async def stop_session(
    user: User,
    employee_id: uuid.UUID,
    session_id: uuid.UUID,
    session: AsyncSession,
) -> datetime:
    """Mark the session stopped — historical points are never deleted."""
    row = await session.get(LocationTrackingSession, session_id)
    if row is None or row.employee_id != employee_id:
        raise TrackingSessionNotFound()
    stopped_at = datetime.now(timezone.utc)
    if row.status == SESSION_STATUS_ACTIVE:
        row.status = SESSION_STATUS_STOPPED
        row.ended_at = stopped_at
        await session.commit()
    else:
        # Idempotent stop — report the recorded end if there is one.
        stopped_at = row.ended_at or stopped_at

    client = await _redis_required()
    try:
        await client.delete(session_key(session_id))
    except Exception as exc:
        raise LiveLocationUnavailable() from exc
    logger.info(
        "tracking session stopped employee=%s session=%s",
        employee_id, session_id,
    )
    return stopped_at


# ---------------------------------------------------------------------------
# Ingest helpers — used by location_live.post_current
# ---------------------------------------------------------------------------


def resolve_capture(payload: LocationUpdate) -> float:
    """Device capture time → epoch seconds (UTC).

    captured_at wins over the legacy epoch `timestamp`. Naive datetimes
    are assumed UTC (the contract documents UTC-only input).
    """
    if payload.captured_at is not None:
        dt = payload.captured_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    return float(payload.timestamp)


def validate_capture_window(captured: float, now: float) -> str | None:
    """Return a quality flag for out-of-window captures — never drop.

    Future timestamps beyond the skew budget are REJECTED (a client
    clock can't meaningfully describe the future); old captures inside
    the acceptance window are accepted and flagged 'delayed'.
    """
    if captured - now > settings.LOCATION_MAX_FUTURE_SKEW_SECONDS:
        raise InvalidHistoryQuery(
            "captured_at is too far in the future.",
            code="INVALID_TIMESTAMP",
        )
    if now - captured > settings.LOCATION_MAX_EVENT_AGE_SECONDS:
        return QUALITY_DELAYED
    return None


def implied_speed_flag(
    prev: dict | None, lat: float, lng: float, captured: float
) -> str | None:
    """suspicious_speed when the previous fix implies an impossible jump.

    Reads the CURRENT live hash (the previous point) — the fix is kept
    either way; the flag marks it for downstream analysis.
    """
    if not prev:
        return None
    try:
        plat = float(prev["latitude"])
        plng = float(prev["longitude"])
        pts = float(prev.get("device_timestamp") or 0)
    except (KeyError, TypeError, ValueError):
        return None
    dt = captured - pts
    if dt <= 0:
        return None
    from app.services.location import haversine_m

    dist = haversine_m(plat, plng, lat, lng)
    if dist / dt > settings.LOCATION_MAX_SPEED_MPS:
        return QUALITY_SUSPICIOUS_SPEED
    return None


def quality_flag(
    payload: LocationUpdate,
    captured: float,
    now: float,
    prev: dict | None,
) -> str:
    """Single quality flag — precedence: delayed > low_accuracy >
    suspicious_speed (a stale fix's derived speed is meaningless)."""
    if now - captured > settings.LOCATION_MAX_EVENT_AGE_SECONDS:
        return QUALITY_DELAYED
    if payload.accuracy > settings.LOCATION_LOW_ACCURACY_M:
        return QUALITY_LOW_ACCURACY
    speed_flag = implied_speed_flag(
        prev, payload.latitude, payload.longitude, captured
    )
    if speed_flag:
        return speed_flag
    return QUALITY_VALID


def history_member(
    employee_id: uuid.UUID,
    payload: LocationUpdate,
    captured: float,
    received: float,
    quality: str,
) -> str:
    """Compact per-point record — everything future dwell/route
    analysis needs (time, accuracy, speed, bearing, session, sequence)."""
    rec = {
        "lat": payload.latitude,
        "lng": payload.longitude,
        "acc": payload.accuracy,
        "cap": captured,
        "rx": received,
        "q": quality,
    }
    speed = payload.speed_mps if payload.speed_mps is not None else payload.speed
    bearing = (
        payload.bearing_deg
        if payload.bearing_deg is not None
        else payload.heading
    )
    if speed is not None:
        rec["spd"] = speed
    if bearing is not None:
        rec["brg"] = bearing
    if payload.altitude_m is not None:
        rec["alt"] = payload.altitude_m
    if payload.tracking_session_id is not None:
        rec["sid"] = str(payload.tracking_session_id)
    if payload.sequence_number is not None:
        rec["seq"] = payload.sequence_number
    if payload.source:
        rec["src"] = payload.source
    return json.dumps(rec, separators=(",", ":"))


# ---------------------------------------------------------------------------
# History read — Super Admin contract
# ---------------------------------------------------------------------------


async def get_history(
    employee_id: uuid.UUID,
    from_dt: datetime,
    to_dt: datetime,
    session_id: uuid.UUID | None = None,
    max_points: int | None = None,
) -> dict:
    """Time-ranged route history — day-partitioned ZRANGEBYSCORE.

    One pipelined round trip covers every date partition in range; a
    range longer than LOCATION_MAX_HISTORY_RANGE_DAYS is rejected, and
    oversized result sets are stride-downsampled (evenly spaced points —
    a route map needs coverage, not truncation).
    """
    if from_dt.tzinfo is None:
        from_dt = from_dt.replace(tzinfo=timezone.utc)
    if to_dt.tzinfo is None:
        to_dt = to_dt.replace(tzinfo=timezone.utc)
    if to_dt <= from_dt:
        raise InvalidHistoryQuery("`to` must be after `from`.")
    if (to_dt - from_dt).days > settings.LOCATION_MAX_HISTORY_RANGE_DAYS:
        raise InvalidHistoryQuery(
            f"Range exceeds {settings.LOCATION_MAX_HISTORY_RANGE_DAYS} days."
        )

    client = await _redis_required()
    keys = [history_key(employee_id, d) for d in _day_bounds(from_dt, to_dt)]
    lo = int(from_dt.timestamp() * 1000)
    hi = int(to_dt.timestamp() * 1000)
    try:
        pipe = client.pipeline(transaction=False)
        for key in keys:
            pipe.zrangebyscore(key, lo, hi)
        partitions = await pipe.execute()
    except Exception as exc:
        logger.warning(
            "history read failed for %s: %s",
            employee_id, type(exc).__name__,
        )
        raise LiveLocationUnavailable() from exc

    sid = str(session_id) if session_id else None
    points = []
    for members in partitions:
        for member in members:
            try:
                rec = json.loads(member)
            except (TypeError, ValueError):
                logger.warning(
                    "skipping malformed history point for %s", employee_id
                )
                continue
            if sid and rec.get("sid") != sid:
                continue
            points.append(rec)

    points.sort(key=lambda r: r.get("cap", 0))
    total = len(points)
    limit = max_points or settings.LOCATION_MAX_HISTORY_POINTS
    downsampled = False
    if total > limit:
        step = total / limit
        points = [points[int(i * step)] for i in range(limit)]
        downsampled = True

    return {
        "employee_id": str(employee_id),
        "from": from_dt.isoformat(),
        "to": to_dt.isoformat(),
        "total_points": total,
        "returned_points": len(points),
        "downsampled": downsampled,
        "points": [
            {
                "latitude": r.get("lat"),
                "longitude": r.get("lng"),
                "accuracy_m": r.get("acc"),
                "speed_mps": r.get("spd"),
                "bearing_deg": r.get("brg"),
                "altitude_m": r.get("alt"),
                "captured_at": _utc(r["cap"]).isoformat()
                if r.get("cap") is not None
                else None,
                "received_at": _utc(r["rx"]).isoformat()
                if r.get("rx") is not None
                else None,
                "tracking_session_id": r.get("sid"),
                "sequence_number": r.get("seq"),
                "quality": r.get("q", QUALITY_VALID),
            }
            for r in points
        ],
    }
