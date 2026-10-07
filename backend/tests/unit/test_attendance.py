"""Attendance — workday lifecycle, day-off requests, RBAC scoping,
operational-day boundaries, and DB-constraint invariants.

Service-level suite (same convention as test_occupancy.py) — the HTTP
layer is thin routing over AttendanceService.
"""
import uuid
from datetime import date as date_type, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.dependencies.auth import Forbidden
from app.models.attendance import (
    AttendanceBreak,
    AttendanceDay,
    AttendanceRequest,
)
from app.models.company import Company
from app.models.employee import Employee
from app.models.property import Property
from app.models.task import Task, TaskHistoryEvent
from app.models.user import User, UserRole
from app.models import Base
from app.repositories.attendance import AttendanceRepository
from app.services.attendance import AttendanceService
from app.services.rollover import (
    RolloverService,
    current_operational_day,
    operational_day_key,
    parse_day_start,
)
from app.services.structure import ConflictErr, NotFoundErr, ValidationErr

IST = ZoneInfo("Asia/Kolkata")

FUTURE = "2999-01-15"
FUTURE_FROM = "2999-01-10"
FUTURE_TO = "2999-01-12"


def op_date_today() -> str:
    return current_operational_day(
        datetime.now(timezone.utc), time(6, 0)
    )


def file_kwargs(frm=FUTURE_FROM, to=FUTURE_TO, cat="leave",
                leave_type="casual_leave", reason="Family event"):
    return {
        "from_date": frm, "to_date": to, "request_type": cat,
        "leave_type": leave_type, "reason": reason,
    }


def other_property(seed):
    return seed["prop"].id, seed


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def seeded(session, seed):
    """seed + a second employee/user pair and a foreign-property user set."""
    prop = seed["prop"]
    company = seed["company"]
    employee2 = Employee(
        company_id=company.id, property_id=prop.id, name="Worker Two",
        email="worker2@acme.test", status="active",
    )
    session.add(employee2)
    await session.flush()
    emp_user_b = User(
        company_id=company.id, property_id=prop.id, name="Emp B",
        email="empb@acme.test", username="empb", password_hash="x",
        role=UserRole.EMPLOYEE, employee_id=employee2.id,
    )
    session.add(emp_user_b)

    prop2 = Property(
        company_id=company.id, name="Other", code="OT1", location="Loc",
        city="City", state="ST", manager_name="M2", manager_email="m2@x.test",
    )
    session.add(prop2)
    await session.flush()
    pm_other = User(
        company_id=company.id, property_id=prop2.id, name="PM Other",
        email="pmo@acme.test", username="pmo", password_hash="x",
        role=UserRole.PROPERTY_MANAGER,
    )
    session.add(pm_other)
    await session.commit()
    return {
        **seed,
        "employee2": employee2, "emp_user_b": emp_user_b,
        "prop2": prop2, "pm_other": pm_other,
    }


# ---------------------------------------------------------------------------
# Operational-day math (pure functions)
# ---------------------------------------------------------------------------

def test_parse_day_start():
    assert parse_day_start("06:00") == time(6, 0)
    assert parse_day_start("00:30") == time(0, 30)
    assert parse_day_start(None) == time(6, 0)
    assert parse_day_start("junk") == time(6, 0)
    assert parse_day_start("25:00") == time(6, 0)


def test_operational_day_key_boundaries():
    start = time(6, 0)
    # 00:15 IST → still yesterday's operational day
    assert operational_day_key(datetime(2026, 3, 10, 0, 15), start) == "2026-03-09"
    # 05:59 → previous day; 06:00 → same day; 23:59 → same day
    assert operational_day_key(datetime(2026, 3, 10, 5, 59), start) == "2026-03-09"
    assert operational_day_key(datetime(2026, 3, 10, 6, 0), start) == "2026-03-10"
    assert operational_day_key(datetime(2026, 3, 10, 23, 59), start) == "2026-03-10"
    # a midnight-start company keys by the plain calendar date
    assert operational_day_key(
        datetime(2026, 3, 10, 0, 15), time(0, 0)
    ) == "2026-03-10"


# ---------------------------------------------------------------------------
# today / lifecycle
# ---------------------------------------------------------------------------

async def test_today_not_started(session, seeded):
    day, date, request = await AttendanceService(session).today(
        seeded["emp_user"]
    )
    assert day is None and request is None
    assert date == op_date_today()


async def test_employee_without_employee_id_forbidden(session, seeded):
    svc = AttendanceService(session)
    with pytest.raises(Forbidden):
        await svc.today(seeded["emp_user2"])
    with pytest.raises(Forbidden):
        await svc.start(seeded["emp_user2"])
    with pytest.raises(Forbidden):
        await svc.calendar(seeded["emp_user2"], "2026-01")


