"""Concurrency invariants on a real PostgreSQL instance.

These run only when AIROS_TEST_DATABASE_URL is set to an ISOLATED, throwaway
local database. The fixture drops and recreates every table, so it refuses
anything that is not localhost/127.0.0.1 with 'test' in the database name.

Example (local Docker, never a shared or production database):
    docker run -d --name airos-audit-pg -p 55432:5432 \
        -e POSTGRES_PASSWORD=audit -e POSTGRES_DB=airos_audit_test postgres:16-alpine
    AIROS_TEST_DATABASE_URL=postgresql+asyncpg://postgres:audit@localhost:55432/airos_audit_test \
        python -m pytest tests/integration -q
"""
import asyncio
import os
import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.attendance import AttendanceBreak, AttendanceDay
from app.models.company import Company
from app.models.employee import Employee
from app.models.property import Property
from app.models.structure import Zone
from app.models.task import Task
from app.models.user import User, UserRole
from app.models.work_allocation import WorkAllocationHistory

URL = os.environ.get("AIROS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not URL, reason="set AIROS_TEST_DATABASE_URL to an isolated local Postgres"
)


def _guard(url: str) -> None:
    host_ok = "localhost" in url or "127.0.0.1" in url
    assert host_ok, "refusing: integration DB must be local"
    assert "test" in url.rsplit("/", 1)[-1], "refusing: database name must contain 'test'"


@pytest.fixture
async def pg():
    from app.models import Base

    _guard(URL)
    engine = create_async_engine(URL)
    async with engine.begin() as conn:
        # drop_all cannot order the departments<->employees foreign-key cycle;
        # the isolated test database is reset as a whole instead.
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
        # Sequences are created by the Alembic chain in production, not create_all.
        for seq in ("work_batch_seq", "maintenance_ticket_seq", "task_ticket_seq"):
            await conn.execute(text(f"CREATE SEQUENCE IF NOT EXISTS {seq} START 1"))
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def _world(sm, *, employees=2, pending=0):
    """Company + property + zone + N employees (housekeeping, one user each)."""
    async with sm() as s:
        company = Company(
            company_name="Acme", brand_name="Acme", address="1 Main St",
            pin_code="10001", email="ops@acme.test", phone_number="555-0000",
        )
        s.add(company)
        await s.flush()
        prop = Property(
            company_id=company.id, name="HQ", code="HQ1", location="Loc", city="City",
            state="ST", manager_name="M", manager_email="m@x.test",
        )
        s.add(prop)
        await s.flush()
        zone = Zone(property_id=prop.id, name="Zone A", code="ZA", floor="F1")
        s.add(zone)
        await s.flush()
        emps, users = [], []
        for i in range(employees):
            emp = Employee(
                company_id=company.id, property_id=prop.id, name=f"Worker {i}",
                email=f"w{i}@acme.test", status="Active", department="Housekeeping",
                zone_id=zone.id,
            )
            s.add(emp)
            await s.flush()
            user = User(
                company_id=company.id, property_id=prop.id, name=f"Worker {i}",
                email=f"u{i}@acme.test", username=f"u{i}", password_hash="x",
                role=UserRole.EMPLOYEE, employee_id=emp.id,
            )
            s.add(user)
            emps.append(emp)
            users.append(user)
        for _ in range(pending):
            s.add(Task(property_id=prop.id, zone_id=zone.id, title="Clean",
                       status="pending", work_type="cleaning"))
        await s.commit()
        return {
            "company": company.id, "prop": prop.id, "zone": zone.id,
            "emps": [e.id for e in emps], "users": [u.id for u in users],
        }


async def _user(sm, user_id):
    async with sm() as s:
        return await s.get(User, user_id)


async def _add_tasks(sm, w, n, *, employee_index=None, status="pending"):
    """Work created AFTER clock-in: starting the day already sweeps any
    existing pending work, so racing sweeps need fresh pending rows."""
    async with sm() as s:
        for _ in range(n):
            s.add(Task(
                property_id=w["prop"], zone_id=w["zone"], title="Clean",
                status=status, work_type="cleaning",
                employee_id=None if employee_index is None else w["emps"][employee_index],
            ))
        await s.commit()


async def _start_day(sm, user_id):
    from app.services.attendance import AttendanceService

    async with sm() as s:
        await AttendanceService(s).start(await s.get(User, user_id))


