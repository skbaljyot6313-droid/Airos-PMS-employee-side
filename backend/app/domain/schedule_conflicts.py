"""Shared work-schedule rules — conflict detection, schedule windows and
overdue evaluation.

This module is BYTE-IDENTICAL in the Employee Backend and the Super Admin
backend (same contract as ``domain/coverage.py``): both applications must
interpret work days, schedule windows, conflicts and overdue state the
same way. Edit both copies together.

Everything here is pure logic over the shared ``tasks`` table — the
property's configured timezone is IST for scheduling purposes, matching
the operational-day convention used everywhere else.
"""
import uuid
from datetime import UTC, datetime
from typing import Mapping
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import Employee
from app.models.task import Task

IST = ZoneInfo("Asia/Kolkata")

# Work that can still be acted on — terminal states never conflict and
# are never overdue.
OPEN_STATUSES = ("pending", "assigned", "in_progress", "reopened", "scheduled")


def hm(value: str | None) -> int | None:
    """'HH:MM' -> minutes since midnight; None/garbage -> None."""
    if not value:
        return None
    try:
        h, m = value.strip().split(":")[:2]
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def task_day(task: Task) -> str | None:
    """The IST calendar day a task belongs to — scheduled_for first, then
    the due-date prefix, then the stamped operational date. Never the
    creation timestamp (mirrors the calendar overlap predicate)."""
    if task.scheduled_for is not None:
        sched = task.scheduled_for
        if sched.tzinfo is None:
            sched = sched.replace(tzinfo=IST)
        return sched.astimezone(IST).date().isoformat()
    if task.due_date and task.due_date[:10]:
        return task.due_date[:10]
    return task.operational_date or None


def task_window(task: Task) -> tuple[int | None, int | None]:
    """(start, end) in minutes — scheduled_for/due_time when explicit
    window fields are absent; end None = open-ended."""
    start = hm(task.start_time) or hm(task.due_time)
    if start is None and task.scheduled_for is not None:
        sched = task.scheduled_for
        if sched.tzinfo is None:
            sched = sched.replace(tzinfo=IST)
        local = sched.astimezone(IST)
        start = local.hour * 60 + local.minute
    return start, hm(task.end_time)


def scheduled_end(task: Task) -> datetime | None:
    """The IST instant the work window ends — schedule day plus end_time
    (or due_time, or end-of-day). end <= start rolls to the next day
    (overnight window). None when the task has no scheduled day."""
    day = task_day(task)
    if day is None:
        return None
    start_m, end_m = task_window(task)
    if end_m is None:
        end_m = 23 * 60 + 59
    from datetime import date as _date, timedelta
    d = _date.fromisoformat(day)
    if start_m is not None and end_m <= start_m and hm(task.end_time) is not None:
        d = d + timedelta(days=1)
    return datetime(
        d.year, d.month, d.day, tzinfo=IST
    ) + timedelta(minutes=end_m)


def is_overdue(task: Task, now: datetime | None = None) -> bool:
    """Open work past its scheduled end instant (IST). Completed,
    submitted, cancelled and abandoned work is never overdue."""
    if task.status not in OPEN_STATUSES:
        return False
    end = scheduled_end(task)
    if end is None:
        return False
    now = now or datetime.now(IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    return now.astimezone(IST) > end


async def assignment_conflicts(
    session: AsyncSession,
    employees: Mapping[uuid.UUID, Employee],
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
        if target_day and task_day(task) != target_day:
            continue
        t_start, t_end = task_window(task)
        duplicate = (
            task.title.strip().lower() == norm
            and (target_day is None or task_day(task) == target_day)
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
            "day": task_day(task),
            "start_time": task.start_time or task.due_time or None,
            "end_time": task.end_time,
            "window": (
                f"{task.start_time or task.due_time or ''}"
                f"–{task.end_time or ''}"
            ).strip("–") or None,
            "kind": "duplicate" if duplicate else "overlap",
        })
    return conflicts


def parse_dt(value: str | None) -> datetime | None:
    """ISO-8601 → aware UTC datetime. Naive input is read as IST (the
    property's scheduling timezone) — never silently as UTC."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=IST).astimezone(UTC)
    return dt.astimezone(UTC)