async def test_full_lifecycle(session, seeded):
    svc = AttendanceService(session)
    day, _ = await svc.start(seeded["emp_user"])
    assert day.status == "present" and day.started_at is not None

    day, _ = await svc.start_break(seeded["emp_user"])
    day, _ = await svc.resume(seeded["emp_user"])
    assert len(day.breaks) == 1
    assert day.breaks[0].duration_seconds is not None
    assert day.break_seconds >= 0

    day, _ = await svc.end(seeded["emp_user"])
    assert day.ended_at is not None
    assert day.work_seconds == (
        int((day.ended_at - day.started_at).total_seconds())
        - day.break_seconds
    )

    # Post-commit the row is durable; today reflects 'completed'.
    day2, date, _ = await svc.today(seeded["emp_user"])
    assert day2.id == day.id and day2.ended_at is not None


async def test_start_twice_conflicts(session, seeded):
    svc = AttendanceService(session)
    await svc.start(seeded["emp_user"])
    with pytest.raises(ConflictErr):
        await svc.start(seeded["emp_user"])


async def test_break_requires_started_day(session, seeded):
    with pytest.raises(ConflictErr):
        await AttendanceService(session).start_break(seeded["emp_user"])


async def test_double_break_conflicts(session, seeded):
    svc = AttendanceService(session)
    await svc.start(seeded["emp_user"])
    await svc.start_break(seeded["emp_user"])
    with pytest.raises(ConflictErr):
        await svc.start_break(seeded["emp_user"])


async def test_resume_without_break_conflicts(session, seeded):
    svc = AttendanceService(session)
    await svc.start(seeded["emp_user"])
    with pytest.raises(ConflictErr):
        await svc.resume(seeded["emp_user"])


async def test_end_with_open_break_conflicts(session, seeded):
    svc = AttendanceService(session)
    await svc.start(seeded["emp_user"])
    await svc.start_break(seeded["emp_user"])
    with pytest.raises(ConflictErr):
        await svc.end(seeded["emp_user"])


async def test_break_and_resume_after_end_conflict(session, seeded):
    svc = AttendanceService(session)
    await svc.start(seeded["emp_user"])
    await svc.end(seeded["emp_user"])
    with pytest.raises(ConflictErr):
        await svc.start_break(seeded["emp_user"])
    with pytest.raises(ConflictErr):
        await svc.resume(seeded["emp_user"])
    with pytest.raises(ConflictErr):
        await svc.end(seeded["emp_user"])


async def test_employees_isolated(session, seeded):
    """A's workday never leaks into B's view or lifecycle."""
    svc = AttendanceService(session)
    await svc.start(seeded["emp_user"])
    day_b, date_b, _ = await svc.today(seeded["emp_user_b"])
    assert day_b is None  # B untouched by A's start
    await svc.start(seeded["emp_user_b"])
    days = await session.execute(
        select(AttendanceDay).where(
            AttendanceDay.attendance_date == op_date_today()
        )
    )
    assert len(days.scalars().all()) == 2


# ---------------------------------------------------------------------------
# Leave / week-off requests — employee side
# ---------------------------------------------------------------------------

async def test_request_create_casual_range(session, seeded):
    svc = AttendanceService(session)
    req = await svc.create_request(
        seeded["emp_user"], **file_kwargs(),
    )
    assert req.status == "pending"
    assert req.from_date == "2999-01-10" and req.to_date == "2999-01-12"
    assert req.request_type == "leave"
    assert req.leave_type == "casual_leave"
    assert req.requested_days == 3  # inclusive


async def test_request_create_sick_single_day(session, seeded):
    svc = AttendanceService(session)
    req = await svc.create_request(
        seeded["emp_user"],
        **file_kwargs(frm=FUTURE, to=FUTURE, leave_type="sick_leave"),
    )
    assert req.requested_days == 1
    assert req.from_date == req.to_date == FUTURE


@pytest.mark.parametrize("leave_type", ["paid_leave", "unpaid_leave", "other"])
async def test_request_create_leave_types(session, seeded, leave_type):
    svc = AttendanceService(session)
    req = await svc.create_request(
        seeded["emp_user"],
        **file_kwargs(to="2999-01-13", leave_type=leave_type),
    )
    assert req.leave_type == leave_type and req.requested_days == 4


async def test_request_create_week_off(session, seeded):
    svc = AttendanceService(session)
    req = await svc.create_request(
        seeded["emp_user"],
        **file_kwargs(cat="week_off", leave_type=None, reason=None),
    )
    assert req.request_type == "week_off"
    assert req.leave_type is None and req.reason is None


async def test_request_overlap_conflict(session, seeded):
    svc = AttendanceService(session)
    await svc.create_request(
        seeded["emp_user"],
        **file_kwargs(frm="2999-01-10", to="2999-01-15"),
    )
    with pytest.raises(ConflictErr) as err:
        await svc.create_request(
            seeded["emp_user"],
            **file_kwargs(frm="2999-01-12", to="2999-01-14"),
        )
    assert err.value.code == "OVERLAPPING_REQUEST"


