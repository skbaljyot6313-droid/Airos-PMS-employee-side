"""End Day handover — what happens to an employee's open work when they end
their day, and what does NOT happen on break."""
import pytest
from sqlalchemy import select

from app.models.audit import AuditEvent
from app.models.employee import Employee
from app.models.maintenance import MaintenanceTicket
from app.models.structure import Zone
from app.models.task import Task
from app.models.work_allocation import WorkAllocationHistory
from app.services.attendance import AttendanceService
from app.services.reassignment import ReassignmentService
from app.services.availability import AvailabilityService
from duty import clock_in


@pytest.fixture
async def ctx(session, seed):
    zone_a = Zone(property_id=seed["prop"].id, name="Zone A", code="ZA", floor="F1")
    zone_b = Zone(property_id=seed["prop"].id, name="Zone B", code="ZB", floor="F2")
    session.add_all([zone_a, zone_b])
    await session.flush()
    ender = seed["employee"]
    ender.zone_id = zone_a.id
    ender.department = "Housekeeping"
    colleague = Employee(
        company_id=seed["company"].id, property_id=seed["prop"].id,
        name="Colleague", email="colleague@acme.test", status="active",
        zone_id=zone_a.id, department="Housekeeping",
    )
    session.add(colleague)
    await session.commit()
    return {"zone_a": zone_a, "zone_b": zone_b, "ender": ender, "colleague": colleague}


def _task(session, seed, zone, employee=None, *, status="assigned", title="Room"):
    t = Task(property_id=seed["prop"].id, zone_id=zone.id, title=title,
             status=status, work_type="cleaning",
             employee_id=employee.id if employee else None,
             assigned_to_name=employee.name if employee else None,
             allocation_status="manually_assigned" if employee else "unassigned")
    session.add(t)
    return t


async def _refresh(session, *objs):
    for obj in objs:
        await session.refresh(obj)


async def test_assigned_task_moves_to_on_duty_colleague_on_end_day(session, seed, ctx):
    await clock_in(session, ctx["colleague"])
    await AttendanceService(session).start(seed["emp_user"])
    task = _task(session, seed, ctx["zone_a"], ctx["ender"])
    await session.commit()

    await AttendanceService(session).end(seed["emp_user"])

    await _refresh(session, task)
    assert task.employee_id == ctx["colleague"].id
    assert task.status == "assigned"
    history = (await session.execute(
        select(WorkAllocationHistory).where(WorkAllocationHistory.ticket_id == task.id)
    )).scalars().all()
    assert history and history[-1].previous_employee_id == ctx["ender"].id
    assert history[-1].allocation_method == "end_of_day_reassign"
    assert history[-1].reason == "employee_ended_day"
    audit = (await session.execute(
        select(AuditEvent).where(AuditEvent.action == "attendance_ended")
    )).scalars().one()
    assert len(audit.detail["handover"]["reassigned"]) == 1


async def test_in_progress_and_submitted_work_is_preserved(session, seed, ctx):
    await clock_in(session, ctx["colleague"])
    await AttendanceService(session).start(seed["emp_user"])
    busy = _task(session, seed, ctx["zone_a"], ctx["ender"], status="in_progress", title="Busy")
    review = _task(session, seed, ctx["zone_a"], ctx["ender"], status="submitted", title="Review")
    await session.commit()

    await AttendanceService(session).end(seed["emp_user"])

    await _refresh(session, busy, review)
    assert busy.employee_id == ctx["ender"].id and busy.status == "in_progress"
    assert review.employee_id == ctx["ender"].id and review.status == "submitted"


async def test_completed_work_is_untouched(session, seed, ctx):
    await clock_in(session, ctx["colleague"])
    await AttendanceService(session).start(seed["emp_user"])
    done = _task(session, seed, ctx["zone_a"], ctx["ender"], status="completed", title="Done")
    await session.commit()

    await AttendanceService(session).end(seed["emp_user"])
    await _refresh(session, done)
    assert done.employee_id == ctx["ender"].id and done.status == "completed"


async def test_no_replacement_returns_work_to_pool_and_sweep_picks_it_up(session, seed, ctx):
    await AttendanceService(session).start(seed["emp_user"])
    task = _task(session, seed, ctx["zone_a"], ctx["ender"])
    await session.commit()

    await AttendanceService(session).end(seed["emp_user"])
    await _refresh(session, task)
    assert task.employee_id is None
    assert task.status == "pending"
    assert task.allocation_status == "unassigned"

    await clock_in(session, ctx["colleague"])
    await AvailabilityService(session).sweep_on_duty(ctx["colleague"].id)
    await _refresh(session, task)
    assert task.employee_id == ctx["colleague"].id and task.status == "assigned"


