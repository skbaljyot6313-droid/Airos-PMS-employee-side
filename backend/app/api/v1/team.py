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
from app.services.task_resources import attach_task_resources

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
                "job_title": e.job_title,
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
    await attach_task_resources(session, tasks)
    return {"items": [task_out(t) for t in tasks], "total": len(tasks)}


class TeamWorkIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=1000)
    work_type: str | None = None
    priority: str = "medium"
    zone_uid: uuid.UUID | None = None
    due_date: str | None = None
    due_time: str | None = None
    scheduled_for: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    break_start_time: str | None = None
    break_end_time: str | None = None
    estimated_minutes: int | None = Field(default=None, ge=0, le=24 * 60)
    checklist: list[dict] | None = None
    employee_uids: list[uuid.UUID] = Field(min_length=1, max_length=25)
    # Conflict policy — default blocks on overlaps/duplicates; the UI can
    # re-submit with allow_conflicts after showing the conflict list.
    allow_conflicts: bool = False


def _hm(value: str | None) -> int | None:
    """'HH:MM' -> minutes since midnight; None/garbage -> None."""
    if not value:
        return None
    try:
        h, m = value.strip().split(":")[:2]
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def _task_day(task: Task) -> str | None:
    if task.scheduled_for is not None:
        return task.scheduled_for.astimezone(IST).date().isoformat()
    return (task.due_date or "")[:10] or None


def _task_window(task: Task) -> tuple[int | None, int | None]:
    """(start, end) in minutes — scheduled_for/due_time when explicit
    window fields are absent; end None = open-ended."""
    start = _hm(task.start_time) or _hm(task.due_time)
    if start is None and task.scheduled_for is not None:
        local = task.scheduled_for.astimezone(IST)
        start = local.hour * 60 + local.minute
    return start, _hm(task.end_time)


async def _assignment_conflicts(
    session: AsyncSession,
    employees: dict[uuid.UUID, Employee],
    *,
    target_day: str | None,
    start: int | None,
    end: int | None,
    title: str,
    property_id: uuid.UUID,
    exclude_task_ids: set[uuid.UUID] | None = None,
) -> list[dict]:
    """Overlaps + exact duplicates for the proposed window, per assignee.

    Window-less tasks (no start time) can only conflict as duplicates —
    a row without a window never blocks a new assignment."""
    if not employees:
        return []
    q = select(Task).where(
        Task.property_id == property_id,
        Task.employee_id.in_(list(employees)),
        Task.status.in_(OPEN_STATUSES),
    )
    if exclude_task_ids:
        q = q.where(~Task.id.in_(exclude_task_ids))
    rows = (await session.execute(q)).scalars().all()
    conflicts: list[dict] = []
    norm = title.strip().lower()
    for task in rows:
        if target_day and _task_day(task) != target_day:
            continue
        t_start, t_end = _task_window(task)
        duplicate = (
            task.title.strip().lower() == norm
            and (target_day is None or _task_day(task) == target_day)
        )
        overlap = (
            start is not None
            and t_start is not None
            and (end is None or t_start < end)
            and (t_end is None or start < t_end)
        )
        if not (duplicate or overlap):
            continue
        emp = employees.get(task.employee_id)
        conflicts.append({
            "employee_uid": str(task.employee_id),
            "employee_name": emp.name if emp else None,
            "task_uid": str(task.id),
            "title": task.title,
            "day": _task_day(task),
            "window": (
                f"{task.start_time or task.due_time or ''}"
                f"–{task.end_time or ''}"
            ).strip("–") or None,
            "kind": "duplicate" if duplicate else "overlap",
        })
    return conflicts


class _ScheduleConflict(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "SCHEDULE_CONFLICT"
    message = "Assignment conflicts with existing scheduled work."


def _conflict_error(conflicts: list[dict]) -> AppError:
    return _ScheduleConflict(details={"conflicts": conflicts})


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
    from app.services.notifications import NotificationService

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

    start_m, end_m = _hm(payload.start_time), _hm(payload.end_time)
    brk_s, brk_e = _hm(payload.break_start_time), _hm(payload.break_end_time)
    if (brk_s is None) != (brk_e is None):
        raise AppError("Break needs both a start and an end.",
                       code="VALIDATION_ERROR", field="break_start_time")

    sched = _parse_dt(payload.scheduled_for)
    target_day = (
        sched.astimezone(IST).date().isoformat() if sched
        else (payload.due_date or "")[:10] or None
    )
    if not payload.allow_conflicts:
        conflicts = await _assignment_conflicts(
            session, members, target_day=target_day,
            start=start_m, end=end_m, title=payload.title,
            property_id=dept.property_id)
        if conflicts:
            raise _conflict_error(conflicts)

    description = (payload.description or "").strip() or None
    if payload.notes and payload.notes.strip():
        description = (
            f"{description}\n\nNotes: {payload.notes.strip()}"
            if description else payload.notes.strip()
        )

    batch_id = uuid.uuid4() if len(assignees) > 1 else None
    notifier = NotificationService(session)
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
            description=description,
            task_type="fixed",
            work_type=(payload.work_type or dept.name).strip().lower(),
            origin="manual",
            status="assigned",
            priority=payload.priority,
            due_date=payload.due_date,
            due_time=payload.due_time or payload.start_time,
            scheduled_for=sched,
            start_time=payload.start_time,
            end_time=payload.end_time,
            break_start_time=payload.break_start_time,
            break_end_time=payload.break_end_time,
            estimated_minutes=payload.estimated_minutes,
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
        await notifier.notify(
            employee_id=emp.id,
            property_id=dept.property_id,
            type="task_assigned",
            title=f"New work: {task.title[:80]}",
            body=f"{user.name} assigned you “{task.title[:120]}”"
                 + (f" on {target_day}" if target_day else ""),
            task_id=task.id,
            employee_name=emp.name,
        )
        tasks.append(task)
    await session.commit()

    # Post-commit invalidation hints — the assignee's app polls anyway.
    from app.services.task import TaskService
    svc = TaskService(session)
    for t in tasks:
        svc._emit_task(t, "task.created")
    await attach_task_resources(session, tasks)
    return {"items": [task_out(t) for t in tasks]}


class TeamWorkPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=1000)
    priority: str | None = None
    zone_uid: uuid.UUID | None = None
    due_date: str | None = None
    due_time: str | None = None
    scheduled_for: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    break_start_time: str | None = None
    break_end_time: str | None = None
    estimated_minutes: int | None = Field(default=None, ge=0, le=24 * 60)
    checklist: list[dict] | None = None
    allow_conflicts: bool = False