async def test_request_overlap_inclusive_boundary(session, seeded):
    """10-15 vs 15-20 conflicts (shared edge day); 10-15 vs 16-20 is OK."""
    svc = AttendanceService(session)
    await svc.create_request(
        seeded["emp_user"],
        **file_kwargs(frm="2999-01-10", to="2999-01-15"),
    )
    with pytest.raises(ConflictErr):
        await svc.create_request(
            seeded["emp_user"],
            **file_kwargs(frm="2999-01-15", to="2999-01-20"),
        )
    req = await svc.create_request(
        seeded["emp_user"],
        **file_kwargs(frm="2999-01-16", to="2999-01-20"),
    )
    assert req.status == "pending"


async def test_request_overlap_ignored_after_decision(session, seeded):
    """Rejected/cancelled filings release the range for a re-file."""
    svc = AttendanceService(session)
    req = await svc.create_request(seeded["emp_user"], **file_kwargs())
    await svc.review_request(seeded["admin"], req.id, approve=False)
    req2 = await svc.create_request(seeded["emp_user"], **file_kwargs())
    assert req2.status == "pending"
    await svc.cancel_request(seeded["emp_user"], req2.id)
    req3 = await svc.create_request(seeded["emp_user"], **file_kwargs())
    assert req3.status == "pending"


async def test_request_overlap_only_per_employee(session, seeded):
    """Overlapping ranges across DIFFERENT employees never conflict."""
    svc = AttendanceService(session)
    await svc.create_request(seeded["emp_user"], **file_kwargs())
    req = await svc.create_request(
        seeded["emp_user_b"], **file_kwargs(),
    )
    assert req.status == "pending"


async def test_request_validation(session, seeded):
    svc = AttendanceService(session)
    emp = seeded["emp_user"]
    # malformed dates
    with pytest.raises(ValidationErr):
        await svc.create_request(
            emp, **file_kwargs(frm="2027-1-5"),
        )
    with pytest.raises(ValidationErr):
        await svc.create_request(
            emp, **file_kwargs(to="not-a-date"),
        )
    # to before from
    with pytest.raises(ValidationErr):
        await svc.create_request(
            emp, **file_kwargs(frm="2999-01-12", to="2999-01-10"),
        )
    # unknown category / leave_type
    with pytest.raises(ValidationErr):
        await svc.create_request(
            emp, **file_kwargs(cat="holiday"),
        )
    with pytest.raises(ValidationErr):
        await svc.create_request(
            emp, **file_kwargs(leave_type="sabbatical"),
        )
    # leave requires a reason; week_off must not carry a leave_type
    with pytest.raises(ValidationErr):
        await svc.create_request(
            emp, **file_kwargs(reason=None),
        )
    with pytest.raises(ValidationErr):
        await svc.create_request(
            emp, **file_kwargs(reason="   "),
        )
    with pytest.raises(ValidationErr):
        await svc.create_request(
            emp, **file_kwargs(cat="week_off", leave_type="casual_leave",
                             reason=None),
        )
    # past operational dates are rejected
    with pytest.raises(ValidationErr):
        await svc.create_request(
            emp, **file_kwargs(frm="2020-01-01", to="2020-01-03"),
        )


async def test_cancel_own_pending_request(session, seeded):
    svc = AttendanceService(session)
    req = await svc.create_request(
        seeded["emp_user"],
        **file_kwargs(cat="week_off", leave_type=None, reason=None),
    )
    req = await svc.cancel_request(seeded["emp_user"], req.id)
    assert req.status == "cancelled"
    # cancelled requests free the range for a re-file
    req2 = await svc.create_request(
        seeded["emp_user"], **file_kwargs(),
    )
    assert req2.status == "pending"


async def test_cancel_non_pending_conflicts(session, seeded):
    svc = AttendanceService(session)
    req = await svc.create_request(
        seeded["emp_user"],
        **file_kwargs(cat="week_off", leave_type=None, reason=None),
    )
    await svc.cancel_request(seeded["emp_user"], req.id)
    with pytest.raises(ConflictErr):
        await svc.cancel_request(seeded["emp_user"], req.id)


async def test_cancel_other_employees_request_not_found(session, seeded):
    svc = AttendanceService(session)
    req = await svc.create_request(
        seeded["emp_user"],
        **file_kwargs(cat="week_off", leave_type=None, reason=None),
    )
    with pytest.raises(NotFoundErr):
        await svc.cancel_request(seeded["emp_user_b"], req.id)


async def test_cancel_requires_employee_role(session, seeded):
    svc = AttendanceService(session)
    req = await svc.create_request(
        seeded["emp_user"],
        **file_kwargs(cat="week_off", leave_type=None, reason=None),
    )
    with pytest.raises(Forbidden):
        await svc.cancel_request(seeded["pm"], req.id)


