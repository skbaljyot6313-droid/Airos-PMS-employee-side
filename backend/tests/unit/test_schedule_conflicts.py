"""Shared schedule rules + unified-allocation metadata (EB side).

``app.domain.schedule_conflicts`` is byte-identical with the Super Admin
copy — these tests pin the shared semantics on the employee side, plus the
``created_by_role`` stamp, the reschedule notification and the
server-computed ``is_overdue`` flag the mobile calendar renders.
"""
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.api.v1.team import (
    TeamWorkIn, TeamWorkPatch, allocate_work, update_work,
)
from app.domain.schedule_conflicts import (
    IST,
    assignment_conflicts,
    is_overdue,
    parse_dt,
    scheduled_end,
    task_day,
    task_window,
)
from app.models.department import Department
from app.models.employee import Employee
from app.models.notifications import Notification
from app.models.task import Task
from app.models.user import User, UserRole


async def _fixture(session, seed):
    dept = Department(
        id=uuid.uuid4(), company_id=seed["company"].id,
        property_id=seed["prop"].id, name="Housekeeping",
        status="active")
    emp = seed["employee"]
    emp.department_id = dept.id
    dept.head_employee_id = emp.id
    session.add(dept)
    mgr = User(
        id=uuid.uuid4(), company_id=seed["company"].id,
        property_id=seed["prop"].id, employee_id=emp.id,
        email="mgr@test", username="mgr", name="Mgr", password_hash="x",
        role=UserRole.DEPARTMENT_MANAGER, is_active=True)
    worker = Employee(
        id=uuid.uuid4(), company_id=seed["company"].id,
        property_id=seed["prop"].id,
        name="Worker", email="w@test", department_id=dept.id,
        status="active")
    session.add_all([mgr, worker])
    await session.commit()
    return dept, mgr, worker


# --- shared rule parity -----------------------------------------------------

def test_window_day_and_overnight_end():
    t = Task(
        id=uuid.uuid4(), property_id=uuid.uuid4(), title="x",
        status="assigned", task_type="fixed",
        due_date="2026-11-25", start_time="22:00", end_time="02:00")
    assert task_window(t) == (22 * 60, 120)
    assert task_day(t) == "2026-11-25"
    end = scheduled_end(t)
    assert end is not None and end.date().isoformat() == "2026-11-26"


def test_is_overdue_terminal_states_and_parse_dt():
    for status in ("completed", "cancelled", "submitted", "abandoned"):
        t = Task(id=uuid.uuid4(), property_id=uuid.uuid4(), title="x",
                 status=status, task_type="fixed", due_date="2026-11-20",
                 start_time="09:00", end_time="10:00")
        assert not is_overdue(t, now=datetime(2026, 11, 21, tzinfo=IST))
    dt = parse_dt("2026-11-25T09:00:00")
    assert dt is not None and (dt.hour, dt.minute) == (3, 30)  # IST→UTC


@pytest.mark.asyncio
async def test_assignment_conflicts_same_contract(session, seed):
    dept, mgr, worker = await _fixture(session, seed)
    session.add(Task(
        id=uuid.uuid4(), property_id=seed["prop"].id, title="Shift A",
        status="assigned", task_type="fixed", employee_id=worker.id,
        due_date="2026-11-25", start_time="09:00", end_time="13:00"))
    await session.commit()
    conflicts = await assignment_conflicts(
        session, {worker.id: worker},
        target_day="2026-11-25", start=12 * 60, end=18 * 60,
        title="Other", property_id=seed["prop"].id)
    assert conflicts[0]["kind"] == "overlap"
    assert conflicts[0]["employee_uid"] == str(worker.id)


# --- unified-allocation metadata --------------------------------------------

@pytest.mark.asyncio
async def test_allocate_stamps_created_by_role(session, seed):
    dept, mgr, worker = await _fixture(session, seed)
    res = await allocate_work(
        TeamWorkIn(title="Stamped", due_date="2026-11-25",
                   employee_uids=[worker.id]),
        department_id=str(dept.id), user=mgr, session=session)
    assert res["items"][0]["created_by_role"] == "department_manager"


@pytest.mark.asyncio
async def test_reschedule_writes_notification_and_is_overdue(session, seed):
    dept, mgr, worker = await _fixture(session, seed)
    res = await allocate_work(
        TeamWorkIn(title="Move me", due_date="2026-11-25",
                   start_time="09:00", end_time="12:00",
                   employee_uids=[worker.id]),
        department_id=str(dept.id), user=mgr, session=session)
    task_id = res["items"][0]["task_uid"]

    await update_work(
        uuid.UUID(task_id), TeamWorkPatch(end_time="15:00"),
        user=mgr, session=session)
    notes = (await session.execute(
        select(Notification).where(
            Notification.task_id == uuid.UUID(task_id),
            Notification.type == "task_rescheduled",
        ))).scalars().all()
    assert len(notes) == 1
    assert notes[0].employee_id == worker.id

    # Server-computed overdue — a past window surfaces on the serializer.
    past = (await session.execute(
        select(Task).where(Task.id == uuid.UUID(task_id)))).scalar_one()
    past.due_date = "2020-01-01"
    past.start_time, past.end_time = "09:00", "10:00"
    await session.commit()
    assert is_overdue(past)
    from app.schemas.workspace import task_out
    assert task_out(past)["is_overdue"] is True
