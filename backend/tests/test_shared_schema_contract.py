"""Shared-database boundary contract tests.

This backend shares one PostgreSQL database — and one alembic_version row —
with the Super Admin backend. These tests pin the invariants that keep that
arrangement safe, without needing a live database:

* the migration chain stays a single linear head (never branches);
* the extended-coverage revision (secondary zone + property-wide flag) is
  mirrored and resolvable with the correct parentage;
* the ORM maps the coverage columns the Super Admin side writes;
* the schema-drift boot check exists and tolerates DBs with no
  alembic_version table (local SQLite dev path).
"""
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base
from app.models.employee import Employee

_ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"

_SHARED_REVISIONS = {
    "y5d8f2a6c4e1": "x8b3d6f1a4c7",  # employee extended coverage
    "b4e9f2a7c3d6": "y5d8f2a6c4e1",  # employee multi-area coverage
    "u7e1f5a9d3c6": None,  # EB-owned tables, mirrored on the SA side
}

# Tables the Super Admin backend owns or shares — EB reads several of these
# directly (tasks, notifications, work_templates) and must keep them mapped.
_SHARED_TABLES = {
    "attendance_days", "attendance_requests",
    "notifications", "shifts", "employee_shift_assignments",
    "employees", "users", "occupancies", "tasks", "maintenance_tickets",
    "refresh_tokens", "cameras", "camera_stream_sessions", "work_templates", "employee_area_assignments",
}


def _scripts() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(_ALEMBIC_INI)))


def test_chain_has_single_head():
    """ONE linear chain — the shared alembic_version row must never branch."""
    assert len(_scripts().get_heads()) == 1


def test_shared_revisions_resolvable():
    scripts = _scripts()
    for revision, parent in _SHARED_REVISIONS.items():
        rev = scripts.get_revision(revision)
        assert rev is not None, f"missing shared revision {revision}"
        if parent is not None:
            assert rev.down_revision == parent


def test_extended_coverage_columns_mapped():
    """EB reads these columns — written by the SA allocation surface."""
    cols = {c.name for c in Employee.__table__.columns}
    assert {"secondary_zone_id", "covers_property"} <= cols
    assert Employee.__table__.c.covers_property.nullable is False


def test_shared_tables_present_in_metadata():
    tables = set(Base.metadata.tables)
    missing = _SHARED_TABLES - tables
    assert not missing, f"shared tables unmapped on EB side: {missing}"


@pytest.mark.asyncio
async def test_schema_check_tolerates_no_alembic_table(monkeypatch):
    """A create_all-built dev DB has no alembic_version — check must not
    report it stale (there is no revision to compare against)."""
    from app import main as app_main

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession)
    monkeypatch.setattr(app_main, "AsyncSessionLocal", factory)
    try:
        assert await app_main.check_schema_version() is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_schema_check_flags_stale_db(monkeypatch):
    """A DB stamped at a non-head revision must be reported stale."""
    from sqlalchemy import text

    from app import main as app_main

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        await conn.execute(text("INSERT INTO alembic_version VALUES ('definitely_not_head')"))
    factory = async_sessionmaker(engine, class_=AsyncSession)
    monkeypatch.setattr(app_main, "AsyncSessionLocal", factory)
    try:
        stale = await app_main.check_schema_version()
        assert stale is not None
        assert "stale" in stale or "schema" in stale
    finally:
        await engine.dispose()