async def test_employee_lists_own_requests_only(session, seeded):
    svc = AttendanceService(session)
    mine = await svc.create_request(seeded["emp_user"], **file_kwargs())
    other = await svc.create_request(
        seeded["emp_user_b"],
        **file_kwargs(cat="week_off", leave_type=None, reason=None),
    )
    items = await svc.list_requests(seeded["emp_user"])
    ids = [r.id for r in items]
    assert mine.id in ids and other.id not in ids


async def test_employee_list_requires_employee_link(session, seeded):
    with pytest.raises(Forbidden):
        await AttendanceService(session).list_requests(
            seeded["emp_user2"],  # EMPLOYEE role, no employee_id
        )


# ---------------------------------------------------------------------------
# Leave / week-off requests — reviewer side
# ---------------------------------------------------------------------------

async def test_employee_cannot_review(session, seeded):
    svc = AttendanceService(session)
    req = await svc.create_request(
        seeded["emp_user"],
        **file_kwargs(cat="week_off", leave_type=None, reason=None),
    )
    with pytest.raises(Forbidden):
        await svc.review_request(seeded["emp_user"], req.id, approve=True)
    with pytest.raises(Forbidden):
        await svc.list_requests_for_review(seeded["emp_user"])


async def test_sa_approves_leave_range_materializes_days(session, seeded):
    svc = AttendanceService(session)
    req = await svc.create_request(
        seeded["emp_user"], **file_kwargs(),
    )
    req = await svc.review_request(
        seeded["admin"], req.id, approve=True, review_comment="ok",
    )
    assert req.status == "approved"
    assert req.reviewed_by_id == seeded["admin"].id
    assert req.reviewed_by_name == seeded["admin"].name
    assert req.review_comment == "ok"
    # approval materialized a 'leave' day for EVERY date in the range
    res = await session.execute(
        select(AttendanceDay).where(
            AttendanceDay.employee_id == seeded["employee"].id,
            AttendanceDay.attendance_date >= FUTURE_FROM,
            AttendanceDay.attendance_date <= FUTURE_TO,
        ).order_by(AttendanceDay.attendance_date)
    )
    days = res.scalars().all()
    assert [d.attendance_date for d in days] == [
        "2999-01-10", "2999-01-11", "2999-01-12",
    ]
    assert all(d.status == "leave" and d.started_at is None for d in days)


async def test_sa_approves_week_off_range(session, seeded):
    svc = AttendanceService(session)
    req = await svc.create_request(
        seeded["emp_user"],
        **file_kwargs(cat="week_off", leave_type=None, reason=None),
    )
    await svc.review_request(seeded["admin"], req.id, approve=True)
    res = await session.execute(
        select(AttendanceDay).where(
            AttendanceDay.employee_id == seeded["employee"].id,
            AttendanceDay.attendance_date >= FUTURE_FROM,
        )
    )
    days = res.scalars().all()
    assert len(days) == 3
    assert all(d.status == "week_off" for d in days)


async def test_approve_overlapping_other_open_request_conflicts(
    session, seeded,
):
    """A second OPEN request overlapping the range (possible only via a
    create race — the app check + PG exclusion normally prevent it)
    makes approval a 409 instead of double-booking the shared dates."""
    svc = AttendanceService(session)
    r1 = await svc.create_request(
        seeded["emp_user"],
        **file_kwargs(frm="2999-01-10", to="2999-01-12"),
    )
    # Simulate the lost race: a pending row inserted bypassing the
    # app-level overlap check (sqlite carries no EXCLUDE constraint).
    r2 = AttendanceRequest(
        property_id=seeded["prop"].id, employee_id=seeded["employee"].id,
        employee_name="Worker One",
        from_date="2999-01-12", to_date="2999-01-14",
        request_type="week_off", leave_type=None,
        requested_days=3, status="pending",
    )
    session.add(r2)
    await session.commit()
    with pytest.raises(ConflictErr) as err:
        await svc.review_request(seeded["admin"], r1.id, approve=True)
    assert err.value.code == "OVERLAPPING_REQUEST"
    # decide r2 first → r1 approves cleanly
    await svc.review_request(seeded["admin"], r2.id, approve=False)
    req = await svc.review_request(seeded["admin"], r1.id, approve=True)
    assert req.status == "approved"


async def test_pm_cannot_approve_or_reject(session, seeded):
    """Approval authority is exclusive to SUPER_ADMIN — PM gets 403 even
    on a request inside his own property."""
    svc = AttendanceService(session)
    req = await svc.create_request(
        seeded["emp_user"], **file_kwargs(),
    )
    with pytest.raises(Forbidden):
        await svc.review_request(seeded["pm"], req.id, approve=True)
    with pytest.raises(Forbidden):
        await svc.review_request(seeded["pm"], req.id, approve=False)


