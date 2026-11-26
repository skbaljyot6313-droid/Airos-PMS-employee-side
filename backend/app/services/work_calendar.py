"""Work calendar — one scoped feed for the employee day/week timeline.

The mobile calendar needs three otherwise separate streams at once:
attendance detail (start/end + break segments), allocated work, and the
work-history events that show what was actually done. This service returns
all three for an arbitrary IST business-date range while keeping the
employee scope identical to /tasks + /maintenance.
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AppError
from app.models.attendance import AttendanceDay
from app.models.maintenance import MaintenanceTicket, MaintenanceTicketEvent
from app.models.task import Task, TaskHistoryEvent
from app.models.user import User
from app.repositories.attendance import AttendanceRepository
from app.schemas.attendance import request_out, workday_out
from app.schemas.maintenance import ticket_out
from app.schemas.workspace import task_out
from app.services.task_resources import attach_task_resources

IST = ZoneInfo("Asia/Kolkata")
MAX_RANGE_DAYS = 92


class InvalidDateRange(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"
    message = "Invalid date range."


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise InvalidDateRange() from exc


def _utc_bounds(from_day: date, to_day: date) -> tuple[datetime, datetime]:
    """[IST date 00:00, IST next-date 00:00) as naive UTC bounds.

    SQLAlchemy's SQLite test dialect stores timezone-aware values as naive
    wall-clock timestamps; Postgres interprets these bounds as UTC.
    """
    start = datetime.combine(from_day, time.min, tzinfo=IST).astimezone(UTC)
    end = datetime.combine(to_day + timedelta(days=1), time.min, tzinfo=IST).astimezone(UTC)
    return start.replace(tzinfo=None), end.replace(tzinfo=None)


def _date_range(from_day: date, to_day: date) -> list[date]:
    return [from_day + timedelta(days=i) for i in range((to_day - from_day).days + 1)]


class WorkCalendarService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def range(self, user: User, date_from: str, date_to: str) -> dict:
        from_day = _parse_date(date_from)
        to_day = _parse_date(date_to)
        if to_day < from_day or (to_day - from_day).days + 1 > MAX_RANGE_DAYS:
            raise InvalidDateRange()

        day_keys = [d.isoformat() for d in _date_range(from_day, to_day)]
        empty = {
            "date_from": from_day.isoformat(),
            "date_to": to_day.isoformat(),
            "days": [{"date": d, "attendance": workday_out(None, date=d)} for d in day_keys],
            "requests": [],
            "tasks": [],
            "maintenance": [],
        }
        if user.employee_id is None:
            return empty

        start_utc, end_utc = _utc_bounds(from_day, to_day)
        repo = AttendanceRepository(self.session)
        days, requests, tasks, tickets = await self._load(
            user, from_day, to_day, start_utc, end_utc, repo
        )

        day_by_date: dict[str, AttendanceDay] = {
            d.attendance_date: d for d in days
        }
        return {
            "date_from": from_day.isoformat(),
            "date_to": to_day.isoformat(),
            "days": [
                {
                    "date": d,
                    "attendance": workday_out(day_by_date.get(d), date=d),
                }
                for d in day_keys
            ],
            "requests": [request_out(r) for r in requests],
            "tasks": [task_out(t) for t in tasks],
            "maintenance": [ticket_out(t) for t in tickets],
        }

    async def _load(
        self,
        user: User,
        from_day: date,
        to_day: date,
        start_utc: datetime,
        end_utc: datetime,
        repo: AttendanceRepository,
    ) -> tuple[list[AttendanceDay], list, list[Task], list[MaintenanceTicket]]:
        days = await repo.list_days(
            user.employee_id, from_day.isoformat(), to_day.isoformat()
        )
        requests = await repo.list_requests(
            user.employee_id, from_day.isoformat(), to_day.isoformat()
        )
        tasks = await self._tasks(user, from_day, to_day, start_utc, end_utc)
        tickets = await self._maintenance(user, from_day, to_day, start_utc, end_utc)
        return days, requests, tasks, tickets

    async def _tasks(
        self,
        user: User,
        from_day: date,
        to_day: date,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[Task]:
        from_key = from_day.isoformat()
        to_key = to_day.isoformat()
        activity_exists = exists().where(
            and_(
                TaskHistoryEvent.task_id == Task.id,
                TaskHistoryEvent.at >= start_utc,
                TaskHistoryEvent.at < end_utc,
            )
        )
        result = await self.session.execute(
            select(Task)
            .where(
                Task.employee_id == user.employee_id,
                or_(
                    Task.operational_date.between(from_key, to_key),
                    func.substr(Task.due_date, 1, 10).between(from_key, to_key),
                    and_(Task.scheduled_for >= start_utc, Task.scheduled_for < end_utc),
                    and_(Task.submitted_at >= start_utc, Task.submitted_at < end_utc),
                    and_(Task.completed_at >= start_utc, Task.completed_at < end_utc),
                    and_(Task.abandoned_at >= start_utc, Task.abandoned_at < end_utc),
                    and_(Task.created_at >= start_utc, Task.created_at < end_utc),
                    activity_exists,
                ),
            )
            .options(selectinload(Task.history))
            .order_by(
                Task.scheduled_for.asc().nulls_last(),
                Task.due_date.asc().nulls_last(),
                Task.created_at.asc(),
            )
        )
        tasks = result.scalars().all()
        await attach_task_resources(self.session, tasks)
        return tasks

    async def _maintenance(
        self,
        user: User,
        from_day: date,
        to_day: date,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[MaintenanceTicket]:
        from_key = from_day.isoformat()
        to_key = to_day.isoformat()
        activity_exists = exists().where(
            and_(
                MaintenanceTicketEvent.ticket_id == MaintenanceTicket.id,
                MaintenanceTicketEvent.created_at >= start_utc,
                MaintenanceTicketEvent.created_at < end_utc,
            )
        )
        result = await self.session.execute(
            select(MaintenanceTicket)
            .where(
                MaintenanceTicket.assigned_to == user.employee_id,
                or_(
                    func.substr(MaintenanceTicket.due_date, 1, 10).between(from_key, to_key),
                    and_(MaintenanceTicket.resolved_at >= start_utc, MaintenanceTicket.resolved_at < end_utc),
                    and_(MaintenanceTicket.closed_at >= start_utc, MaintenanceTicket.closed_at < end_utc),
                    and_(MaintenanceTicket.created_at >= start_utc, MaintenanceTicket.created_at < end_utc),
                    activity_exists,
                ),
            )
            .options(
                selectinload(MaintenanceTicket.events),
                selectinload(MaintenanceTicket.attachments),
            )
            .order_by(
                MaintenanceTicket.due_date.asc().nulls_last(),
                MaintenanceTicket.created_at.asc(),
            )
        )
        return result.scalars().all()
