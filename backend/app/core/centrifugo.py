"""Centrifugo integration — connection/subscription tokens + HTTP publish.

Shares the SA backend's channel grammar and secrets (one Centrifugo
deployment serves both apps):

    priv:prop:{property_uid}:locations    employee.location_updated
    priv:prop:{property_uid}:attendance   attendance.* events
    priv:prop:{property_uid}:tasks        task.* events
    priv:prop:{property_uid}:maintenance  maintenance.* events
    priv:prop:{property_uid}:units        resource.state_changed
    priv:emp:{employee_uid}               per-employee channel — the ONLY
                                          channel this API mints tokens
                                          for (self-scoped)

Publishing is best-effort fire-and-forget (publish_bg): business
mutations never wait on — or fail because of — Centrifugo. The SA
frontend's reconciliation polls are the correctness backstop.
"""

import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import jwt

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("app.centrifugo")

PRIVATE_NS = "priv"
PROP_TOPICS = ("tasks", "units", "attendance", "maintenance",
               "locations", "employees")


def prop_channel(property_id: uuid.UUID, topic: str) -> str:
    return f"{PRIVATE_NS}:prop:{property_id}:{topic}"


def emp_channel(employee_id: uuid.UUID) -> str:
    return f"{PRIVATE_NS}:emp:{employee_id}"


def configured() -> bool:
    return bool(
        settings.CENTRIFUGO_URL
        and settings.CENTRIFUGO_API_KEY
        and settings.CENTRIFUGO_TOKEN_SECRET
    )


def ws_url() -> str | None:
    if settings.CENTRIFUGO_WS_URL:
        return settings.CENTRIFUGO_WS_URL
    if settings.CENTRIFUGO_URL:
        return settings.CENTRIFUGO_URL.rstrip("/") + "/connection/websocket"
    return None


# ---------------------------------------------------------------------------
# Tokens — HMAC-SHA256 JWTs in Centrifugo's expected format.
# ---------------------------------------------------------------------------

def _sign(claims: dict) -> str:
    return jwt.encode(
        claims, settings.CENTRIFUGO_TOKEN_SECRET, algorithm="HS256"
    )


def connection_token(user) -> tuple[str, int]:
    now = int(time.time())
    exp = now + settings.CENTRIFUGO_CONN_TOKEN_TTL_SECONDS
    token = _sign({
        "sub": str(user.id),
        "iat": now,
        "exp": exp,
        "info": {
            "role": str(getattr(user.role, "value", user.role)),
            "company_id": str(user.company_id),
            "property_id": str(user.property_id) if user.property_id else None,
        },
    })
    return token, exp


def subscription_token(user, channel: str) -> tuple[str, int]:
    now = int(time.time())
    exp = now + settings.CENTRIFUGO_SUB_TOKEN_TTL_SECONDS
    token = _sign({
        "sub": str(user.id),
        "channel": channel,
        "iat": now,
        "exp": exp,
    })
    return token, exp


# ---------------------------------------------------------------------------
# HTTP publish — POST {CENTRIFUGO_URL}/api/publish. A fresh short-lived
# client per publish is deliberately avoided; a shared module client is
# created lazily. Failures are logged, never raised.
# ---------------------------------------------------------------------------

_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=4.0)
    return _client


async def publish(channel: str, event_type: str, data: dict[str, Any]) -> bool:
    if not configured():
        return False
    envelope = {
        "v": 1,
        "id": uuid.uuid4().hex,
        "type": event_type,
        "ts": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
    try:
        res = await _http().post(
            f"{settings.CENTRIFUGO_URL.rstrip('/')}/api/publish",
            headers={"X-API-Key": settings.CENTRIFUGO_API_KEY},
            json={"channel": channel, "data": envelope},
        )
        if res.status_code != 200:
            logger.warning(
                "centrifugo publish %s -> HTTP %s", channel, res.status_code
            )
            return False
        return True
    except httpx.HTTPError as exc:
        logger.warning(
            "centrifugo publish %s failed: %s", channel, type(exc).__name__
        )
        return False


def publish_bg(channel: str, event_type: str, data: dict[str, Any]) -> None:
    """Fire-and-forget publish — caller must only invoke this AFTER its
    business mutation has committed. Never blocks the request path and
    never raises."""
    if not configured():
        return
    try:
        asyncio.get_running_loop().create_task(
            publish(channel, event_type, dict(data))
        )
    except RuntimeError:
        pass  # no loop (sync context) — event simply skipped


# ---------------------------------------------------------------------------
# Post-commit dispatch — for services whose mutation commits in the
# CALLER (e.g. ResourceStateService inside an occupancy transaction):
# buffer on session.info; the after_commit hook in app.core.database
# publishes only after the real commit.
# ---------------------------------------------------------------------------

RT_EVENTS = "_centrifugo_events"


def queue_event(
    session, channel: str, event_type: str, data: dict[str, Any]
) -> None:
    if not configured():
        return
    session.info.setdefault(RT_EVENTS, []).append(
        (channel, event_type, dict(data))
    )


async def dispatch_realtime_events(events: list[tuple]) -> None:
    for channel, event_type, data in events[:50]:
        await publish(channel, event_type, data)


# ---------------------------------------------------------------------------
# Per-employee location-publish throttle — a device can ingest a fix every
# ~10 s; Centrifugo delivery is coalesced to LOCATION_PUBLISH_MIN_INTERVAL.
# Redis marker when available, in-process dict otherwise (per-worker —
# acceptable since this is a throttle, not a correctness gate).
# ---------------------------------------------------------------------------

_last_pub: dict[str, float] = {}


async def location_publish_allowed(employee_id: uuid.UUID) -> bool:
    """True at most once per employee per interval."""
    now = time.time()
    key = f"rt:locpub:{employee_id}"
    try:
        from app.core import redis as redis_core
        client = await redis_core.get_redis()
        if client is not None:
            ok = await client.set(
                key, "1", nx=True,
                ex=settings.LOCATION_PUBLISH_MIN_INTERVAL_SECONDS,
            )
            return bool(ok)
    except Exception:
        pass  # fall through to in-memory throttle
    last = _last_pub.get(key, 0.0)
    if now - last < settings.LOCATION_PUBLISH_MIN_INTERVAL_SECONDS:
        return False
    _last_pub[key] = now
    if len(_last_pub) > 10_000:  # bound the map
        cutoff = now - 3600
        for k in [k for k, v in _last_pub.items() if v < cutoff]:
            _last_pub.pop(k, None)
    return True
