"""
SQLAlchemy async database infrastructure.

AsyncEngine → async_sessionmaker → AsyncSession, injected into routes via
the `get_db` dependency (see app/dependencies/db.py).
"""

import asyncio
import socket
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


def _pgbouncer_connect_args() -> dict:
    """pgbouncer transaction/statement poolers do not support asyncpg's
    prepared-statement cache. Disable the cache when the URL points at a
    Supabase pooler host so migrations and queries work reliably."""
    try:
        parsed = make_url(settings.database_url)
        if parsed.host and "pooler" in parsed.host:
            return {"statement_cache_size": 0}
    except Exception:
        pass
    return {}


engine: AsyncEngine = create_async_engine(
    settings.database_url,
    connect_args=_pgbouncer_connect_args(),
    # pool_recycle handles stale connections at checkout — avoids paying an
    # extra DB round trip (~300ms to remote Supabase) on EVERY request.
    pool_pre_ping=False,
    pool_recycle=settings.DB_POOL_RECYCLE,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    echo=settings.SQL_ECHO,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


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
