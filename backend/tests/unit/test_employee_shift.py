"""My Shift — GET /attendance/shift service resolution.

Service-level suite (same convention as test_attendance.py): the HTTP
layer is thin routing over resolve_my_shift + my_shift_out. Covers
assignment-in-force rules, inactive/expired/future windows, overnight
and working-day flags, and own-employee scoping.
"""
from datetime import date, datetime, time, timedelta, timezone

import pytest

from app.dependencies.auth import Forbidden
from app.models.employee import Employee
from app.models.shift import EmployeeShiftAssignment, Shift
from app.models.user import User, UserRole
from app.schemas.attendance import my_shift_out
from app.services.employee_shift import resolve_my_shift, shift_applies_on
from app.services.rollover import current_operational_day


def op_today() -> str:
    """Seed company's op-day (default 06:00 start)."""
    return current_operational_day(datetime.now(timezone.utc), time(6, 0))


def d(offset: int) -> str:
    return (date.fromisoformat(op_today()) + timedelta(days=offset)).isoformat()


async def make_shift(session, prop, company, **over) -> Shift:
    fields = {
        "name": "Day Shift", "start_time": time(9, 0),
        "end_time": time(18, 0), **over,
    }
    s = Shift(company_id=company.id, property_id=prop.id, **fields)
    session.add(s)
    await session.flush()
    return s


def assign(session, employee, shift, frm, until=None):
    a = EmployeeShiftAssignment(
        employee_id=employee.id, shift_id=shift.id,
        effective_from=frm, effective_until=until,
    )
    session.add(a)
    return a


async def my_shift(user, session):
    a, s, op_date = await resolve_my_shift(user, session)
    return my_shift_out(
        a, s, op_date=op_date,
        is_working_today=(
            shift_applies_on(s.working_days, op_date) if s else False
        ),
    )


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_assignment_returns_not_assigned(session, seed):
    out = await my_shift(seed["emp_user"], session)
    assert out["status"] == "not_assigned"
    assert out["shift"] is None
    assert out["date"] == op_today()
    assert out["timezone"] == "Asia/Kolkata"


@pytest.mark.asyncio
async def test_active_assignment_returns_scheduled(session, seed):
    s = await make_shift(
        session, seed["prop"], seed["company"],
        name="Morning", start_time=time(9, 0), end_time=time(18, 0),
        working_days="1111110",
    )
    assign(session, seed["employee"], s, frm=d(-30))
    await session.commit()

    out = await my_shift(seed["emp_user"], session)
    assert out["status"] == "scheduled"
    sh = out["shift"]
    assert sh["shift_name"] == "Morning"
    assert sh["start_time"] == "09:00"
    assert sh["end_time"] == "18:00"
    assert sh["overnight"] is False
    assert sh["working_days"] == "1111110"
    assert sh["effective_from"] == d(-30)
    assert sh["effective_until"] is None
    # Sunday is '0' in '1111110' — flag must track today's weekday.
    today_weekday = date.fromisoformat(op_today()).weekday()
    assert sh["is_working_today"] == (today_weekday != 6)


@pytest.mark.asyncio
async def test_inactive_shift_definition_reports_inactive(session, seed):
    s = await make_shift(session, seed["prop"], seed["company"], is_active=False)
    assign(session, seed["employee"], s, frm=d(-7))
    await session.commit()
    out = await my_shift(seed["emp_user"], session)
    assert out["status"] == "inactive"
    assert out["shift"]["shift_name"] == "Day Shift"


@pytest.mark.asyncio
async def test_expired_assignment_returns_not_assigned(session, seed):
    s = await make_shift(session, seed["prop"], seed["company"])
    assign(session, seed["employee"], s, frm=d(-60), until=d(-1))
    await session.commit()
    out = await my_shift(seed["emp_user"], session)
    assert out["status"] == "not_assigned"
    assert out["shift"] is None


@pytest.mark.asyncio
async def test_future_assignment_returns_not_assigned(session, seed):
    s = await make_shift(session, seed["prop"], seed["company"])
    assign(session, seed["employee"], s, frm=d(+1))
    await session.commit()
    out = await my_shift(seed["emp_user"], session)
    assert out["status"] == "not_assigned"
    assert out["shift"] is None


@pytest.mark.asyncio
async def test_latest_effective_from_wins(session, seed):
    """Two in-force rows (data drift) — latest effective_from applies,
    matching the SA resolution order."""
    old = await make_shift(session, seed["prop"], seed["company"], name="Old")
    new = await make_shift(session, seed["prop"], seed["company"], name="New")
    assign(session, seed["employee"], old, frm=d(-60))
    assign(session, seed["employee"], new, frm=d(-10))
    await session.commit()
    out = await my_shift(seed["emp_user"], session)
    assert out["status"] == "scheduled"
    assert out["shift"]["shift_name"] == "New"
    assert out["shift"]["effective_from"] == d(-10)


@pytest.mark.asyncio
async def test_overnight_flag_and_window(session, seed):
    s = await make_shift(
        session, seed["prop"], seed["company"],
        name="Night", start_time=time(22, 0), end_time=time(6, 0),
    )
    assign(session, seed["employee"], s, frm=d(-3))
    await session.commit()
    out = await my_shift(seed["emp_user"], session)
    assert out["shift"]["overnight"] is True
    assert out["shift"]["start_time"] == "22:00"
    assert out["shift"]["end_time"] == "06:00"


@pytest.mark.asyncio
async def test_not_working_today_flag(session, seed):
    """Shift bitmap excludes today's weekday — still scheduled, but
    is_working_today is False."""
    bitmap = list("1111111")
    bitmap[date.fromisoformat(op_today()).weekday()] = "0"
    if "1" not in bitmap:
        bitmap[(date.fromisoformat(op_today()).weekday() + 1) % 7] = "1"
    s = await make_shift(
        session, seed["prop"], seed["company"],
        working_days="".join(bitmap),
    )
    assign(session, seed["employee"], s, frm=d(-5))
    await session.commit()
    out = await my_shift(seed["emp_user"], session)
    assert out["status"] == "scheduled"
    assert out["shift"]["is_working_today"] is False


@pytest.mark.asyncio
async def test_employee_without_link_forbidden(session, seed):
    """emp_user2 has no employee_id — same 403 as the rest of attendance."""
    with pytest.raises(Forbidden):
        await resolve_my_shift(seed["emp_user2"], session)


@pytest.mark.asyncio
async def test_other_employees_assignment_never_leaks(session, seed):
    """emp2 is assigned; the caller's own (empty) schedule is returned —
    the wire never carries someone else's shift."""
    employee2 = Employee(
        company_id=seed["company"].id, property_id=seed["prop"].id,
        name="Worker Two", email="w2@acme.test", status="active",
    )
    session.add(employee2)
    await session.flush()
    s = await make_shift(session, seed["prop"], seed["company"])
    assign(session, employee2, s, frm=d(-10))
    await session.commit()
    out = await my_shift(seed["emp_user"], session)
    assert out["status"] == "not_assigned"
    assert out["shift"] is None


@pytest.mark.asyncio
async def test_boundary_dates_inclusive(session, seed):
    """effective_from == today and effective_until == today both count."""
    s = await make_shift(session, seed["prop"], seed["company"])
    assign(session, seed["employee"], s, frm=d(0), until=d(0))
    await session.commit()
    out = await my_shift(seed["emp_user"], session)
    assert out["status"] == "scheduled"
    assert out["shift"]["effective_until"] == d(0)
