"""AiROS employee backend application entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import check_database, close_db, describe_db_error
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.core.middleware import AccessLogMiddleware, RequestIDMiddleware, SecurityHeadersMiddleware
from app.core.redis import check_redis, close_redis, redis_configured
from app.core.storage import LocalStorage

setup_logging()
logger = get_logger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    for warning in settings.production_warnings():
        logger.warning("Production warning: %s", warning)
    yield
    await close_redis()
    await close_db()


app = FastAPI(
    title="AiROS Employee API",
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

_uploads = LocalStorage().dir
_uploads.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(_uploads)), name="uploads")


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok", "service": "AiROS Employee API", "env": settings.APP_ENV}


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
