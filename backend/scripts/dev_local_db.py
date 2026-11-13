"""Local-dev database bootstrap — NO remote access.

Used by `python main.py --local` (and runnable standalone):

    python -m scripts.dev_local_db            # create schema only
    python -m scripts.dev_local_db --seed     # + demo tenant & tasks

It ONLY makes sense against a local DATABASE_URL — the intended target is
the sqlite file `backend/dev.db` that `--local` injects
(`sqlite+aiosqlite:///./dev.db`). It refuses to run against any host that
isn't loopback/sqlite so a stray remote URL can never be schema-created.

Schema is created straight from `Base.metadata` (the same path the
in-memory unit tests use). The Alembic chain is Postgres-targeted and is
NOT replayed here — run `alembic upgrade head` against a real local
Postgres when one is available.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.models import Base


def _assert_local_url() -> None:
    """Fail loudly if DATABASE_URL resolves to anything non-local."""
    url = settings.database_url
    if url.startswith("sqlite"):
        return
    host = urlparse(url).hostname or ""
    # 'postgres' is the bundled compose service hostname — local by
    # construction (it can only resolve inside the compose network).
    if host in ("postgres", "localhost", "127.0.0.1", "::1"):
        return
    raise SystemExit(
        f"Refusing to initialise a non-local database (host={host!r}). "
        "Point DATABASE_URL at sqlite or a loopback Postgres first."
    )


async def _create_schema() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


ZONE_ID = uuid.UUID("de000000-0000-4000-8000-0000000000d1")
ROOM_ID = uuid.UUID("de000000-0000-4000-8000-0000000000d2")


async def _seed_demo_work() -> None:
    """Demo zone + room + two assigned tasks so the task list, task detail
    and the speaker button are visible immediately after login."""
    from app.models.structure import Room, Zone
    from app.models.task import Task
    from scripts.seed_demo import EMP_ID, PROP_ID, main as seed_tenant

    await seed_tenant()  # idempotent company/property/employee/users

    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as s:
        zone = await s.get(Zone, ZONE_ID)
        if zone is None:
            zone = Zone(
                id=ZONE_ID, property_id=PROP_ID, name="Wing A", code="WING-A",
                zone_type="stay", status="active",
            )
            s.add(zone)

        room = await s.get(Room, ROOM_ID)
        if room is None:
            room = Room(
                id=ROOM_ID, property_id=PROP_ID, zone_id=ZONE_ID,
                room_number="205", type="Private Room", status="available",
            )
            s.add(room)

        existing = await s.scalar(
            select(Task.id).where(Task.employee_id == EMP_ID).limit(1)
        )
        if existing is None:
            s.add_all([
                Task(
                    property_id=PROP_ID, zone_id=ZONE_ID, room_id=ROOM_ID,
                    room_number="205", employee_id=EMP_ID,
                    assigned_to_name="Demo Employee",
                    title="Clean room 205",
                    description="Mop the floor, change the sheets, and restock towels.",
                    task_type="fixed", work_type="cleaning", origin="manual",
                    status="assigned", priority="high",
                    allocation_status="manually_assigned",
                ),
                Task(
                    property_id=PROP_ID, zone_id=ZONE_ID, employee_id=EMP_ID,
                    assigned_to_name="Demo Employee",
                    title="Inspect lobby HVAC filter",
                    description="Check the lobby air filter and report dust buildup.",
                    task_type="fixed", work_type="inspection", origin="manual",
                    status="pending", priority="medium",
                    allocation_status="manually_assigned",
                ),
            ])
            print("created 2 demo tasks for Demo Employee")
        await s.commit()


async def amain(seed: bool) -> None:
    _assert_local_url()
    await _create_schema()
    print(f"schema ready ({settings.database_url.split(':', 1)[0]})")
    if seed:
        await _seed_demo_work()
    await engine.dispose()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--seed", action="store_true",
                   help="seed the demo tenant + demo tasks")
    args = p.parse_args()
    sys.exit(asyncio.run(amain(args.seed)) or 0)
