"""
Redis infrastructure — cache, rate limiting, and the arq job queue all share
one connection-pooled client.

Design contract:
  * Redis is an ACCELERATOR, never a source of truth — PostgreSQL owns all
    persistent business data.
  * Every consumer must degrade gracefully when REDIS_URL is unset or the
    server is unreachable (in-memory rate limiting, no cache, embedded
    scheduler). `get_redis()` returns None instead of raising.
  * Key convention: `mt:{domain}:{scope}:{id}` — e.g. mt:rl:login:1.2.3.4,
    mt:cache:prop-meta:<uuid>. TTLs are always explicit.
"""

from redis.asyncio import Redis

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import TimedRedis

logger = get_logger("app.redis")

_client: Redis | None = None
_available: bool | None = None  # tri-state: None = not yet probed


def redis_configured() -> bool:
    return bool(settings.REDIS_URL)


async def get_redis() -> Redis | None:
    """Shared async client — None when unconfigured/unreachable.

    Bounded by connect/socket timeouts so a dead Redis can never hang a
    request path. The client is wrapped in TimedRedis so every command
    lands in the request's X-Redis timing bucket.

    The startup probe runs ONCE: the previous implementation PINGed on
    every get_redis() call — 2–3 extra Redis round trips per request for
    zero benefit, since every consumer already wraps its ops in
    try/except-and-degrade. Mid-run failures surface through the ops
    themselves; a later success implies recovery without a probe.
    """
    global _client, _available
    if not settings.REDIS_URL:
        return None
    if _client is None:
        _client = TimedRedis(
            Redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=settings.REDIS_CONNECT_TIMEOUT,
                socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
                retry_on_timeout=True,
            )
        )
    if _available is True or _available is False:
        # Verified once (or failed once) — ops still execute either way;
        # callers degrade on failure. No per-call health probe.
        return _client
    try:
        await _client.ping()
        logger.info("Redis connection verified")
        _available = True
    except Exception as exc:
        logger.warning("Redis unreachable (%s) — degrading to local fallbacks",
                       type(exc).__name__)
        _available = False
    return _client


async def check_redis(timeout: float = 5.0) -> bool:
    """Readiness probe — True only when Redis is configured AND reachable."""
    import asyncio

    if not settings.REDIS_URL:
        return False
    client = await get_redis()
    if client is None:
        return False
    try:
        await asyncio.wait_for(client.ping(), timeout=timeout)
        return True
    except Exception:
        return False


async def close_redis() -> None:
    global _client, _available
    if _client is not None:
        await _client.aclose()
        _client = None
    _available = None
