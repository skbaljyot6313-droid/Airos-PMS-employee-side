"""Availability-driven allocation — who may receive pending work, and when
pending work reaches them (Start Day / End Break)."""
import pytest
from sqlalchemy import func, select

from app.models.maintenance import MaintenanceTicket
from app.models.structure import Zone
from app.models.task import Task
from app.models.work_allocation import WorkAllocationBatch
from app.services.attendance import AttendanceService
from app.services.availability import AvailabilityService, _EmployeeUnavailable
from app.services.structure import ValidationErr
from app.services.work_allocation import WorkAllocationService
from duty import clock_in


@pytest.fixture
async def zoned(session, seed):
    """Worker One is a Housekeeping employee in Zone A."""
    zone = Zone(property_id=seed["prop"].id, name="Zone A", code="ZA", floor="F1")
    session.add(zone)
    await session.flush()
    emp = seed["employee"]
    emp.zone_id = zone.id
    emp.department = "Housekeeping"
    await session.commit()
    return zone


def _pending(session, seed, zone, *, title="Clean room", work_type="cleaning"):
    task = Task(property_id=seed["prop"].id, zone_id=zone.id, title=title,
                status="pending", work_type=work_type)
    session.add(task)
    return task


async def _refresh(session, *objs):
    for obj in objs:
        await session.refresh(obj)


async def _eligible_ids(session, seed, zone):
    pool, _ = await WorkAllocationService(session).eligible_employees(
        seed["prop"].id, zone.id, departments=("housekeeping",))
    return {e.id for e in pool}


async def test_start_day_assigns_pending_zone_work(session, seed, zoned):
    t1 = _pending(session, seed, zoned, title="Room 101")
    t2 = _pending(session, seed, zoned, title="Room 102")
    await session.commit()

    await AttendanceService(session).start(seed["emp_user"])

    await _refresh(session, t1, t2)
    for task in (t1, t2):
        assert task.employee_id == seed["employee"].id
        assert task.status == "assigned"
        assert task.allocation_status == "auto_assigned"
        assert task.allocation_batch_id is not None


async def test_absent_employee_receives_no_pending_work(session, seed, zoned):
    task = _pending(session, seed, zoned)
    await session.commit()

    assert await AvailabilityService(session).sweep_on_duty(seed["employee"].id) == 0
    await _refresh(session, task)
    assert task.employee_id is None and task.status == "pending"


async def test_on_break_gets_no_new_work_and_resume_allocates(session, seed, zoned):
    svc = AttendanceService(session)
    await svc.start(seed["emp_user"])
    await svc.start_break(seed["emp_user"])
    task = _pending(session, seed, zoned)
    await session.commit()

    assert seed["employee"].id not in await _eligible_ids(session, seed, zoned)
    assert await AvailabilityService(session).sweep_on_duty(seed["employee"].id) == 0
    await _refresh(session, task)
    assert task.employee_id is None

    await svc.resume(seed["emp_user"])
    await _refresh(session, task)
    assert task.employee_id == seed["employee"].id and task.status == "assigned"


async def test_ended_day_receives_no_work(session, seed, zoned):
    svc = AttendanceService(session)
    await svc.start(seed["emp_user"])
    await svc.end(seed["emp_user"])
    task = _pending(session, seed, zoned)
    await session.commit()

    assert seed["employee"].id not in await _eligible_ids(session, seed, zoned)
    assert await AvailabilityService(session).sweep_on_duty(seed["employee"].id) == 0
    await _refresh(session, task)
    assert task.employee_id is None


async def test_multiple_breaks_gate_and_release_each_time(session, seed, zoned):
    svc = AttendanceService(session)
    await svc.start(seed["emp_user"])
    for _ in range(2):
        await svc.start_break(seed["emp_user"])
        assert seed["employee"].id not in await _eligible_ids(session, seed, zoned)
        await svc.resume(seed["emp_user"])
        assert seed["employee"].id in await _eligible_ids(session, seed, zoned)


