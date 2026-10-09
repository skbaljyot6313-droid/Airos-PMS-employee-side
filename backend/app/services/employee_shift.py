"""Employee 'My Shift' — read-only resolution of the caller's current
shift assignment for the profile screen.

Reads the shared shifts/employee_shift_assignments tables written by the
Super Admin backend. Resolution mirrors the SA scheduling authority
(services/shifts.py:effective_assignments) exactly: the assignment in
force on today's IST operational day — effective_from <= op_date and
(effective_until IS NULL or effective_until >= op_date), latest
effective_from wins (overlap validation keeps at most one anyway).

The employee scope comes from user.employee_id — never from request
input, so another employee's shift is unreachable through this path.
Times stay IST wall-clock 'HH:MM' — the UI renders them verbatim; a
device timezone conversion would silently shift the displayed window.
"""

import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import bindparam
from sqlalchemy.types import Uuid

from app.models.company import Company
from app.models.employee import Employee
from app.models.property import Property
from app.models.shift import EmployeeShiftAssignment, Shift
from app.models.user import User
from app.services.rollover import operational_day_key, parse_day_start

IST = ZoneInfo("Asia/Kolkata")


def shift_applies_on(working_days: str, op_date: str) -> bool:
    """True when the shift's Monday-first bitmap covers `op_date`'s
    weekday — same rule as the SA backend."""
    try:
        weekday = date.fromisoformat(op_date).weekday()  # Mon=0
    except ValueError:
        return False
    return len(working_days) == 7 and working_days[weekday] == "1"


async def resolve_my_shift(
    user: User, session: AsyncSession
) -> tuple[EmployeeShiftAssignment | None, Shift | None, str]:
    """(assignment, shift, op_date) — the pair in force today, or
    (None, None, op_date) when the caller has no current assignment."""
    from app.dependencies.auth import Forbidden

    if user.employee_id is None:
        raise Forbidden(
            "Your account is not linked to an employee record."
        )
    prop_param = bindparam("caller_prop", user.property_id, type_=Uuid)
    res = await session.execute(
        select(Employee, Company.operational_day_start)
        .select_from(Employee)
        .join(
            Property,
            Property.id
            == func.coalesce(prop_param, Employee.property_id),
        )
        .join(Company, Company.id == Property.company_id)
        .where(Employee.id == user.employee_id)
    )
    row = res.first()
    if row is None:
        raise Forbidden(
            "Your account is not linked to an employee record."
        )
    _employee, day_start = row
    op_date = operational_day_key(
        datetime.now(IST), parse_day_start(day_start)
    )

    res = await session.execute(
        select(EmployeeShiftAssignment, Shift)
        .join(Shift, EmployeeShiftAssignment.shift_id == Shift.id)
        .where(
            EmployeeShiftAssignment.employee_id == user.employee_id,
            EmployeeShiftAssignment.effective_from <= op_date,
            (EmployeeShiftAssignment.effective_until.is_(None))
            | (EmployeeShiftAssignment.effective_until >= op_date),
        )
        .order_by(
            EmployeeShiftAssignment.effective_from.desc(),
            EmployeeShiftAssignment.created_at.desc(),
        )
    )
    pair = res.first()
    if pair is None:
        return None, None, op_date
    return pair[0], pair[1], op_date