async def test_hr_cannot_approve_or_reject(session, seeded):
    svc = AttendanceService(session)
    req = await svc.create_request(
        seeded["emp_user"], **file_kwargs(),
    )
    with pytest.raises(Forbidden):
        await svc.review_request(seeded["hr"], req.id, approve=True)
    with pytest.raises(Forbidden):
        await svc.review_request(seeded["hr"], req.id, approve=False)


async def test_sa_approves_company_scoped(session, seeded):
    svc = AttendanceService(session)
    req = await svc.create_request(
        seeded["emp_user"],
        **file_kwargs(cat="week_off", leave_type=None, reason=None),
    )
    req = await svc.review_request(seeded["admin"], req.id, approve=True)
    assert req.status == "approved"


async def test_sa_other_company_gets_404(session, seeded):
    """SA review authority is company-scoped — a foreign-company SA gets
    404 on both the decision and the queue (never a cross-tenant leak)."""
    svc = AttendanceService(session)
    req = await svc.create_request(
        seeded["emp_user"],
        **file_kwargs(cat="week_off", leave_type=None, reason=None),
    )
    other_company = Company(
        company_name="Globex", brand_name="Globex", address="9 Far Rd",
        pin_code="90001", email="ops@globex.test", phone_number="555-9999",
    )
    session.add(other_company)
    await session.flush()
    sa_other = User(
        company_id=other_company.id, name="SA Other",
        email="sao@globex.test", username="sao", password_hash="x",
        role=UserRole.SUPER_ADMIN,
    )
    session.add(sa_other)
    await session.commit()
    with pytest.raises(NotFoundErr):
        await svc.review_request(sa_other, req.id, approve=True)
    # and the request is invisible in the foreign company's queue
    items = await svc.list_requests_for_review(sa_other)
    assert all(r.id != req.id for r in items)


async def test_pm_hr_cannot_list_review_queue(session, seeded):
    """GET /requests as PM or HR → 403 — only SA sees the pending queue
    (both the service dispatch and the dedicated review list)."""
    svc = AttendanceService(session)
    await svc.create_request(
        seeded["emp_user"], **file_kwargs(),
    )
    for role_user in (seeded["pm"], seeded["hr"], seeded["pm_other"]):
        with pytest.raises(Forbidden):
            await svc.list_requests(role_user)
        with pytest.raises(Forbidden):
            await svc.list_requests_for_review(role_user)


async def test_review_list_scoping(session, seeded):
    svc = AttendanceService(session)
    req = await svc.create_request(
        seeded["emp_user"],
        **file_kwargs(cat="week_off", leave_type=None, reason=None),
    )
    sa_items = await svc.list_requests_for_review(seeded["admin"])
    assert req.id in [r.id for r in sa_items]
    # the reviewer list also serves SA through GET /requests
    sa_items2 = await svc.list_requests(seeded["admin"])
    assert req.id in [r.id for r in sa_items2]
    # ?date= filters ranges COVERING the date
    covered = await svc.list_requests_for_review(
        seeded["admin"], attendance_date="2999-01-11",
    )
    assert [r.id for r in covered] == [req.id]
    outside = await svc.list_requests_for_review(
        seeded["admin"], attendance_date="2999-01-13",
    )
    assert outside == []


async def test_decided_requests_are_immutable(session, seeded):
    """approved/rejected/cancelled → any further transition is a 409."""
    svc = AttendanceService(session)
    emp = seeded["emp_user"]
    pm = seeded["admin"]  # reviewer is exclusively SUPER_ADMIN

    approved = await svc.create_request(
        emp, **file_kwargs(frm="2999-02-01", to="2999-02-02"),
    )
    await svc.review_request(pm, approved.id, approve=True)
    with pytest.raises(ConflictErr):
        await svc.review_request(pm, approved.id, approve=True)
    with pytest.raises(ConflictErr):
        await svc.review_request(pm, approved.id, approve=False)
    with pytest.raises(ConflictErr):
        await svc.cancel_request(emp, approved.id)

    rejected = await svc.create_request(
        emp, **file_kwargs(frm="2999-03-01", to="2999-03-02"),
    )
    await svc.review_request(pm, rejected.id, approve=False)
    with pytest.raises(ConflictErr):
        await svc.review_request(pm, rejected.id, approve=True)
    with pytest.raises(ConflictErr):
        await svc.review_request(pm, rejected.id, approve=False)
    with pytest.raises(ConflictErr):
        await svc.cancel_request(emp, rejected.id)

    cancelled = await svc.create_request(
        emp, **file_kwargs(frm="2999-04-01", to="2999-04-02"),
    )
    await svc.cancel_request(emp, cancelled.id)
    with pytest.raises(ConflictErr):
        await svc.review_request(pm, cancelled.id, approve=True)
    with pytest.raises(ConflictErr):
        await svc.review_request(pm, cancelled.id, approve=False)
    with pytest.raises(ConflictErr):
        await svc.cancel_request(emp, cancelled.id)


