"""Per-request stage timing — how much of each request went to Postgres,
Redis, and external services.

A mutable metrics dict lives in a contextvar for the duration of one HTTP
request (installed by AccessLogMiddleware). Instrumentation sites read it
via ``current()`` — None outside a request, so every call site is a no-op
for non-HTTP work (tests, scripts, startup). The dict is shared by
reference, so mutations made inside SQLAlchemy's greenlet listeners and
Redis wrappers are visible to the middleware that owns the dict.

Emitted as response headers (AccessLogMiddleware):
    X-DB-Exec-ms    wall time inside session.execute() — query + pool
                    acquisition + result fetch (acquisition dominates the
                    first call only when the pool is contended)
    X-DB-Query-ms   pure server-side cursor execution (engine listeners)
    X-DB-Count      statements executed
    X-Redis-ms      wall time across all Redis commands/pipelines
    X-Redis-Ops     Redis round trips (a pipeline counts as one)
    X-Ext-ms        external HTTP (push providers, etc.)
    X-PoolWait-ms   first-execute entry → first cursor execute gap —
                    pool-checkout wait + first-statement setup overhead

Headers are gated by settings.perf_headers_enabled (on outside prod);
the same stage data is always kept in the access log line.
"""

import contextvars
import functools
import time
from typing import Any

from app.core.logging import get_logger

logger = get_logger("app.metrics")

_request_metrics: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "airos_request_metrics", default=None
)

_FIELDS = (
    "db_exec_ms",
    "db_query_ms",
    "db_count",
    "redis_ms",
    "redis_ops",
    "ext_ms",
    "pool_wait_ms",
    "db_pool_exhaustions",
)


def begin() -> contextvars.Token:
    """Install a fresh metrics dict for this request; returns the token
    the caller must pass to ``end``."""
    return _request_metrics.set({f: 0.0 for f in _FIELDS})


def current() -> dict | None:
    return _request_metrics.get()


def end(token: contextvars.Token) -> None:
    _request_metrics.reset(token)


def record_db(ms: float, count: int = 1) -> None:
    m = _request_metrics.get()
    if m is not None:
        m["db_exec_ms"] += ms
        m["db_count"] += count


def mark_first_exec_start() -> None:
    """Stamp the wall-clock entry into the first execute() of a request —
    the gap to the first before_cursor_execute is pool-acquisition +
    first-statement overhead, surfaced as X-PoolWait-ms."""
    m = _request_metrics.get()
    if m is not None and "_exec_t0" not in m:
        m["_exec_t0"] = time.perf_counter()


def record_db_query(ms: float) -> None:
    m = _request_metrics.get()
    if m is not None:
        m["db_query_ms"] += ms


def record_pool_wait() -> None:
    """Called at first cursor execution — turns the stamped execute-entry
    gap into the pool-wait bucket (fires once per request)."""
    m = _request_metrics.get()
    if m is not None and "_exec_t0" in m:
        m["pool_wait_ms"] += (time.perf_counter() - m.pop("_exec_t0")) * 1000


def record_redis(ms: float, ops: int = 1) -> None:
    m = _request_metrics.get()
    if m is not None:
        m["redis_ms"] += ms
        m["redis_ops"] += ops


def record_ext(ms: float) -> None:
    m = _request_metrics.get()
    if m is not None:
        m["ext_ms"] += ms


def _timed(awaitable_fn, on_error=None, on_ok=None):
    """Wrap an awaitable-producing callable; times the awaited call into
    the Redis bucket. No-op pass-through outside a request context.
    Optional lifecycle hooks report op outcome to the owner's health
    tracking — they must never raise."""

    @functools.wraps(awaitable_fn)
    async def wrapper(*args, **kwargs):
        m = _request_metrics.get()
        if m is None:
            try:
                result = await awaitable_fn(*args, **kwargs)
            except Exception:
                if on_error is not None:
                    try:
                        on_error()
                    except Exception:
                        pass
                raise
            if on_ok is not None:
                try:
                    on_ok()
                except Exception:
                    pass
            return result
        t0 = time.perf_counter()
        try:
            result = await awaitable_fn(*args, **kwargs)
        except Exception:
            if on_error is not None:
                try:
                    on_error()
                except Exception:
                    pass
            raise
        else:
            if on_ok is not None:
                try:
                    on_ok()
                except Exception:
                    pass
            return result
        finally:
            m["redis_ms"] += (time.perf_counter() - t0) * 1000
            m["redis_ops"] += 1

    return wrapper


class _TimedPipeline:
    """Proxy for a Redis pipeline — sync chain methods pass straight
    through; execute()/aexecute() are timed as ONE round trip."""

    __slots__ = ("_pipe", "_on_error", "_on_ok")

    def __init__(self, pipe, on_error=None, on_ok=None):
        self._pipe = pipe
        self._on_error = on_error
        self._on_ok = on_ok

    def __getattr__(self, name):
        attr = getattr(self._pipe, name)
        if name in ("execute", "aexecute") and callable(attr):
            return _timed(attr, self._on_error, self._on_ok)
        return attr

    async def __aenter__(self):
        await self._pipe.__aenter__()
        return self

    async def __aexit__(self, *exc):
        return await self._pipe.__aexit__(*exc)


class TimedRedis:
    """Transparent async-command timer around a redis.asyncio client.

    Every awaited command lands in the request's X-Redis bucket when a
    metrics context exists — zero call-site changes, and pipelines are
    counted once. Non-callable attributes pass through untouched. Op
    outcomes are reported through optional on_error/on_ok hooks so the
    owner re-probes health only when it actually changed."""

    __slots__ = ("_client", "_on_error", "_on_ok")

    def __init__(self, client, on_error=None, on_ok=None):
        self._client = client
        self._on_error = on_error
        self._on_ok = on_ok

    def pipeline(self, *args, **kwargs):
        return _TimedPipeline(
            self._client.pipeline(*args, **kwargs),
            self._on_error, self._on_ok,
        )

    def __getattr__(self, name) -> Any:
        attr = getattr(self._client, name)
        if not callable(attr):
            return attr
        return _timed(attr, self._on_error, self._on_ok)