async def _scoped_task(
    session: AsyncSession, user: User, task_id: uuid.UUID
) -> Task:
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
    return task


@router.patch("/work/{task_id}")
async def update_work(
    task_id: uuid.UUID,
    payload: TeamWorkPatch,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Edit/reschedule a department assignment — server-side scoped to the
    manager's departments. Submitted/completed/cancelled work is frozen."""
    task = await _scoped_task(session, user, task_id)
    if task.status in ("submitted", "completed", "cancelled"):
        raise _Forbidden()

    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return task_out(task)

    if payload.zone_uid is not None:
        from app.models.structure import Zone
        z = await session.get(Zone, payload.zone_uid)
        if z is None or z.property_id != task.property_id:
            raise _NotFound()
        task.zone_id = z.id

    start_m = _hm(changes.get("start_time", task.start_time))
    end_m = _hm(changes.get("end_time", task.end_time))
    sched = _parse_dt(changes.get("scheduled_for")) \
        if "scheduled_for" in changes else task.scheduled_for
    due_date = changes.get("due_date", task.due_date)
    target_day = (
        sched.astimezone(IST).date().isoformat() if sched
        else (due_date or "")[:10] or None
    )
    new_title = changes.get("title", task.title)
    if not payload.allow_conflicts and task.employee_id:
        emp = await session.get(Employee, task.employee_id)
        conflicts = await _assignment_conflicts(
            session, {task.employee_id: emp} if emp else {},
            target_day=target_day, start=start_m, end=end_m,
            title=new_title, property_id=task.property_id,
            exclude_task_ids={task.id})
        if conflicts:
            raise _conflict_error(conflicts)

    if "title" in changes and payload.title:
        task.title = payload.title.strip()
    if "description" in changes or "notes" in changes:
        desc = (changes.get("description") or "").strip() or None
        notes = (changes.get("notes") or "").strip() if "notes" in changes else None
        if desc is None:
            desc = task.description
        if notes:
            desc = f"{desc}\n\nNotes: {notes}" if desc else notes
        task.description = desc
    for field in ("priority", "due_date", "due_time", "start_time", "end_time",
                  "break_start_time", "break_end_time", "estimated_minutes"):
        if field in changes:
            setattr(task, field, changes[field])
    if "scheduled_for" in changes:
        task.scheduled_for = sched
    if "checklist" in changes:
        task.checklist = [
            {"title": str(c.get("title", "")).strip(),
             "description": c.get("description"),
             "required": bool(c.get("required", True))}
            for c in (payload.checklist or [])
            if str(c.get("title", "")).strip()
        ] or None

    session.add(TaskHistoryEvent(
        task_id=task.id, type="updated", actor_name=user.name,
        note="Assignment updated"))
    await session.commit()
    from app.services.task import TaskService
    TaskService(session)._emit_task(task, "task.updated")
    await attach_task_resources(session, [task])
    return task_out(task)


@router.post("/work/{task_id}/cancel")
async def cancel_work(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    task = await _scoped_task(session, user, task_id)
    if task.status in ("submitted", "completed", "cancelled"):
        raise _Forbidden()
    task.status = "cancelled"
    session.add(TaskHistoryEvent(
        task_id=task.id, type="cancelled", actor_name=user.name,
        note="Assignment cancelled"))
    from app.services.notifications import NotificationService
    await NotificationService(session).notify(
        employee_id=task.employee_id,
        property_id=task.property_id,
        type="task_cancelled",
        title=f"Cancelled: {task.title[:80]}",
        body=f"{user.name} cancelled “{task.title[:120]}”",
        task_id=task.id,
        employee_name=task.assigned_to_name,
    )
    await session.commit()
    from app.services.task import TaskService
    TaskService(session)._emit_task(task, "task.updated")
    await attach_task_resources(session, [task])
    return task_out(task)


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
    from app.services.notifications import NotificationService
    await NotificationService(session).notify(
        employee_id=emp.id,
        property_id=task.property_id,
        type="task_assigned",
        title=f"Reassigned to you: {task.title[:70]}",
        body=f"{user.name} reassigned “{task.title[:120]}” to you",
        task_id=task.id,
        employee_name=emp.name,
    )
    await session.commit()
    from app.services.task import TaskService
    TaskService(session)._emit_task(task, "task.updated")
    await attach_task_resources(session, [task])
    return task_out(task)
