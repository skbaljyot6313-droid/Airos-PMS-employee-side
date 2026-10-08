"""
Rate limiting — Redis fixed-window counters with an in-memory fallback.

Redis backend (multi-instance safe):
    INCR mt:rl:<scope>:<key> → PEXPIRE on first hit. A fixed window is
    adequate for auth/upload protection; it can briefly allow 2x the limit
    at a window boundary, which is acceptable for brute-force defense.

In-memory fallback (no Redis): per-process token counters — correct for a
single replica and clearly better than nothing; documented limitation.

Failures: if Redis errors mid-request the limiter FAILS OPEN (request is
allowed and the error is logged) — a Redis blip must not take down login.
"""

import time
from collections import defaultdict

from fastapi import Request, status

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.core.redis import get_redis

logger = get_logger("app.rate_limit")


class RateLimited(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "RATE_LIMITED"
    message = "Too many requests. Please slow down and try again."


# --- in-memory fallback: {key: (count, window_start)} ---
_mem_counts: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))


def _mem_hit(key: str, limit: int, window_s: int) -> bool:
    """Returns True when the request is allowed."""
    now = time.monotonic()
    count, start = _mem_counts[key]
    if now - start >= window_s:
        _mem_counts[key] = (1, now)
        return True
    if count >= limit:
        return False
    _mem_counts[key] = (count + 1, start)
    return True


async def check_rate_limit(scope: str, ident: str, limit: int, window_s: int) -> bool:
    """True = allowed, False = limited. Fails open on Redis errors."""
    if not settings.RATE_LIMIT_ENABLED:
        return True
    key = f"mt:rl:{scope}:{ident}"
    redis = await get_redis()
    if redis is not None:
        try:
            count = await redis.incr(key)
            if count == 1:
                await redis.pexpire(key, window_s * 1000)
            return count <= limit
        except Exception as exc:
            logger.warning("Redis rate-limit check failed (fail-open): %s",
                           type(exc).__name__)
            return True
    return _mem_hit(key, limit, window_s)


def _client_ip(request: Request) -> str:
    # Trust X-Forwarded-For only from the known proxy hop — in compose/nginx
    # the proxy sets it; direct clients can't spoof past nginx.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(scope: str, limit: int, window_seconds: int = 60):
    """FastAPI dependency factory: `Depends(rate_limit('login', 10, 60))`."""

    async def _limiter(request: Request) -> None:
        allowed = await check_rate_limit(
            scope, _client_ip(request), limit, window_seconds
        )
        if not allowed:
            raise RateLimited()

    return _limiter