async def test_concurrent_start_day_yields_exactly_one_open_day(pg):
    from app.services.attendance import AttendanceService

    w = await _world(pg)
    users = [await _user(pg, w["users"][0]) for _ in range(2)]

    async def go(u):
        async with pg() as s:
            await AttendanceService(s).start(await s.get(User, u.id))
            return True

    results = await asyncio.gather(*(go(u) for u in users), return_exceptions=True)
    assert sum(1 for r in results if r is True) == 1, results
    async with pg() as s:
        rows = (await s.execute(select(AttendanceDay).where(
            AttendanceDay.employee_id == w["emps"][0]))).scalars().all()
        assert len(rows) == 1 and rows[0].started_at is not None


async def test_concurrent_break_and_end_never_end_a_day_with_an_open_break(pg):
    from app.services.attendance import AttendanceService

    w = await _world(pg)
    await _start_day(pg, w["users"][0])
    user = await _user(pg, w["users"][0])

    async def brk():
        async with pg() as s:
            await AttendanceService(s).start_break(await s.get(User, user.id))

    async def end():
        async with pg() as s:
            await AttendanceService(s).end(await s.get(User, user.id))

    await asyncio.gather(brk(), end(), return_exceptions=True)
    async with pg() as s:
        day = (await s.execute(select(AttendanceDay).where(
            AttendanceDay.employee_id == w["emps"][0]))).scalar_one()
        open_breaks = await s.scalar(
            select(func.count()).select_from(AttendanceBreak).where(
                AttendanceBreak.attendance_day_id == day.id,
                AttendanceBreak.ended_at.is_(None),
            )
        )
        assert not (day.ended_at is not None and open_breaks > 0)


async def test_concurrent_sweeps_assign_each_task_exactly_once(pg):
    from app.services.availability import AvailabilityService
    from app.services.attendance import AttendanceService

    w = await _world(pg, employees=1)
    await _start_day(pg, w["users"][0])
    await _add_tasks(pg, w, 3)

    async def sweep():
        async with pg() as s:
            return await AvailabilityService(s).sweep_on_duty(w["emps"][0])

    counts = await asyncio.gather(sweep(), sweep())
    assert sum(counts) == 3
    async with pg() as s:
        tasks = (await s.execute(select(Task).where(Task.zone_id == w["zone"]))).scalars().all()
        assert len(tasks) == 3 and all(t.employee_id == w["emps"][0] for t in tasks)
        history = await s.scalar(select(func.count()).select_from(WorkAllocationHistory).where(
            WorkAllocationHistory.ticket_kind == "task",
            WorkAllocationHistory.employee_id == w["emps"][0]))
        assert history == 3


@pytest.mark.parametrize("round_no", range(5))
async def test_sweep_racing_end_day_never_leaves_work_with_ended_employee(pg, round_no):
    from app.services.attendance import AttendanceService
    from app.services.availability import AvailabilityService

    w = await _world(pg, employees=2)
    await _start_day(pg, w["users"][0])
    await _start_day(pg, w["users"][1])
    await _add_tasks(pg, w, 2, employee_index=0, status="assigned")
    await _add_tasks(pg, w, 2)
    ender = await _user(pg, w["users"][0])

    async def end_day():
        async with pg() as s:
            await AttendanceService(s).end(await s.get(User, ender.id))

    async def sweep():
        async with pg() as s:
            await AvailabilityService(s).sweep_on_duty(w["emps"][1])

    await asyncio.gather(end_day(), sweep(), return_exceptions=True)
    async with pg() as s:
        still_with_ender = await s.scalar(select(func.count()).select_from(Task).where(
            Task.employee_id == w["emps"][0], Task.status == "assigned"))
        total_open = await s.scalar(select(func.count()).select_from(Task).where(
            Task.zone_id == w["zone"], Task.status.in_(("pending", "assigned"))))
        assert still_with_ender == 0
        assert total_open == 4


async def test_concurrent_allocations_on_one_zone_pick_distinct_employees(pg):
    from app.services.work_allocation import WorkAllocationService

    w = await _world(pg, employees=2)
    await _start_day_many(pg, w["users"])

    async def allocate_and_record():
        async with pg() as s:
            svc = WorkAllocationService(s)
            res = await svc.allocate(
                None, property_id=w["prop"], zone_id=w["zone"], zone_name="Zone A",
                work_type="cleaning", company_id=w["company"],
            )
            await svc.record(
                property_id=w["prop"], zone_id=w["zone"], batch=res.batch,
                ticket_kind="task", ticket_id=uuid.uuid4(), ticket_number=None,
                employee_id=res.employee.id, employee_name=res.employee.name,
                method=res.method,
            )
            await s.commit()
            return res.employee.id

    picks = await asyncio.gather(allocate_and_record(), allocate_and_record())
    assert len(set(picks)) == 2, picks


async def _start_day_many(sm, user_ids):
    for uid in user_ids:
        await _start_day(sm, uid)
