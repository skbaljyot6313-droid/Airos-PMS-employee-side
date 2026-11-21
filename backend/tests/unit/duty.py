"""Test helper: put employees on duty for today's operational date.

Allocation only considers employees with an open, started workday and no
open break (`models.attendance.on_duty`). Fixtures that create staff call
`clock_in(session, *employees)` — or `clock_in(session)` for everyone — to
open that state the same way `AttendanceService.start` does.
"""
from datetime import UTC, datetime, time

from sqlalchemy import select

from app.models.attendance import AttendanceDay
from app.models.employee import Employee
from app.services.rollover import current_operational_day


async def clock_in(session, *employees):
    now = datetime.now(UTC)
    op_date = current_operational_day(now, time(6, 0))
    if not employees:
        employees = (await session.execute(select(Employee))).scalars().all()
    for emp in employees:
        existing = await session.scalar(
            select(AttendanceDay.id).where(
                AttendanceDay.employee_id == emp.id,
                AttendanceDay.attendance_date == op_date,
            )
        )
        if existing is None:
            session.add(AttendanceDay(
                property_id=emp.property_id, employee_id=emp.id,
                employee_name=emp.name, attendance_date=op_date,
                status="present", started_at=now,
            ))
    await session.flush()
