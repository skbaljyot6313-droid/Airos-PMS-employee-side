"""Airco PMS employee backend application entrypoint."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import check_database, close_db, describe_db_error
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.core.middleware import AccessLogMiddleware, RequestIDMiddleware, SecurityHeadersMiddleware
from app.core.redis import check_redis, close_redis, redis_configured
setup_logging()
logger = get_logger("app.main")


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
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
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
    return JSONResponse(status_code=200 if result["status"] == "ok" else 503, content=result)


app.include_router(api_router, prefix=settings.API_V1_PREFIX)
