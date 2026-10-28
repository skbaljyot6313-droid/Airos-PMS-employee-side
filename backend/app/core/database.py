"""
SQLAlchemy async database infrastructure.

AsyncEngine → async_sessionmaker → AsyncSession, injected into routes via
the `get_db` dependency (see app/dependencies/db.py).
"""

import asyncio
import socket
import time
import uuid
import ssl as ssl_module
from collections.abc import AsyncGenerator

from fastapi import status
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core import metrics
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger

logger = get_logger("app.database")


class DatabaseUnavailable(AppError):
    """Connectivity-level failure reaching PostgreSQL (DNS/refused/timeout).

    Distinct from SQLAlchemyError handling — asyncpg surfaces gaierror and
    friends as raw OSErrors that never become SQLAlchemyError subclasses."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "DATABASE_UNAVAILABLE"
    message = "The database is temporarily unavailable. Please try again."


def _is_pooler_host() -> bool:
    try:
        parsed = make_url(settings.database_url)
        return bool(parsed.host and "pooler" in parsed.host)
    except Exception:
        return False


def _pgbouncer_connect_args() -> dict:
    """pgbouncer transaction/statement poolers do not support asyncpg's
    prepared-statement cache. Disable the cache when the URL points at a
    Supabase pooler host so migrations and queries work reliably."""
    try:
        if _is_pooler_host():
            # Dialect-level args (not raw asyncpg kwargs): disable the
            # prepared-statement cache AND give every statement a unique
            # name — pooler transaction mode shares server connections, so
            # default "__asyncpg_stmt_N__" names collide across clients.
            return {
                "prepared_statement_cache_size": 0,
                "prepared_statement_name_func": (
                    lambda: f"__asyncpg_stmt_{uuid.uuid4().hex}__"
                ),
            }
    except Exception:
        pass
    return {}


def _connect_args() -> dict:
    """asyncpg-only connect args — skipped for sqlite (tests, tooling)
    and merged with the pgBouncer opts for Supabase pooler hosts."""
    args = _pgbouncer_connect_args()
    if settings.database_url.startswith("postgresql+asyncpg"):
        # command_timeout → PostgreSQL statement_timeout: a runaway
        # statement can no longer hold a pool connection indefinitely.
        # timeout → asyncpg connect() timeout (TLS + pooler handshake).
        args = {"command_timeout": 30, "timeout": 15, **args}
    return args


engine: AsyncEngine = create_async_engine(
    settings.database_url,
    connect_args=_connect_args(),
    # pool_recycle handles stale connections at checkout — avoids paying an
    # extra DB round trip (~300ms to remote Supabase) on EVERY request.
    pool_pre_ping=settings.DB_POOL_PRE_PING,
    pool_recycle=settings.DB_POOL_RECYCLE,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    echo=settings.SQL_ECHO,
)

class TimedAsyncSession(AsyncSession):
    """Times wall-clock duration of every execute() into the request
    metrics context — covers session.get/scalar/scalars (they all route
    through execute). No-op outside HTTP request handling."""

    async def execute(self, *args, **kwargs):
        if metrics.current() is None:
            return await super().execute(*args, **kwargs)
        metrics.mark_first_exec_start()
        t0 = time.perf_counter()
        try:
            return await super().execute(*args, **kwargs)
        finally:
            metrics.record_db((time.perf_counter() - t0) * 1000)


AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=TimedAsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


from sqlalchemy import event as _sa_engine_event  # noqa: E402


@_sa_engine_event.listens_for(engine.sync_engine, "before_cursor_execute")
def _metrics_before_cursor(conn, cursor, statement, parameters, context, executemany):
    metrics.record_pool_wait()  # first execute→cursor gap only
    conn.info["_airos_stmt_t0"] = time.perf_counter()


@_sa_engine_event.listens_for(engine.sync_engine, "after_cursor_execute")
def _metrics_after_cursor(conn, cursor, statement, parameters, context, executemany):
    t0 = conn.info.pop("_airos_stmt_t0", None)
    if t0 is not None:
        metrics.record_db_query((time.perf_counter() - t0) * 1000)


# OPT-IN PostgreSQL idle_in_transaction_session_timeout — applied as a
# per-connection SET at engine connect (safe under transaction poolers
# in that it is not a startup server_settings parameter baked into the
# connection spec, but session state can still carry between checkouts
# on a shared server connection — therefore OFF by default AND skipped
# entirely on pooler hosts until verified on staging).
if settings.DB_IDLE_TX_TIMEOUT_MS > 0:
    if _is_pooler_host():
        logger.warning(
            "DB_IDLE_TX_TIMEOUT_MS is set but DATABASE_URL points at a "
            "pooler host — skipping; session-level SET can leak across "
            "shared server connections. Verify on staging first."
        )
    elif settings.database_url.startswith("postgresql+asyncpg"):
        @_sa_engine_event.listens_for(engine.sync_engine, "connect")
        def _set_idle_tx_timeout(dbapi_conn, conn_record):
            cursor = dbapi_conn.cursor()
            try:
                cursor.execute(
                    "SET idle_in_transaction_session_timeout = "
                    f"{int(settings.DB_IDLE_TX_TIMEOUT_MS)}"
                )
            finally:
                cursor.close()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields an AsyncSession, always closed on exit."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as exc:
            await session.rollback()
            # asyncpg raises raw OSErrors (gaierror, refused, timeout) that
            # bypass the SQLAlchemyError handler — map them to a clean 503.
            if isinstance(_unwrap(exc), (socket.gaierror, ConnectionError, TimeoutError)):
                logger.error("Database unavailable: %s", describe_db_error(exc))
                raise DatabaseUnavailable() from exc
            raise


async def close_db() -> None:
    """Dispose the engine's connection pool (app shutdown)."""
    await engine.dispose()


