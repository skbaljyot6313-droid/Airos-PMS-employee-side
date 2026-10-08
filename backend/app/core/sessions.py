"""Server-side session registry in Redis.

JWT access tokens stay stateless, but carry a ``sid`` claim pointing at a
session hash created at login. Logout deletes the hash, so an in-flight
access token dies immediately instead of living out its full expiry —
the Postgres refresh-token row remains the durable revocation record.

Keys (project convention ``mt:{domain}:{scope}:{id}``):
    mt:session:{sid}              hash   {user_id, refresh_hash, created_at}
    mt:session:rt:{refresh_hash}  string -> sid     (refresh → session lookup)
    mt:session:user:{user_id}     set    {sid, …}   (revoke-all index)

Degradation (matches app.core.redis): Redis is an accelerator, never the
source of truth. Unconfigured/unreachable → ``create_session`` returns
None (the token simply carries no sid), ``alive`` fails open, revocations
are no-ops. A refresh token still valid in Postgres re-materializes its
session on refresh, so a Redis restart can never mass-logout users.
"""

import secrets
import time
import uuid

from app.core.config import settings
from app.core.logging import get_logger
from app.core.redis import get_redis

logger = get_logger("app.sessions")


def _session_ttl() -> int:
    return settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400


def _key(sid: str) -> str:
    return f"mt:session:{sid}"


def _rt_key(refresh_hash: str) -> str:
    return f"mt:session:rt:{refresh_hash}"


def _user_key(user_id: uuid.UUID) -> str:
    return f"mt:session:user:{user_id}"


async def create_session(
    *, user_id: uuid.UUID, refresh_hash: str
) -> str | None:
    """Write a session bound to a refresh token; returns the sid, or None
    when Redis is unavailable (caller issues a sid-less token)."""
    client = await get_redis()
    if client is None:
        return None
    sid = secrets.token_urlsafe(24)
    ttl = _session_ttl()
    try:
        pipe = client.pipeline(transaction=False)
        pipe.hset(
            _key(sid),
            mapping={
                "user_id": str(user_id),
                "refresh_hash": refresh_hash,
                "created_at": str(int(time.time())),
            },
        )
        pipe.expire(_key(sid), ttl)
        pipe.set(_rt_key(refresh_hash), sid, ex=ttl)
        pipe.sadd(_user_key(user_id), sid)
        pipe.expire(_user_key(user_id), ttl)
        await pipe.execute()
        return sid
    except Exception as exc:
        logger.warning(
            "session create failed — issuing token without sid: %s",
            type(exc).__name__,
        )
        return None


async def alive(sid: str) -> bool:
    """False only when Redis positively confirms the session is gone.

    Fails open: an unreachable/unconfigured Redis must not log out every
    active user (same contract as the rate limiter).
    """
    client = await get_redis()
    if client is None:
        return True
    try:
        return bool(await client.exists(_key(sid)))
    except Exception as exc:
        logger.warning(
            "session check failed (fail-open): %s", type(exc).__name__
        )
        return True


async def sid_by_refresh(refresh_hash: str) -> str | None:
    """sid bound to a refresh-token hash — None when absent OR Redis is
    unreachable (callers treat both as 're-materialize on refresh')."""
    client = await get_redis()
    if client is None:
        return None
    try:
        return await client.get(_rt_key(refresh_hash))
    except Exception:
        return None


async def touch(sid: str, refresh_hash: str) -> None:
    """Re-arm session + reverse-index TTLs on refresh so an active
    session never expires mid-use."""
    client = await get_redis()
    if client is None:
        return
    ttl = _session_ttl()
    try:
        pipe = client.pipeline(transaction=False)
        pipe.expire(_key(sid), ttl)
        pipe.expire(_rt_key(refresh_hash), ttl)
        await pipe.execute()
    except Exception as exc:
        logger.warning("session touch failed: %s", type(exc).__name__)


async def revoke_session(sid: str) -> None:
    """Delete one session — kills its access token on the next request."""
    client = await get_redis()
    if client is None:
        return
    try:
        raw = await client.hgetall(_key(sid))
        pipe = client.pipeline(transaction=False)
        pipe.delete(_key(sid))
        if raw.get("refresh_hash"):
            pipe.delete(_rt_key(raw["refresh_hash"]))
        if raw.get("user_id"):
            pipe.srem(_user_key(uuid.UUID(raw["user_id"])), sid)
        await pipe.execute()
    except Exception as exc:
        logger.warning("session revoke failed: %s", type(exc).__name__)


async def revoke_by_refresh(refresh_hash: str) -> None:
    """Logout path — resolves the session via the reverse index."""
    client = await get_redis()
    if client is None:
        return
    try:
        sid = await client.get(_rt_key(refresh_hash))
        if sid:
            await revoke_session(sid)
        else:
            await client.delete(_rt_key(refresh_hash))
    except Exception as exc:
        logger.warning(
            "session revoke-by-refresh failed: %s", type(exc).__name__
        )


async def revoke_all_for_user(user_id: uuid.UUID) -> int:
    """Kill every session for a user (logout-everywhere / password change).
    Returns the number of sessions revoked."""
    client = await get_redis()
    if client is None:
        return 0
    try:
        sids = await client.smembers(_user_key(user_id))
        for sid in sids:
            await revoke_session(sid)
        await client.delete(_user_key(user_id))
        return len(sids)
    except Exception as exc:
        logger.warning(
            "session revoke-all failed for user %s: %s",
            user_id, type(exc).__name__,
        )
        return 0
