import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError, ProgrammingError, TimeoutError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core import database, metrics
from app.core.config import Settings
from app.core.exceptions import register_exception_handlers


def test_pool_defaults_and_engine_configuration():
    config = Settings(_env_file=None)
    assert (config.DB_POOL_SIZE, config.DB_MAX_OVERFLOW) == (2, 1)
    assert (config.DB_POOL_TIMEOUT, config.DB_POOL_RECYCLE) == (10, 900)
    assert config.DB_POOL_PRE_PING is True
    assert database.engine.pool.size() == 2
    assert database.engine.pool._max_overflow == 1
    assert database.engine.pool._pre_ping is True


def test_pool_settings_are_bounded_and_overridable():
    config = Settings(_env_file=None, DB_POOL_SIZE=1, DB_MAX_OVERFLOW=0,
                      DB_POOL_TIMEOUT=3, DB_POOL_RECYCLE=60, DB_POOL_PRE_PING=False)
    assert (config.DB_POOL_SIZE, config.DB_MAX_OVERFLOW) == (1, 0)
    assert config.DB_POOL_PRE_PING is False
    for key, value in [("DB_POOL_SIZE", 0), ("DB_MAX_OVERFLOW", -1),
                       ("DB_POOL_TIMEOUT", 0), ("DB_POOL_RECYCLE", -1)]:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **{key: value})


@pytest.fixture
async def bounded_pool(tmp_path, monkeypatch):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'pool.db'}", pool_size=2,
        max_overflow=1, pool_timeout=1, pool_pre_ping=True,
    )
    monkeypatch.setattr(database, "AsyncSessionLocal", async_sessionmaker(engine))
    try:
        yield engine
    finally:
        await engine.dispose()


async def test_request_sessions_close_after_success_failure_and_cancellation(bounded_pool):
    dep = database.get_db()
    session = await anext(dep)
    await session.execute(text("SELECT 1"))
    await dep.aclose()
    assert bounded_pool.pool.checkedout() == 0

    for error in [RuntimeError("request failed"), asyncio.CancelledError()]:
        dep = database.get_db()
        session = await anext(dep)
        await session.execute(text("SELECT 1"))
        with pytest.raises(type(error)):
            await dep.athrow(error)
        assert bounded_pool.pool.checkedout() == 0


async def test_cancelled_request_releases_checked_out_connection(bounded_pool):
    acquired = asyncio.Event()

    async def request():
        dep = database.get_db()
        session = await anext(dep)
        try:
            await session.execute(text("SELECT 1"))
            acquired.set()
            await asyncio.Event().wait()
        finally:
            await dep.aclose()

    task = asyncio.create_task(request())
    await acquired.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert bounded_pool.pool.checkedout() == 0


async def test_repeated_post_login_bursts_stay_within_connection_ceiling(bounded_pool):
    peak = 0
    sessions = set()

    @event.listens_for(bounded_pool.sync_engine, "checkout")
    def checkout(*args):
        nonlocal peak
        peak = max(peak, bounded_pool.pool.checkedout())

    async def request():
        dep = database.get_db()
        session = await anext(dep)
        assert session not in sessions
        sessions.add(session)
        try:
            assert (await session.execute(text("SELECT 1"))).scalar_one() == 1
            await asyncio.sleep(0.005)
        finally:
            sessions.remove(session)
            await dep.aclose()

    for _ in range(10):
        await asyncio.gather(*(request() for _ in range(8)))
        assert bounded_pool.pool.checkedout() == 0
    assert 1 <= peak <= 3


def test_pooler_driver_arguments_and_url_normalization_are_preserved(monkeypatch):
    config = Settings(_env_file=None, DATABASE_URL="postgresql://test:test@pooler.example.test:5432/test")
    monkeypatch.setattr(database, "settings", config)
    assert config.database_url.startswith("postgresql+asyncpg://")
    args = database._connect_args()
    assert args["timeout"] == 15
    assert args["command_timeout"] == 30
    assert args["prepared_statement_cache_size"] == 0
    assert args["prepared_statement_name_func"]() != args["prepared_statement_name_func"]()


async def test_local_saturation_times_out_and_releases_waiting_session(bounded_pool):
    from contextlib import AsyncExitStack

    async with AsyncExitStack() as stack:
        for _ in range(3):
            await stack.enter_async_context(bounded_pool.connect())
        dep = database.get_db()
        session = await anext(dep)
        try:
            with pytest.raises(TimeoutError):
                await session.execute(text("SELECT 1"))
        finally:
            await dep.aclose()
        assert bounded_pool.pool.checkedout() == 3
    assert bounded_pool.pool.checkedout() == 0


