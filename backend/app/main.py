"""Airco PMS employee backend application entrypoint."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import AsyncSessionLocal, check_database, close_db, describe_db_error
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.core.middleware import AccessLogMiddleware, RequestIDMiddleware, SecurityHeadersMiddleware
from app.core.redis import check_redis, close_redis, redis_configured

setup_logging()
logger = get_logger("app.main")

_ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


async def check_schema_version() -> str | None:
    """Compare the database's alembic_version with the script head.

    This backend shares one PostgreSQL database (and one alembic_version
    row) with the Super Admin backend. Booting against a revision the
    models don't match is the silent-killer failure: every query on a
    missing column surfaces as an unrelated 503. Returns None when
    current, else a human-readable remediation string."""
    from alembic.config import Config as AlembicConfig
    from alembic.script import ScriptDirectory
    from sqlalchemy import text

    if not _ALEMBIC_INI.exists():
        return None  # no migration config — nothing to compare
    try:
        cfg = AlembicConfig(str(_ALEMBIC_INI))
        heads = set(ScriptDirectory.from_config(cfg).get_heads())
        async with AsyncSessionLocal() as session:
            rows = await session.execute(
                text("SELECT version_num FROM alembic_version")
            )
            current = {r[0] for r in rows}
    except Exception as exc:
        # A DB with no alembic_version at all (e.g. local SQLite dev built
        # via create_all) has no revision to compare — treat as current.
        # Match on the RAW exception text; describe_db_error sanitizes it
        # into a network-flavored message that loses the table name.
        raw = str(exc).lower()
        if "alembic_version" in raw and (
            "no such table" in raw or "does not exist" in raw
        ):
            return None
        return (
            f"could not read schema version ({describe_db_error(exc)}) "
            "— run `alembic upgrade head`"
        )
    if current != heads:
        return (
            f"database schema is stale (at {sorted(current) or '[]'}, head is "
            f"{sorted(heads)}) — run `alembic upgrade head`"
        )
    return None


async def _push_sweep_loop() -> None:
    """Durable push outbox sweep — drains due queued/retry_pending
    notifications on a timer so a restart or transient FCM failure can
    never lose a pending send. Claiming is atomic (UPDATE … WHERE
    status), so multiple replicas may run this loop concurrently."""
    from app.services.notifications import dispatch_pending_pushes

    while True:
        await asyncio.sleep(settings.PUSH_SWEEP_INTERVAL_SECONDS)
        try:
            await dispatch_pending_pushes()
        except Exception as exc:  # pragma: no cover — loop must not die
            logger.warning("push sweep tick failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    for warning in settings.production_warnings():
        logger.warning("Production warning: %s", warning)
    logger.info(
        "Database pool per process: size=%d overflow=%d ceiling=%d timeout_s=%d recycle_s=%d pre_ping=%s",
        settings.DB_POOL_SIZE, settings.DB_MAX_OVERFLOW,
        settings.DB_POOL_SIZE + settings.DB_MAX_OVERFLOW,
        settings.DB_POOL_TIMEOUT, settings.DB_POOL_RECYCLE, settings.DB_POOL_PRE_PING,
    )
    # Push provider must initialize — production never silently degrades
    # to the log stub: PUSH_PROVIDER=fcm without working credentials is a
    # boot failure, not a hidden outage.
    from app.services.push import PushUnavailable, validate_push_config

    try:
        desc = validate_push_config()
        logger.info("Push provider ready: %s", desc)
    except PushUnavailable as exc:
        if settings.is_production:
            raise RuntimeError(
                f"Push provider misconfigured — refusing to boot: {exc}"
            ) from exc
        logger.error(
            "Push provider misconfigured (%s) — pushes are disabled "
            "until this is fixed", exc,
        )

    # Schema drift check — a reachable DB on an old (or different) shared
    # revision produces exactly the "endpoint 503s for no obvious reason"
    # failure mode. Refuse to serve rather than boot half-broken. The DB
    # and alembic_version row are shared with the Super Admin backend, so
    # this also catches the case where only one side migrated.
    stale = await check_schema_version()
    if stale:
        logger.error("FATAL: %s", stale)
        raise RuntimeError(f"Database schema out of date: {stale}")

    sweep_task = asyncio.create_task(_push_sweep_loop())
    try:
        yield
    finally:
        sweep_task.cancel()
        try:
            await sweep_task
        except asyncio.CancelledError:
            pass
        try:
            await close_redis()
        finally:
            await close_db()


app = FastAPI(
    title="Airco PMS Employee API",
    version="1.0.0",
    docs_url="/docs" if settings.APP_ENV != "production" else None,
    openapi_url="/openapi.json" if settings.APP_ENV != "production" else None,
    lifespan=lifespan,
)
# allow_origin_regex covers localhost/127.0.0.1 on ANY port — dev servers
# pick arbitrary ports (5173, 5199, …) and a fixed CORS_ORIGINS list makes
# "unable to connect" appear every time Vite bumps the port.
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?", allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(AccessLogMiddleware)
app.add_middleware(RequestIDMiddleware)
register_exception_handlers(app)

@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok", "service": "Airco PMS Employee API", "env": settings.APP_ENV}


@app.get("/health/db", tags=["health"])
async def health_db():
    try:
        await check_database()
        return {"status": "ok", "database": "connected"}
    except Exception as exc:
        logger.error("Database health check failed: %s", describe_db_error(exc))
        raise HTTPException(status_code=503, detail={"code": "DATABASE_UNAVAILABLE", "message": "Database is unreachable."})


@app.get("/ready", tags=["health"])
async def ready():
    result = {"status": "ok", "database": "connected", "redis": "disabled"}
    try:
        await check_database()
    except Exception:
        result.update(status="degraded", database="disconnected")
    if redis_configured():
        result["redis"] = "connected" if await check_redis() else "unreachable"
        if result["redis"] == "unreachable":
            result["status"] = "degraded"
    if result["database"] == "connected":
        stale = await check_schema_version()
        result["schema"] = "current" if stale is None else "stale"
        if stale is not None:
            result["status"] = "degraded"
            result["schema_detail"] = stale
    return JSONResponse(status_code=200 if result["status"] == "ok" else 503, content=result)


app.include_router(api_router, prefix=settings.API_V1_PREFIX)