async def test_approved_leave_blocks_start(session, seeded):
    svc = AttendanceService(session)
    today = op_date_today()
    req = await svc.create_request(
        seeded["emp_user"],
        **file_kwargs(frm=today, to=today, leave_type="sick_leave"),
    )
    await svc.review_request(seeded["admin"], req.id, approve=True)
    with pytest.raises(ConflictErr):
        await svc.start(seeded["emp_user"])
    # today reflects the leave day, not 'not_started'
    day, date, request = await svc.today(seeded["emp_user"])
    assert day.status == "leave" and day.started_at is None
    assert request.id == req.id


async def test_approved_week_off_blocks_start(session, seeded):
    svc = AttendanceService(session)
    today = op_date_today()
    req = await svc.create_request(
        seeded["emp_user"],
        **file_kwargs(frm=today, to=today, cat="week_off",
                      leave_type=None, reason=None),
    )
    await svc.review_request(seeded["admin"], req.id, approve=True)
    with pytest.raises(ConflictErr):
        await svc.start(seeded["emp_user"])
    day, _, _ = await svc.today(seeded["emp_user"])
    assert day.status == "week_off" and day.started_at is None


async def test_approve_range_with_present_day_conflicts(session, seeded):
    """A worked day ANYWHERE inside the range aborts the approval —
    the 409 names the offending date."""
    svc = AttendanceService(session)
    today = op_date_today()
    await svc.start(seeded["emp_user"])
    req = await svc.create_request(
        seeded["emp_user"],
        **file_kwargs(frm=today, to="2999-01-20"),
    )
    with pytest.raises(ConflictErr) as err:
        await svc.review_request(seeded["admin"], req.id, approve=True)
    assert today in str(err.value)
    # the request stays pending — reviewer may still reject
    res = await session.execute(
        select(AttendanceRequest).where(AttendanceRequest.id == req.id)
    )
    assert res.scalar_one().status == "pending"
    # and NO day in the range was materialized
    res = await session.execute(
        select(AttendanceDay).where(
            AttendanceDay.employee_id == seeded["employee"].id,
            AttendanceDay.status == "leave",
        )
    )
    assert res.scalars().all() == []


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------

async def test_calendar_returns_days_and_requests(session, seeded):
    svc = AttendanceService(session)
    today = op_date_today()
    month = today[:7]
    await svc.start(seeded["emp_user"])
    await svc.create_request(
        seeded["emp_user"], **file_kwargs(),
    )
    days, requests = await svc.calendar(seeded["emp_user"], month)
    assert [d.attendance_date for d in days] == [today]
    # the far-future request range lives outside this month
    assert all(
        r.from_date <= f"{month}-31" and r.to_date >= f"{month}-01"
        for r in requests
    )
    assert isinstance(requests, list)


async def test_calendar_request_ranges_intersect_month(session, seeded):
    """A range is returned for a LATER month it spills into even though
    it started earlier — the frontend expands covered dates."""
    svc = AttendanceService(session)
    today = op_date_today()
    to = (
        date_type.fromisoformat(today) + timedelta(days=40)
    ).isoformat()
    req = await svc.create_request(
        seeded["emp_user"], **file_kwargs(frm=today, to=to),
    )
    # viewing the month the range ENDS in still returns it
    _days, requests = await svc.calendar(seeded["emp_user"], to[:7])
    assert req.id in [r.id for r in requests]


async def test_calendar_never_fabricates_absent(session, seeded):
    days, requests = await AttendanceService(session).calendar(
        seeded["emp_user"], "2026-02"
    )
    assert days == [] and requests == []


async def test_calendar_month_validation(session, seeded):
    svc = AttendanceService(session)
    for bad in ("2026-1", "26-01", "not", "2026-13"):
        with pytest.raises(ValidationErr):
            await svc.calendar(seeded["emp_user"], bad)


# ---------------------------------------------------------------------------
# Concurrency — get-or-create retry path
# ---------------------------------------------------------------------------