@pytest.mark.parametrize("error,code", [
    (TimeoutError("pool timeout"), "DATABASE_BUSY"),
    (DBAPIError(None, None, Exception("(EMAXCONNSESSION) max clients reached")), "DATABASE_BUSY"),
    (ProgrammingError(None, None, Exception("invalid column")), "DATABASE_ERROR"),
])
async def test_database_errors_are_classified_and_sanitized(error, code):
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/probe")
    async def probe():
        raise error

    token = metrics.begin()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/probe")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == code
        assert "EMAXCONNSESSION" not in response.text
        assert "invalid column" not in response.text
        assert response.headers.get("Retry-After") == ("1" if code == "DATABASE_BUSY" else None)
        assert metrics.current()["db_pool_exhaustions"] == (1 if code == "DATABASE_BUSY" else 0)
    finally:
        metrics.end(token)


async def test_shutdown_disposes_database_if_redis_cleanup_fails(monkeypatch):
    import app.main as main

    close = AsyncMock()
    monkeypatch.setattr(main, "close_db", close)
    monkeypatch.setattr(main, "close_redis", AsyncMock(side_effect=RuntimeError("redis")))
    with pytest.raises(RuntimeError, match="redis"):
        async with main.lifespan(main.app):
            pass
    close.assert_awaited_once()


async def test_push_releases_connection_before_external_send(session, seed, monkeypatch):
    from types import SimpleNamespace
    from app.models.notifications import DeviceRegistration
    from app.services import notifications

    employee_id = seed["employee"].id
    session.add(DeviceRegistration(
        employee_id=employee_id, device_id="pool-test", push_token="token",
        platform="android", is_active=True,
    ))
    await session.commit()

    async def send(*args, **kwargs):
        assert not session.in_transaction()
        return SimpleNamespace(invalid_tokens=["token"])

    monkeypatch.setattr(notifications, "get_push_provider", lambda: SimpleNamespace(send=send))
    await notifications._dispatch_snapshot(session, {
        "employee_id": employee_id, "notification_id": "test", "title": "test",
        "body": "test", "data": {},
    })
    assert not session.in_transaction()
    assert (await session.execute(text("SELECT is_active FROM device_registrations WHERE device_id='pool-test'"))).scalar_one() == 0


async def test_location_releases_completed_reads_before_redis(session, seed, monkeypatch):
    from types import SimpleNamespace
    from app.services import location_tracking

    async def redis_operation(*args, **kwargs):
        assert not session.in_transaction()

    redis = SimpleNamespace(set=redis_operation, delete=redis_operation)
    monkeypatch.setattr(location_tracking, "_redis_required", AsyncMock(return_value=redis))
    employee_id = seed["employee"].id
    user = seed["emp_user"]
    row = await location_tracking.start_session(user, employee_id, session)
    await location_tracking.stop_session(user, employee_id, row.id, session)
    await location_tracking.stop_session(user, employee_id, row.id, session)


async def test_media_releases_auth_session_before_storage(monkeypatch):
    from io import BytesIO
    from types import SimpleNamespace
    from fastapi import UploadFile
    from starlette.datastructures import Headers
    from app.api.v1 import media

    session = AsyncMock()

    async def save(*args):
        session.close.assert_awaited_once()
        return "object.png"

    monkeypatch.setattr(media, "get_storage", lambda: SimpleNamespace(save=save))
    file = UploadFile(BytesIO(b"\x89PNG\r\n\x1a\nimage"), filename="image.png",
                      headers=Headers({"content-type": "image/png"}))
    result = await media.upload_media(None, file, object(), session)
    assert "url" in result


async def test_apk_releases_read_session_before_storage(monkeypatch):
    from types import SimpleNamespace
    from app.api.v1 import mobile

    session = AsyncMock()
    monkeypatch.setattr(mobile.release_service, "get_active_release", AsyncMock(return_value=SimpleNamespace(
        platform="android", version="1.0", download_url="/api/v1/media/file/" + "a" * 32 + ".apk",
    )))

    async def stream():
        yield b"APK"

    async def open_object(key):
        session.close.assert_awaited_once()
        return stream, "application/vnd.android.package-archive", 3

    monkeypatch.setattr(mobile, "get_storage", lambda: SimpleNamespace(open=open_object))
    response = await mobile.download_active_apk("android", session)
    assert response.status_code == 200