async def test_zone_restriction_respected(session, seed, zoned):
    other = Zone(property_id=seed["prop"].id, name="Zone B", code="ZB", floor="F2")
    session.add(other)
    await session.flush()
    task = _pending(session, seed, other)
    await session.commit()

    await AttendanceService(session).start(seed["emp_user"])
    await _refresh(session, task)
    assert task.employee_id is None


async def test_department_gating_respected(session, seed, zoned):
    task = _pending(session, seed, zoned, title="Fix geyser", work_type="maintenance")
    await session.commit()

    await AttendanceService(session).start(seed["emp_user"])
    await _refresh(session, task)
    assert task.employee_id is None


async def test_maintenance_ticket_assigned_when_employee_starts(session, seed, zoned):
    ticket = MaintenanceTicket(
        ticket_number="MT-T-00001", company_id=seed["company"].id,
        property_id=seed["prop"].id, zone_id=zoned.id,
        maintenance_type="plumbing", issue="Leak", priority="medium",
        status="open", allocation_status="unassigned",
    )
    session.add(ticket)
    seed["employee"].department = "Maintenance & Engineering"
    await session.commit()

    await AttendanceService(session).start(seed["emp_user"])
    await _refresh(session, ticket)
    assert ticket.assigned_to == seed["employee"].id
    assert ticket.status == "assigned"


async def test_sweep_is_idempotent(session, seed, zoned):
    task = _pending(session, seed, zoned)
    await session.commit()
    await AttendanceService(session).start(seed["emp_user"])

    assert await AvailabilityService(session).sweep_on_duty(seed["employee"].id) == 0
    await _refresh(session, task)
    assert task.employee_id == seed["employee"].id


async def test_explicit_assignment_requires_on_duty(session, seed, zoned):
    svc = WorkAllocationService(session)
    with pytest.raises(ValidationErr, match="not on duty"):
        await svc.employee_for_assignment(
            seed["employee"].id, seed["prop"].id, work_type="cleaning")

    await AttendanceService(session).start(seed["emp_user"])
    emp = await svc.employee_for_assignment(
        seed["employee"].id, seed["prop"].id, work_type="cleaning")
    assert emp.id == seed["employee"].id


async def test_confirm_on_duty_rejects_ended_employee(session, seed, zoned):
    svc = AttendanceService(session)
    await svc.start(seed["emp_user"])
    await svc.end(seed["emp_user"])
    with pytest.raises(_EmployeeUnavailable):
        await AvailabilityService(session).confirm_on_duty(seed["employee"])


async def test_stale_pool_lost_race_rolls_back_batch(session, seed, zoned, monkeypatch):
    """Pool was read while on duty; the employee ends the day before the
    write. Nothing is assigned and the allocation batch is rolled back."""
    task = _pending(session, seed, zoned)
    await session.commit()
    await clock_in(session, seed["employee"])
    await AttendanceService(session).end(seed["emp_user"])

    async def stale_pool(self, *args, **kwargs):
        return [seed["employee"]], "zone"

    monkeypatch.setattr(WorkAllocationService, "eligible_employees", stale_pool)
    assigned = await AvailabilityService(session)._take(
        seed["employee"], seed["prop"], task, kind="task",
        work_type="cleaning", actor_name=None)
    assert assigned is False
    await _refresh(session, task)
    assert task.employee_id is None
    assert await session.scalar(select(func.count()).select_from(WorkAllocationBatch)) == 0


async def test_sweep_failure_does_not_fail_start(session, seed, zoned, monkeypatch):
    task = _pending(session, seed, zoned)
    await session.commit()

    async def boom(self, *args, **kwargs):
        raise RuntimeError("sweep exploded")

    monkeypatch.setattr(AvailabilityService, "_take", boom)
    day, _ = await AttendanceService(session).start(seed["emp_user"])
    assert day.started_at is not None
    await _refresh(session, task)
    assert task.employee_id is None and task.status == "pending"