async def test_get_or_create_integrity_race(session, seeded, monkeypatch):
    """Row committed by a competing txn between the lock-select and the
    insert → IntegrityError → savepoint rollback → re-select FOR UPDATE
    returns the winner's row (never a duplicate)."""
    repo = AttendanceRepository(session)
    existing = AttendanceDay(
        property_id=seeded["prop"].id, employee_id=seeded["employee"].id,
        employee_name="Worker One", attendance_date=op_date_today(),
        status="present", started_at=datetime.now(timezone.utc),
    )
    session.add(existing)
    await session.commit()

    original = repo.lock_day
    calls = 0

    async def pretend_race(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return None  # as if the row didn't exist at select time
        return await original(*args, **kwargs)

    # aiosqlite (CPython sqlite3 legacy txn mode) rolls back the whole
    # transaction on IntegrityError, so a real SAVEPOINT can't be exercised
    # here — stub the driver-level failure instead: the insert's flush
    # raises, a no-op "savepoint" swallows nothing, and the retry path
    # must re-select the winner's row.
    class _NullSavepoint:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    real_flush = session.flush
    flushed = False

    async def losing_insert():
        nonlocal flushed
        if not flushed:
            flushed = True
            raise IntegrityError(
                "INSERT INTO attendance_days ...", (),
                Exception("UNIQUE constraint failed"),
            )
        await real_flush()

    monkeypatch.setattr(repo, "lock_day", pretend_race)
    monkeypatch.setattr(session, "begin_nested", lambda: _NullSavepoint())
    monkeypatch.setattr(session, "flush", losing_insert)
    day = await repo.get_or_create_day(
        property_id=seeded["prop"].id, employee_id=seeded["employee"].id,
        employee_name="Worker One", attendance_date=op_date_today(),
        status="present",
    )
    assert day.id == existing.id  # winner's row, no duplicate


# ---------------------------------------------------------------------------
# DB constraints
# ---------------------------------------------------------------------------

@pytest.fixture
async def base_day(session, seeded):
    def _make(**over):
        fields = {
            "property_id": seeded["prop"].id,
            "employee_id": seeded["employee"].id,
            "employee_name": "Worker One",
            "attendance_date": "2026-05-01",
            "status": "present",
        }
        fields.update(over)
        return AttendanceDay(**fields)
    return _make


async def test_check_rejects_invalid_status(session, base_day):
    session.add(base_day(status="bogus"))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_check_leave_day_never_started(session, base_day):
    session.add(base_day(
        status="week_off", started_at=datetime.now(timezone.utc),
    ))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_check_end_needs_start(session, base_day):
    session.add(base_day(
        status="present", ended_at=datetime.now(timezone.utc),
    ))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_check_work_seconds_need_end(session, base_day):
    session.add(base_day(status="present", work_seconds=3600))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_uq_employee_date(session, base_day):
    session.add(base_day())
    await session.flush()
    session.add(base_day())
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_one_open_session_per_employee(session, base_day):
    """uq_attendance_open_session — the concurrent /start backstop."""
    session.add(base_day(
        started_at=datetime.now(timezone.utc),
        attendance_date="2026-05-01",
    ))
    session.add(base_day(
        started_at=datetime.now(timezone.utc),
        attendance_date="2026-05-02",  # different date, same open session
    ))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_one_open_break_per_day(session, seeded):
    day = AttendanceDay(
        property_id=seeded["prop"].id, employee_id=seeded["employee"].id,
        employee_name="Worker One", attendance_date="2026-05-01",
        status="present", started_at=datetime.now(timezone.utc),
    )
    session.add(day)
    await session.flush()
    session.add(AttendanceBreak(attendance_day_id=day.id))
    await session.flush()
    session.add(AttendanceBreak(attendance_day_id=day.id))
    with pytest.raises(IntegrityError):
        await session.flush()


def _request_row(seeded, **over):
    fields = {
        "property_id": seeded["prop"].id,
        "employee_id": seeded["employee"].id,
        "employee_name": "Worker One",
        "from_date": "2026-05-01",
        "to_date": "2026-05-03",
        "request_type": "week_off",
        "leave_type": None,
        "requested_days": 3,
        "status": "pending",
    }
    fields.update(over)
    return AttendanceRequest(**fields)


async def test_check_request_type(session, seeded):
    session.add(_request_row(seeded, request_type="holiday"))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_check_request_range_order(session, seeded):
    session.add(_request_row(
        seeded, from_date="2026-05-03", to_date="2026-05-01",
    ))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_check_leave_type_pairing(session, seeded):
    # leave without a leave_type
    session.add(_request_row(
        seeded, request_type="leave", leave_type=None,
    ))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_check_week_off_rejects_leave_type(session, seeded):
    session.add(_request_row(seeded, leave_type="casual_leave"))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_check_leave_type_vocab(session, seeded):
    session.add(_request_row(
        seeded, request_type="leave", leave_type="sabbatical",
    ))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_check_requested_days_positive(session, seeded):
    session.add(_request_row(seeded, requested_days=0))
    with pytest.raises(IntegrityError):
        await session.flush()


# ---------------------------------------------------------------------------
# Rollover service (reconstructed module)
# ---------------------------------------------------------------------------

async def test_expire_due_abandons_open_instance(session, seeded):
    task = Task(
        property_id=seeded["prop"].id, title="Cleaning", status="in_progress",
        task_type="repetitive",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    session.add(task)
    await session.commit()

    stats = await RolloverService(session).expire_due()
    assert stats["expired"] == 1
    await session.refresh(task)
    assert task.status == "abandoned"
    assert task.abandoned_reason == "NEXT_SCHEDULED_OCCURRENCE"
    assert task.abandoned_from_status == "in_progress"
    assert task.operational_date is not None
    res = await session.execute(
        select(TaskHistoryEvent).where(TaskHistoryEvent.task_id == task.id)
    )
    events = res.scalars().all()
    assert len(events) == 1 and events[0].type == "abandoned"
    # idempotent — a second sweep is a no-op
    assert (await RolloverService(session).expire_due())["expired"] == 0


async def test_expire_due_leaves_submitted_and_open_window(session, seeded):
    submitted = Task(
        property_id=seeded["prop"].id, title="In review",
        status="submitted", task_type="repetitive",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    live = Task(
        property_id=seeded["prop"].id, title="Still valid",
        status="in_progress", task_type="repetitive",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    session.add_all([submitted, live])
    await session.commit()
    stats = await RolloverService(session).expire_due()
    assert stats["expired"] == 0
    for t in (submitted, live):
        await session.refresh(t)
        assert t.status != "abandoned"


async def test_daily_rollover_abandons_past_day(session, seeded):
    yesterday = (
        datetime.now(IST) - timedelta(days=1)
    ).date().isoformat()
    task = Task(
        property_id=seeded["prop"].id, title="Old cleaning",
        status="assigned", due_date=yesterday,
    )
    session.add(task)
    await session.commit()
    stats = await RolloverService(session).run()
    assert stats["abandoned"] >= 1
    await session.refresh(task)
    assert task.status == "abandoned"
    assert task.abandoned_reason == "SYSTEM_DAILY_ROLLOVER"
    assert task.operational_date == yesterday


# ---------------------------------------------------------------------------
# Geo capture — POST /attendance/start|end optional geo body
# ---------------------------------------------------------------------------
from app.models.notifications import LocationEvent  # noqa: E402
from app.schemas.location import GeoCapture  # noqa: E402


async def _location_events(session, source=None):
    q = select(LocationEvent)
    if source:
        q = q.where(LocationEvent.source == source)
    return list((await session.execute(q)).scalars())


async def test_start_with_geo_records_event(session, seeded):
    svc = AttendanceService(session)
    geo = GeoCapture(latitude=12.9716, longitude=77.5946,
                     accuracy_meters=12.0)
    day, _ = await svc.start(seeded["emp_user"], geo=geo)
    events = await _location_events(session, "attendance_start")
    assert len(events) == 1
    ev = events[0]
    assert ev.attendance_day_id == day.id
    assert ev.employee_id == seeded["employee"].id
    assert ev.property_id == seeded["prop"].id
    assert ev.latitude == 12.9716 and ev.accuracy_meters == 12.0
    assert ev.flagged is None  # no geofence configured → never flagged
    assert ev.recorded_at is not None  # server-stamped


async def test_end_with_geo_records_event(session, seeded):
    svc = AttendanceService(session)
    await svc.start(seeded["emp_user"])
    day, _ = await svc.end(
        seeded["emp_user"],
        geo=GeoCapture(latitude=12.97, longitude=77.59),
    )
    events = await _location_events(session, "attendance_end")
    assert len(events) == 1 and events[0].attendance_day_id == day.id


async def test_start_without_geo_records_nothing(session, seeded):
    await AttendanceService(session).start(seeded["emp_user"])
    assert await _location_events(session) == []


async def test_invalid_geo_rejected_before_day_touched(session, seeded):
    svc = AttendanceService(session)
    with pytest.raises(ValidationErr):
        await svc.start(
            seeded["emp_user"],
            geo=GeoCapture(latitude=200.0, longitude=0.0),
        )
    # no half-started day, no event
    day, _, _ = await svc.today(seeded["emp_user"])
    assert day is None
    assert await _location_events(session) == []


async def test_geo_outside_geofence_flagged_not_rejected(session, seeded):
    """Property geofence configured → a far fix records with
    flagged='outside_geofence'; the workday still starts."""
    prop = seeded["prop"]
    prop.latitude, prop.longitude, prop.geofence_radius_m = (
        12.9716, 77.5946, 500,
    )
    await session.commit()
    day, _ = await AttendanceService(session).start(
        seeded["emp_user"],
        geo=GeoCapture(latitude=13.0827, longitude=80.2707),  # ~300 km away
    )
    assert day.started_at is not None  # flagged, never rejected
    events = await _location_events(session, "attendance_start")
    assert events[0].flagged == "outside_geofence"


async def test_geo_inside_geofence_unflagged(session, seeded):
    prop = seeded["prop"]
    prop.latitude, prop.longitude, prop.geofence_radius_m = (
        12.9716, 77.5946, 1000,
    )
    await session.commit()
    await AttendanceService(session).start(
        seeded["emp_user"],
        geo=GeoCapture(latitude=12.9720, longitude=77.5950),
    )
    events = await _location_events(session, "attendance_start")
    assert events[0].flagged is None


async def test_geo_absurd_accuracy_flagged_low_accuracy(session, seeded):
    await AttendanceService(session).start(
        seeded["emp_user"],
        geo=GeoCapture(latitude=12.97, longitude=77.59,
                       accuracy_meters=50000.0),
    )
    events = await _location_events(session, "attendance_start")
    assert events[0].flagged == "low_accuracy"
