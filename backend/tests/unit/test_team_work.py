"""Department-manager team work — scope, conflicts, schedule windows."""
import uuid

import pytest
from sqlalchemy import select

from app.api.v1.team import (
    ReassignIn, TeamWorkIn, TeamWorkPatch,
    _Forbidden, _ScheduleConflict,
    allocate_work, cancel_work, reassign_work, team_overview, team_work,
    update_work,
)
from app.models.department import Department
from app.models.employee import Employee
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


@pytest.mark.asyncio
async def test_allocate_creates_real_task_with_schedule(session, seed):
    dept, mgr, worker = await _fixture(session, seed)
    res = await allocate_work(
        TeamWorkIn(
            title="Deep clean lobby", due_date="2026-11-25",
            start_time="09:00", end_time="17:00",
            break_start_time="13:00", break_end_time="14:00",
            estimated_minutes=420, priority="high",
            employee_uids=[worker.id]),
        department_id=str(dept.id), user=mgr, session=session)
    task = res["items"][0]
    assert task["department_id"] == str(dept.id)
    assert task["department_name"] == "Housekeeping"
    assert task["start_time"] == "09:00" and task["end_time"] == "17:00"
    assert task["break_start_time"] == "13:00"
    assert task["estimated_minutes"] == 420
    assert task["status"] == "assigned"
    note = (await session.execute(
        select(Task).where(Task.id == uuid.UUID(task["task_uid"]))
    )).scalar_one()
    assert note.employee_id == worker.id


@pytest.mark.asyncio
async def test_overlap_conflict_blocks_then_allows(session, seed):
    dept, mgr, worker = await _fixture(session, seed)
    payload = dict(
        title="Shift A", due_date="2026-11-25",
        start_time="09:00", end_time="13:00", employee_uids=[worker.id])
    await allocate_work(TeamWorkIn(**payload),
                        department_id=str(dept.id), user=mgr, session=session)
    with pytest.raises(_ScheduleConflict) as e:
        await allocate_work(
            TeamWorkIn(**{**payload, "title": "Shift B",
                          "start_time": "12:00", "end_time": "18:00"}),
            department_id=str(dept.id), user=mgr, session=session)
    conflicts = e.value.details["conflicts"]
    assert conflicts[0]["kind"] == "overlap"
    # Explicit override proceeds
    res = await allocate_work(
        TeamWorkIn(**{**payload, "title": "Shift B", "start_time": "12:00",
                      "end_time": "18:00", "allow_conflicts": True}),
        department_id=str(dept.id), user=mgr, session=session)
    assert len(res["items"]) == 1


@pytest.mark.asyncio
async def test_duplicate_title_same_day_conflicts(session, seed):
    dept, mgr, worker = await _fixture(session, seed)
    payload = dict(title="Same job", due_date="2026-11-25",
                   start_time="09:00", end_time="10:00",
                   employee_uids=[worker.id])
    await allocate_work(TeamWorkIn(**payload),
                        department_id=str(dept.id), user=mgr, session=session)
    with pytest.raises(_ScheduleConflict) as e:
        await allocate_work(
            TeamWorkIn(**{**payload, "start_time": "20:00",
                          "end_time": "22:00"}),
            department_id=str(dept.id), user=mgr, session=session)
    assert e.value.details["conflicts"][0]["kind"] == "duplicate"


@pytest.mark.asyncio
async def test_multi_employee_batch_and_team_scope(session, seed):
    dept, mgr, worker = await _fixture(session, seed)
    other = Employee(id=uuid.uuid4(), company_id=seed["company"].id,
                     property_id=seed["prop"].id,
                     name="Outsider", email="o@test", status="active")
    session.add(other)
    await session.commit()
    res = await allocate_work(
        TeamWorkIn(title="Team shift", due_date="2026-11-26",
                   employee_uids=[worker.id, worker.id]),
        department_id=str(dept.id), user=mgr, session=session)
    assert len(res["items"]) == 1  # dedupe
    # Outsider (not in dept) is rejected
    with pytest.raises(_Forbidden):
        await allocate_work(
            TeamWorkIn(title="Bad", employee_uids=[other.id]),
            department_id=str(dept.id), user=mgr, session=session)
    # Non-manager is rejected at the scope gate
    plain = User(id=uuid.uuid4(), company_id=seed["company"].id,
                 property_id=seed["prop"].id,
                 employee_id=other.id, email="p@test", username="plain", name="P",
                 password_hash="x", role=UserRole.EMPLOYEE, is_active=True)
    with pytest.raises(_Forbidden):
        await team_overview(user=plain, session=session)
    overview = await team_overview(user=mgr, session=session)
    assert overview["items"][0]["department_uid"] == str(dept.id)
    assert any(e["employee_uid"] == str(worker.id)
               for e in overview["items"][0]["employees"])


@pytest.mark.asyncio
async def test_edit_reschedule_and_cancel(session, seed):
    dept, mgr, worker = await _fixture(session, seed)
    res = await allocate_work(
        TeamWorkIn(title="Edit me", due_date="2026-11-25",
                   start_time="09:00", end_time="12:00",
                   employee_uids=[worker.id]),
        department_id=str(dept.id), user=mgr, session=session)
    task_id = res["items"][0]["task_uid"]

    updated = await update_work(
        uuid.UUID(task_id),
        TeamWorkPatch(title="Edited", end_time="15:00", priority="critical"),
        user=mgr, session=session)
    assert updated["title"] == "Edited"
    assert updated["end_time"] == "15:00"
    assert updated["priority"] == "critical"

    cancelled = await cancel_work(uuid.UUID(task_id), user=mgr, session=session)
    assert cancelled["status"] == "cancelled"
    # Cancelled work is frozen
    with pytest.raises(_Forbidden):
        await update_work(uuid.UUID(task_id), TeamWorkPatch(title="x"),
                          user=mgr, session=session)


@pytest.mark.asyncio
async def test_reassign_notifies_and_moves(session, seed):
    dept, mgr, worker = await _fixture(session, seed)
    second = Employee(id=uuid.uuid4(), company_id=seed["company"].id,
                      property_id=seed["prop"].id,
                      name="Second", email="s@test", department_id=dept.id,
                      status="active")
    session.add(second)
    await session.commit()
    res = await allocate_work(
        TeamWorkIn(title="Move me", employee_uids=[worker.id]),
        department_id=str(dept.id), user=mgr, session=session)
    task_id = res["items"][0]["task_uid"]
    moved = await reassign_work(
        uuid.UUID(task_id), ReassignIn(employee_uid=second.id),
        user=mgr, session=session)
    assert moved["employee_uid"] == str(second.id)
    items = await team_work(department_id=str(dept.id), status_=None,
                            employee_id=str(second.id), date_from=None,
                            date_to=None, limit=200,
                            user=mgr, session=session)
    assert items["total"] == 1