# ---------------------------------------------------------------------------
# Post-commit Centrifugo dispatch — services buffer events on
# session.info[RT_EVENTS] via centrifugo.queue_event(); they publish ONLY
# after the outer transaction commits, so a rolled-back mutation never
# emits a success event and a publish failure can never fail the
# committed business transaction. Listeners attach to the sync Session
# class (async_sessionmaker isn't a valid event target).
# ---------------------------------------------------------------------------

from sqlalchemy import event as _sa_event  # noqa: E402
from sqlalchemy.orm import Session as _SyncSession  # noqa: E402


@_sa_event.listens_for(_SyncSession, "after_commit")
def _rt_events_after_commit(session) -> None:
    if session.in_nested_transaction():
        return
    from app.core.centrifugo import RT_EVENTS, dispatch_realtime_events
    from app.services.notifications import (
        PUSH_QUEUE,
        dispatch_queued_pushes,
    )
    events = session.info.pop(RT_EVENTS, None)
    pushes = session.info.pop(PUSH_QUEUE, None)
    if events:
        try:
            try:
                asyncio.get_running_loop().create_task(
                    dispatch_realtime_events(list(events))
                )
            except RuntimeError:
                from sqlalchemy.util.concurrency import await_only
                await_only(dispatch_realtime_events(list(events)))
        except Exception as exc:
            logger.warning(
                "realtime-event dispatch failed: %s", type(exc).__name__
            )
    if pushes:
        # Push sends run OUTSIDE the committed transaction on a fresh
        # session — external HTTPS must never hold a pool connection.
        try:
            try:
                asyncio.get_running_loop().create_task(
                    dispatch_queued_pushes(list(pushes))
                )
            except RuntimeError:
                from sqlalchemy.util.concurrency import await_only
                await_only(dispatch_queued_pushes(list(pushes)))
        except Exception as exc:
            logger.warning(
                "push dispatch scheduling failed: %s", type(exc).__name__
            )


@_sa_event.listens_for(_SyncSession, "after_rollback")
def _rt_events_after_rollback(session) -> None:
    if session.in_nested_transaction():
        return
    from app.core.centrifugo import RT_EVENTS
    from app.services.notifications import PUSH_QUEUE
    session.info.pop(RT_EVENTS, None)
    session.info.pop(PUSH_QUEUE, None)


async def check_database(timeout: float = 10.0) -> None:
    """Real connectivity probe — runs SELECT 1 through the engine/pool.

    Raises on failure; returns None on success. Bounded by `timeout` so a
    stalled remote (e.g. Supabase) can't hang health checks or startup.
    """
    async def _probe() -> None:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))

    await asyncio.wait_for(_probe(), timeout=timeout)


def _unwrap(exc: BaseException) -> BaseException:
    """Peel SQLAlchemy/OSError wrappers down to the root cause."""
    seen: set[int] = set()
    cur: BaseException = exc
    while True:
        nxt = getattr(cur, "orig", None) or getattr(cur, "__cause__", None)
        if nxt is None or id(nxt) in seen:
            return cur
        seen.add(id(cur))
        cur = nxt


def describe_db_error(exc: BaseException) -> str:
    """Categorized, credential-free description of a database failure.

    Used for startup/scheduler/health logging — identifies the failure class
    (DNS, auth, refused, timeout, TLS) and the sanitized host:port, without
    ever emitting the connection string or password.
    """
    host_port = settings.database_host_port
    root = _unwrap(exc)

    if isinstance(root, socket.gaierror):
        return f"unable to resolve PostgreSQL host '{host_port}' (DNS failure)"
    if isinstance(root, (TimeoutError, asyncio.TimeoutError)):
        return f"connection to PostgreSQL host '{host_port}' timed out"
    if isinstance(root, ConnectionRefusedError):
        return f"connection refused by PostgreSQL host '{host_port}'"
    if isinstance(root, ssl_module.SSLError):
        return f"TLS/SSL failure connecting to PostgreSQL host '{host_port}'"
    if isinstance(root, OSError):
        return f"network error reaching PostgreSQL host '{host_port}': {root.strerror or root}"

    name = type(root).__name__.lower()
    if "password" in name or "auth" in name:
        return f"authentication failed for PostgreSQL host '{host_port}' — check SUPABASE_DB_USER/SUPABASE_DB_PASSWORD"
    return f"{type(exc).__name__} connecting to PostgreSQL host '{host_port}'"
