"""Team Work — the department manager's mobile surface.

A ``department_manager`` signs in with the same staff account used on
the web; their scope resolves from the linked employee record — the
departments they head plus their own department. Every work item is a
real row in the shared ``tasks`` table, so allocation from here lands in
the employee's task list, calendar, the SA department view and the
property calendar identically.

Managers can allocate, schedule, list and reassign inside their
departments. Review authority (approve/reject submissions) stays with
Super Admin staff — no approval endpoints live here.
"""
import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import AppError
from app.dependencies.auth import get_current_user
from app.models.department import Department
from app.models.employee import Employee
from app.models.task import Task, TaskHistoryEvent
from app.models.user import User, UserRole
from app.schemas.workspace import task_out

router = APIRouter(prefix="/team", tags=["team"])

IST = ZoneInfo("Asia/Kolkata")
OPEN_STATUSES = ("pending", "assigned", "in_progress", "reopened", "scheduled")


class _Forbidden(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "FORBIDDEN"
    message = "You do not have access to this."


class _NotFound(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"
    message = "The requested resource was not found."


async def _managed_departments(
    session: AsyncSession, user: User
) -> list[Department]:
    """Departments this manager may operate — head-of plus own."""
    if user.role != UserRole.DEPARTMENT_MANAGER or not user.employee_id:
        raise _Forbidden()
    rows = (await session.execute(
        select(Department).where(
            or_(
                Department.head_employee_id == user.employee_id,
                Department.id.in_(
                    select(Employee.department_id).where(
                        Employee.id == user.employee_id)),
            ),
            Department.company_id == user.company_id,
            Department.status == "active",
        )
    )).scalars().all()
    if not rows:
        raise _Forbidden()
    return list(rows)


async def _department(
    session: AsyncSession, user: User, department_id: uuid.UUID
) -> Department:
    depts = await _managed_departments(session, user)
    dept = next((d for d in depts if d.id == department_id), None)
    if dept is None:
        raise _NotFound()
    return dept


def _dept_pred(dept: Department):
    return or_(
        Task.department_id == dept.id,
        Task.employee_id.in_(
            select(Employee.id).where(Employee.department_id == dept.id)),
    )


def _date_overlap(from_d: str, to_d: str):
    sched_ist = func.timezone("Asia/Kolkata", Task.scheduled_for)
    return or_(
        func.date(sched_ist).between(from_d, to_d),
        func.substr(Task.due_date, 1, 10).between(from_d, to_d),
        Task.operational_date.between(from_d, to_d),
    )


@router.get("")
async def team_overview(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Departments the manager operates, with roster + open work counts."""
    depts = await _managed_departments(session, user)
    out = []
    for dept in depts:
        emps = (await session.execute(
            select(Employee).where(
                Employee.department_id == dept.id,
                func.lower(Employee.status) != "deactivated",
            ).order_by(Employee.name)
        )).scalars().all()
        emp_ids = [e.id for e in emps]
        counts = dict((await session.execute(
            select(Task.status, func.count()).where(
                _dept_pred(dept), Task.property_id == dept.property_id)
            .group_by(Task.status)
        )).all())
        open_counts = dict((await session.execute(
            select(Task.employee_id, func.count()).where(
                Task.employee_id.in_(emp_ids),
                Task.status.in_(OPEN_STATUSES))
            .group_by(Task.employee_id)
        )).all()) if emp_ids else {}
        today = datetime.now(IST).date().isoformat()
        overdue = await session.scalar(
            select(func.count()).select_from(Task).where(
                _dept_pred(dept),
                Task.property_id == dept.property_id,
                Task.status.in_(OPEN_STATUSES),
                func.substr(Task.due_date, 1, 10) < today,
            )) or 0
        out.append({
            "department_uid": str(dept.id),
            "name": dept.name,
            "code": dept.code,
            "is_head": dept.head_employee_id == user.employee_id,
            "counts": dict(counts),
            "overdue": int(overdue),
            "employees": [{
                "employee_uid": str(e.id),
                "name": e.name,
                "role": e.role,
                "is_head": dept.head_employee_id == e.id,
                "open_tasks": int(open_counts.get(e.id, 0)),
            } for e in emps],
        })
    return {"items": out}


@router.get("/work")
async def team_work(
    department_id: str = Query(...),
    status_: str | None = Query(None, alias="status"),
    employee_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = Query(200, ge=1, le=500),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    dept = await _department(session, user, uuid.UUID(department_id))
    q = select(Task).where(
        Task.property_id == dept.property_id, _dept_pred(dept))
    if status_:
        q = q.where(Task.status == status_)
    if employee_id:
        q = q.where(Task.employee_id == uuid.UUID(employee_id))
    if date_from or date_to:
        q = q.where(_date_overlap(
            date_from or "0001-01-01", date_to or "9999-12-31"))
    tasks = (await session.execute(
        q.order_by(Task.scheduled_for.asc().nulls_last(),
                   Task.due_date.asc().nulls_last()).limit(limit)
    )).scalars().all()
    return {"items": [task_out(t) for t in tasks], "total": len(tasks)}


class TeamWorkIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    work_type: str | None = None
    priority: str = "medium"
    zone_uid: uuid.UUID | None = None
    due_date: str | None = None
    due_time: str | None = None
    scheduled_for: str | None = None
    checklist: list[dict] | None = None
    employee_uids: list[uuid.UUID] = Field(min_length=1, max_length=25)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=IST).astimezone(UTC)
    return dt.astimezone(UTC)


@router.post("/work", status_code=status.HTTP_201_CREATED)
async def allocate_work(
    payload: TeamWorkIn,
    department_id: str = Query(...),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Create one task per assignee — real ``tasks`` rows stamped with the
    department, the manager's checklist and the scheduled window."""
    from app.models.structure import Zone
    from app.services.maintenance import next_ticket_number

    dept = await _department(session, user, uuid.UUID(department_id))
    assignees = list(dict.fromkeys(payload.employee_uids))
    members = {e.id: e for e in (await session.execute(
        select(Employee).where(
            Employee.id.in_(assignees), Employee.department_id == dept.id)
    )).scalars()}
    missing = [str(u) for u in assignees if u not in members]
    if missing:
        raise _Forbidden()
    zone_id = None
    if payload.zone_uid:
        z = await session.get(Zone, payload.zone_uid)
        if z is None or z.property_id != dept.property_id:
            raise _NotFound()
        zone_id = z.id

    batch_id = uuid.uuid4() if len(assignees) > 1 else None
    tasks = []
    for uid in assignees:
        emp = members[uid]
        task = Task(
            property_id=dept.property_id,
            ticket_number=await next_ticket_number(session, "task"),
            zone_id=zone_id,
            area_id=None,
            department_id=dept.id,
            checklist=[
                {"title": str(c.get("title", "")).strip(),
                 "description": c.get("description"),
                 "required": bool(c.get("required", True))}
                for c in (payload.checklist or [])
                if str(c.get("title", "")).strip()
            ] or None,
            employee_id=emp.id,
            assigned_to_name=emp.name,
            title=payload.title.strip(),
            description=payload.description,
            task_type="fixed",
            work_type=(payload.work_type or dept.name).strip().lower(),
            origin="manual",
            status="assigned",
            priority=payload.priority,
            due_date=payload.due_date,
            due_time=payload.due_time,
            scheduled_for=_parse_dt(payload.scheduled_for),
            created_by_name=user.name,
            allocation_batch_id=batch_id,
            allocation_status="manually_assigned",
            allocation_method="manual",
        )
        session.add(task)
        await session.flush()
        session.add(TaskHistoryEvent(
            task_id=task.id, type="allocated", actor_name=user.name,
            note=f"Assigned to {emp.name}"))
        tasks.append(task)
    await session.commit()

    # Post-commit invalidation hints — the assignee's app polls anyway.
    from app.services.task import TaskService
    svc = TaskService(session)
    for t in tasks:
        svc._emit_task(t, "task.created")
    return {"items": [task_out(t) for t in tasks]}


class ReassignIn(BaseModel):
    employee_uid: uuid.UUID


@router.post("/work/{task_id}/reassign")
async def reassign_work(
    task_id: uuid.UUID,
    payload: ReassignIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    task = await session.get(Task, task_id)
    if task is None:
        raise _NotFound()
    dept = await session.scalar(
        select(Department).where(Department.id == task.department_id)) \
        if task.department_id else None
    if dept is None and task.employee_id:
        dept = await session.scalar(
            select(Department).join(
                Employee, Employee.department_id == Department.id
            ).where(Employee.id == task.employee_id))
    if dept is None:
        raise _Forbidden()
    await _department(session, user, dept.id)  # 404s outside scope
    if task.status in ("submitted", "completed", "cancelled"):
        raise _Forbidden()

    emp = await session.get(Employee, payload.employee_uid)
    if emp is None or emp.department_id != dept.id:
        raise _Forbidden()
    prev_name = task.assigned_to_name
    task.employee_id = emp.id
    task.assigned_to_name = emp.name
    task.allocation_status = "manually_assigned"
    task.allocation_method = "reassign"
    session.add(TaskHistoryEvent(
        task_id=task.id, type="reassigned", actor_name=user.name,
        note=f"Reassigned from {prev_name or 'unassigned'} to {emp.name}"))
    await session.commit()
    from app.services.task import TaskService
    TaskService(session)._emit_task(task, "task.updated")
    return task_out(task)