async def test_replacement_must_be_zone_eligible(session, seed, ctx):
    other = Employee(
        company_id=seed["company"].id, property_id=seed["prop"].id,
        name="Elsewhere", email="elsewhere@acme.test", status="active",
        zone_id=ctx["zone_b"].id, department="Housekeeping",
    )
    session.add(other)
    await session.commit()
    await clock_in(session, other)
    await AttendanceService(session).start(seed["emp_user"])
    task = _task(session, seed, ctx["zone_a"], ctx["ender"])
    await session.commit()

    await AttendanceService(session).end(seed["emp_user"])
    await _refresh(session, task)
    assert task.employee_id is None and task.status == "pending"


async def test_break_does_not_reassign_existing_work(session, seed, ctx):
    await clock_in(session, ctx["colleague"])
    svc = AttendanceService(session)
    await svc.start(seed["emp_user"])
    task = _task(session, seed, ctx["zone_a"], ctx["ender"])
    await session.commit()

    await svc.start_break(seed["emp_user"])
    await _refresh(session, task)
    assert task.employee_id == ctx["ender"].id and task.status == "assigned"


async def test_tickets_reassigned_then_released_when_nobody_eligible(session, seed, ctx):
    ctx["colleague"].department = "Maintenance & Engineering"
    await clock_in(session, ctx["colleague"])
    await AttendanceService(session).start(seed["emp_user"])
    ticket = MaintenanceTicket(
        ticket_number="MT-R-00001", company_id=seed["company"].id,
        property_id=seed["prop"].id, zone_id=ctx["zone_a"].id,
        maintenance_type="plumbing", issue="Leak", priority="medium",
        status="assigned", assigned_to=ctx["ender"].id,
        assigned_to_name=ctx["ender"].name, allocation_status="manually_assigned",
    )
    session.add(ticket)
    await session.commit()

    await AttendanceService(session).end(seed["emp_user"])
    await _refresh(session, ticket)
    assert ticket.assigned_to == ctx["colleague"].id and ticket.status == "assigned"


async def test_ticket_released_to_open_without_eligible_maintenance_staff(session, seed, ctx):
    await AttendanceService(session).start(seed["emp_user"])
    ticket = MaintenanceTicket(
        ticket_number="MT-R-00002", company_id=seed["company"].id,
        property_id=seed["prop"].id, zone_id=ctx["zone_a"].id,
        maintenance_type="plumbing", issue="Leak", priority="medium",
        status="assigned", assigned_to=ctx["ender"].id,
        assigned_to_name=ctx["ender"].name, allocation_status="manually_assigned",
    )
    session.add(ticket)
    await session.commit()

    await AttendanceService(session).end(seed["emp_user"])
    await _refresh(session, ticket)
    assert ticket.assigned_to is None
    assert ticket.status == "open"
    assert ticket.allocation_status == "unassigned"


async def test_failed_item_is_preserved_and_end_day_still_succeeds(session, seed, ctx, monkeypatch):
    await clock_in(session, ctx["colleague"])
    await AttendanceService(session).start(seed["emp_user"])
    good = _task(session, seed, ctx["zone_a"], ctx["ender"], title="Good")
    bad = _task(session, seed, ctx["zone_a"], ctx["ender"], title="BAD")
    await session.commit()

    original = ReassignmentService._move

    async def flaky(self, emp, prop, item, kind, actor_name):
        if item.title == "BAD":
            raise RuntimeError("simulated allocator failure")
        return await original(self, emp, prop, item, kind, actor_name)

    monkeypatch.setattr(ReassignmentService, "_move", flaky)
    day, _ = await AttendanceService(session).end(seed["emp_user"])

    assert day.ended_at is not None
    await _refresh(session, good, bad)
    assert good.employee_id == ctx["colleague"].id
    assert bad.employee_id == ctx["ender"].id and bad.status == "assigned"
    audit = (await session.execute(
        select(AuditEvent).where(AuditEvent.action == "attendance_ended")
    )).scalars().one()
    assert [f["id"] for f in audit.detail["handover"]["failed"]] == [str(bad.id)]
