"""TaskService — CRUD + lifecycle + repetitive-series generation."""

import uuid
from datetime import datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.logging import get_logger
from app.core.storage import get_storage, storage_key_from_url
from app.models.employee import Employee, employee_is_assignable
from app.models.structure import Bed, Dorm, Room, Washroom, WashroomFixture, Zone
from app.models.task import (
    Task, TaskCompletionImage, TaskCompletionSubmission, TaskHistoryEvent,
)
from app.models.user import User, UserRole
from app.schemas.structure import (
    TaskCompleteRequest,
    TaskCreateRequest,
    TaskSubmitRequest,
    TaskUpdateRequest,
)
from app.services.structure import (
    ConflictErr,
    NotFoundErr,
    StructureService,
    ValidationErr,
)

# pending=open · assigned · in_progress · submitted (awaiting review)
# reopened (was rejected) · completed · cancelled · abandoned (rollover)
# scheduled · overdue
TASK_STATUSES = {
    "pending", "assigned", "in_progress", "submitted", "reopened",
    "completed", "cancelled", "abandoned", "overdue", "scheduled",
}
TASK_TYPES = {"fixed", "repetitive", "automated"}
PRIORITIES = {"low", "medium", "high", "urgent", "critical"}
HOURLY = {"hourly": 1, "every_2_hours": 2, "every_6_hours": 6, "every_12_hours": 12}
DAILY = {"daily": 1, "weekly": 7, "monthly": 30, "quarterly": 90, "yearly": 365}

# due_date / due_time are stored as local wall-clock — the create modal sends
# a date input + time input with no timezone. Occurrence math therefore runs
# in naive IST (matching the template scheduler's DEFAULT_TZ) so a stored
# "20:00" stays "20:00" on the user's clock.
IST = ZoneInfo("Asia/Kolkata")
logger = get_logger("app.task")


def _local_now() -> datetime:
    return datetime.now(IST).replace(tzinfo=None)


def _d(s):
    try:
        return datetime.fromisoformat(s).date()
    except (ValueError, TypeError):
        return None


def _hm(s, fallback):
    try:
        h, m = s.split(":")[:2]
        return dtime(int(h), int(m))
    except (ValueError, TypeError, AttributeError):
        return fallback


def _due_dt(task: Task) -> datetime | None:
    """Effective due moment of a task — due_date + due_time combined.

    due_date may be a bare date ('2026-09-23') or a full ISO timestamp
    (hourly occurrences). A bare date without due_time falls back to
    end-of-day so hourly series don't restart from midnight.
    """
    if not task.due_date:
        return None
    try:
        dt = datetime.fromisoformat(task.due_date)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(IST).replace(tzinfo=None)
    if "T" not in task.due_date:
        dt = datetime.combine(
            dt.date(), _hm(task.due_time, dtime(23, 59))
        )
    return dt


def next_occurrence(task: Task, after: datetime) -> datetime | None:
    """Smallest scheduled occurrence strictly after `after` (naive IST).

    The occurrence grid is anchored at the task's due moment and steps by
    the recurrence interval — hourly schedules honor the optional daily
    window; daily+ schedules step whole days at start_time (midnight when
    unset). Returns None once the recurrence end date is passed.
    """
    after = after.replace(tzinfo=None)
    start_d = _d(task.recurrence_start_date)
    end_d = _d(task.recurrence_end_date)  # None → runs forever
    wstart = _hm(task.start_time, dtime(8, 0))
    wend = _hm(task.recurrence_window_end, None)
    base = _due_dt(task)

    if task.recurrence in HOURLY:
        hours = HOURLY[task.recurrence]
        nxt = (base or after) + timedelta(hours=hours)
        if wend is None and nxt <= after:
            # continuous grid — jump straight to the first slot after `after`
            # instead of stepping through a long-missed chain one by one
            k = int((after - nxt).total_seconds() // (hours * 3600)) + 1
            nxt += timedelta(hours=hours * k)
        for _ in range(20000):
            if wend and nxt.time() > wend:
                # past today's window → resume tomorrow at start_time
                nxt = datetime.combine(nxt.date() + timedelta(days=1), wstart)
                continue
            if start_d and nxt.date() < start_d:
                nxt = datetime.combine(start_d, wstart)
                continue
            if end_d and nxt.date() > end_d:
                return None
            if nxt > after:
                return nxt
            nxt += timedelta(hours=hours)
        return None

    days = DAILY.get(task.recurrence) or task.recurrence_interval_days or 1
    next_d = (base.date() if base else after.date()) + timedelta(days=days)
    anchor = _hm(task.start_time, dtime(0, 0))
    for _ in range(3660):
        if start_d and next_d < start_d:
            next_d = start_d
        if end_d and next_d > end_d:
            return None
        if datetime.combine(next_d, anchor) > after:
            return datetime.combine(next_d, anchor)
        next_d += timedelta(days=days)
    return None


def _expired(task: Task) -> bool:
    """Recurring instance past its validity boundary?

    `expires_at` (the next scheduled occurrence) is the authoritative
    lifecycle clock — never extended by scheduler downtime. A task past
    it is a dead occurrence: it cannot be worked on, only abandoned by
    the sweep.
    """
    exp = task.expires_at
    if exp is None:
        return False
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)  # sqlite round-trip
    return exp <= datetime.now(timezone.utc)


def _raise_if_expired(task: Task) -> None:
    if _expired(task):
        raise ConflictErr(
            "This task's occurrence has expired — the next scheduled "
            "instance supersedes it."
        )


def _occurrence_due_string(task: Task, occ: datetime) -> str:
    """Stored due_date for an occurrence — ISO timestamp when a clock time
    is meaningful (hourly / explicit start_time), bare date otherwise."""
    if task.recurrence in HOURLY or task.start_time:
        return occ.isoformat()
    return occ.date().isoformat()


class TaskService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.structure = StructureService(session)
        from app.services.work_allocation import WorkAllocationService
        self.alloc = WorkAllocationService(session)

    async def _get_task(self, user: User, task_id: uuid.UUID) -> Task:
        res = await self.session.execute(
            select(Task)
            .where(Task.id == task_id)
            .options(
                selectinload(Task.history),
                selectinload(Task.completion_images),
                selectinload(Task.completion_submissions)
                .selectinload(TaskCompletionSubmission.images),
            )
            .execution_options(populate_existing=True)
        )
        task = res.scalar_one_or_none()
        if task is None:
            raise NotFoundErr()
        await self.structure._property_for_write(user, task.property_id)
        from app.services.task_location import resolve_task_location
        location = await resolve_task_location(
            self.session, property_id=task.property_id,
            room_id=task.room_id, dorm_id=task.dorm_id,
            washroom_id=task.washroom_id, zone_id=task.zone_id,
        )
        task._resolved_area_id = location.area_id
        return task

    async def get_task(self, user: User, task_id: uuid.UUID) -> Task:
        """Fully-loaded task detail (history + evidence) for the detail
        drawer — the list endpoint intentionally returns a slim shape."""
        task = await self._get_task(user, task_id)
        # List scoping hides other employees' tasks — the detail read must
        # enforce the same boundary or the list scope is trivially bypassed.
        if user.role == UserRole.EMPLOYEE and (
            user.employee_id is None or task.employee_id != user.employee_id
        ):
            from app.dependencies.auth import Forbidden

            raise Forbidden()
        # Surface the template's checklist + evidence rules on the detail
        # payload — the list stays slim; clients render what the server
        # resolves (mirrors _resolved_area_id).
        if task.template_id:
            from app.models.template import WorkTemplate

            tpl = await self.session.get(WorkTemplate, task.template_id)
            if tpl:
                task._checklist = tpl.checklist or []
                task._verification = tpl.verification or {}
        return task

    def _require_assignee(self, user: User, task: Task) -> None:
        """Only the assigned employee — or staff — may act on a task. HR
        and department managers are NOT task actors."""
        if user.role in (UserRole.SUPER_ADMIN, UserRole.PROPERTY_MANAGER):
            return
        if user.role != UserRole.EMPLOYEE or task.employee_id != user.employee_id:
            from app.dependencies.auth import Forbidden

            raise Forbidden()

    async def _employee_or_none(self, employee_id, property_id, work_type=None):
        if employee_id is None:
            return None, None
        emp = await self.alloc.employee_for_assignment(
            employee_id, property_id, work_type=work_type
        )
        return emp.id, emp.name

    async def _task_work_type(self, task: Task) -> str:
        """Resolve the domain work kind from durable task provenance."""
        if task.work_type:
            return task.work_type
        template_type = allocation_work_type = None
        if task.template_id:
            from app.models.template import WorkTemplate
            template = await self.session.get(WorkTemplate, task.template_id)
            template_type = template.template_type if template else None
        if task.allocation_batch_id:
            from app.models.work_allocation import WorkAllocationBatch
            batch = await self.session.get(
                WorkAllocationBatch, task.allocation_batch_id)
            allocation_work_type = batch.work_type if batch else None
        from app.services.work_allocation import infer_task_work_type
        return infer_task_work_type(
            title=task.title,
            template_type=template_type,
            allocation_work_type=allocation_work_type,
        )

    async def _zone_or_none(self, zone_id, property_id):
        if zone_id is None:
            return None
        res = await self.session.execute(
            select(Zone).where(Zone.id == zone_id, Zone.property_id == property_id)
        )
        if res.scalar_one_or_none() is None:
            raise ValidationErr("Zone not found in this property.", field="zone_uid")
        return zone_id

    async def _room_or_none(self, room_id, property_id):
        if room_id is None:
            return None, None
        res = await self.session.execute(
            select(Room).where(Room.id == room_id, Room.property_id == property_id)
        )
        room = res.scalar_one_or_none()
        if room is None:
            raise ValidationErr("Room not found in this property.", field="room_uid")
        return room.id, room.room_number

    async def _washroom_or_none(self, washroom_id, property_id):
        if washroom_id is None:
            return None, None
        res = await self.session.execute(
            select(Washroom).where(
                Washroom.id == washroom_id, Washroom.property_id == property_id
            )
        )
        washroom = res.scalar_one_or_none()
        if washroom is None:
            raise ValidationErr(
                "Washroom not found in this property.", field="washroom_uid"
            )
        return washroom.id, washroom.name

    async def _fixture_or_none(self, fixture_id, washroom_id, property_id):
        """Resolve a washroom_fixture_uid → (id, label). The fixture must
        belong to the task's washroom."""
        if fixture_id is None:
            return None, None
        if washroom_id is None:
            raise ValidationErr(
                "A fixture target requires washroom_uid.",
                field="washroom_fixture_uid",
            )
        res = await self.session.execute(
            select(WashroomFixture).where(
                WashroomFixture.id == fixture_id,
                WashroomFixture.washroom_id == washroom_id,
                WashroomFixture.property_id == property_id,
            )
        )
        fixture = res.scalar_one_or_none()
        if fixture is None:
            raise ValidationErr(
                "Fixture not found in this washroom.",
                field="washroom_fixture_uid",
            )
        t = fixture.fixture_type.strip()
        label = (
            f"{t.replace('_', ' ').title() if t else 'Fixture'}"
            f" {fixture.fixture_number:02d}"
        )
        return fixture.id, label

    async def _stamp_fixture_cleaned(self, task: Task) -> None:
        """Completing a fixture-scoped task marks the fixture clean."""
        if task.washroom_fixture_id is None:
            return
        fixture = await self.session.get(
            WashroomFixture, task.washroom_fixture_id
        )
        if fixture is not None:
            fixture.last_cleaned_at = datetime.now(timezone.utc)

    def _history(self, task, type_, user, note=None, photos=None):
        event = TaskHistoryEvent(
            task_id=task.id, type=type_, actor_name=user.name,
            note=note, photos=photos or [],
        )
        self.session.add(event)
        # Keep an already-loaded collection authoritative — lifecycle
        # methods return the in-session task without a redundant refetch.
        # (order_by=TaskHistoryEvent.at → append = chronological.)
        if "history" not in sa_inspect(task).unloaded:
            task.history.append(event)
        return event

    async def _evidence_limits(self, task: Task) -> tuple[int, int]:
        required = 1
        configured_max = settings.MAX_TASK_COMPLETION_IMAGES
        if task.template_id:
            from app.models.template import WorkTemplate
            tpl = await self.session.get(WorkTemplate, task.template_id)
            v = (tpl.verification or {}) if tpl else {}
            required = v.get("min_photos", 1) if v.get("photo_required") else 0
            if v.get("max_photos"):
                configured_max = min(configured_max, int(v["max_photos"]))
        return required, configured_max

    async def _evidence_urls(self, task: Task, raw_urls) -> list[str]:
        required, maximum = await self._evidence_limits(task)
        urls = list(dict.fromkeys(
            str(u).strip() for u in (raw_urls or []) if str(u).strip()
        ))
        if len(urls) < required:
            raise ValidationErr(
                f"At least {required} completion photo"
                f"{'s are' if required > 1 else ' is'} required.",
                field="photo_urls",
            )
        if len(urls) > maximum:
            raise ValidationErr(
                f"At most {maximum} completion photos are allowed.",
                field="photo_urls",
            )
        return urls

    async def _new_submission(
        self, task: Task, event: TaskHistoryEvent, user: User,
        status: str = "pending", review_note: str | None = None,
    ) -> TaskCompletionSubmission:
        res = await self.session.execute(
            select(func.max(TaskCompletionSubmission.attempt_number)).where(
                TaskCompletionSubmission.task_id == task.id
            )
        )
        reviewed = status == "approved"
        submission = TaskCompletionSubmission(
            task_id=task.id,
            history_event_id=event.id,
            employee_id=task.employee_id,
            employee_name=event.actor_name or user.name,
            attempt_number=(res.scalar_one_or_none() or 0) + 1,
            status=status,
            submitted_at=event.at or datetime.now(timezone.utc),
            reviewed_at=datetime.now(timezone.utc) if reviewed else None,
            reviewed_by_id=user.id if reviewed else None,
            reviewed_by_name=user.name if reviewed else None,
            review_comment=review_note if reviewed else None,
        )
        self.session.add(submission)
        # Initialize while pending so _record_evidence appends without a
        # lazy-load — the in-session task stays authoritative post-commit.
        submission.images = []
        # order_by=attempt_number.desc() → the new (highest) attempt is first
        if "completion_submissions" not in sa_inspect(task).unloaded:
            task.completion_submissions.insert(0, submission)
        return submission

    def _latest_pending_submission(
        self, task: Task
    ) -> TaskCompletionSubmission | None:
        return next(
            (s for s in task.completion_submissions if s.status == "pending"),
            None,
        )

    def _record_evidence(
        self, task: Task, event: TaskHistoryEvent,
        submission: TaskCompletionSubmission, urls: list[str], user: User,
    ) -> None:
        base = datetime.now(timezone.utc)
        task_images_loaded = "completion_images" not in sa_inspect(task).unloaded
        submission_images_loaded = (
            "images" not in sa_inspect(submission).unloaded
        )
        images: list[TaskCompletionImage] = []
        for position, url in enumerate(urls):
            image = TaskCompletionImage(
                task_id=task.id,
                history_event_id=event.id,
                submission_id=submission.id,
                url=url,
                storage_key=storage_key_from_url(url),
                file_name=url.rsplit("/", 1)[-1],
                created_by_id=user.id,
                created_by_name=user.name,
                created_at=base + timedelta(milliseconds=position),
            )
            self.session.add(image)
            images.append(image)
            # order_by=created_at ascending → append keeps upload order
            if task_images_loaded:
                task.completion_images.append(image)
            if submission_images_loaded:
                submission.images.append(image)

    # ------------------------------------------------------------------

    async def create_task(self, user: User, payload: TaskCreateRequest) -> Task:
        prop = await self.structure._property_for_write(user, payload.property_uid)
        if payload.task_type not in TASK_TYPES:
            raise ValidationErr("Invalid task_type.", field="task_type")
        if payload.priority and payload.priority not in PRIORITIES:
            raise ValidationErr("Invalid priority.", field="priority")
        from app.models.template import TEMPLATE_TYPES
        from app.services.work_allocation import infer_task_work_type
        if payload.work_type is not None:
            work_type = payload.work_type.strip().lower()
            if work_type not in TEMPLATE_TYPES:
                raise ValidationErr("Invalid work_type.", field="work_type")
        else:
            work_type = infer_task_work_type(title=payload.title)
        emp_id, emp_name = await self._employee_or_none(
            payload.employee_uid, prop.id, work_type=work_type
        )
        sup_id, sup_name = await self._employee_or_none(
            payload.supervisor_uid, prop.id
        )
        zone_id = await self._zone_or_none(payload.zone_uid, prop.id)
        if sum(1 for uid in (payload.room_uid, payload.washroom_uid) if uid) > 1:
            raise ValidationErr(
                "Provide at most one task resource target.", field="room_uid"
            )
        room_id, room_number = await self._room_or_none(payload.room_uid, prop.id)
        washroom_id, washroom_name = await self._washroom_or_none(
            payload.washroom_uid, prop.id
        )
        fixture_id, fixture_label = await self._fixture_or_none(
            payload.washroom_fixture_uid, washroom_id, prop.id
        )
        rule = payload.automation_rule.model_dump() if payload.automation_rule else None
        if rule and rule.get("scope_zone_uid"):
            rule["scope_zone_uid"] = str(rule["scope_zone_uid"])
        if rule and rule.get("assign_to_uid"):
            await self._employee_or_none(
                rule["assign_to_uid"], prop.id, work_type=work_type
            )
            rule["assign_to_uid"] = str(rule["assign_to_uid"])

        from app.services.task_location import resolve_task_location

        location = await resolve_task_location(
            self.session, property_id=prop.id, room_id=room_id,
            washroom_id=washroom_id, zone_id=zone_id,
        )
        zone_id = location.zone_id
        area_id = location.area_id

        # No explicit assignee → zone/area round-robin picks one (fixed tasks
        # only; automated/repetitive templates stay templates until triggered).
        auto_alloc = None
        if emp_id is None and payload.task_type == "fixed" and (zone_id or area_id):
            zname = aname = None
            if zone_id:
                res = await self.session.execute(select(Zone).where(Zone.id == zone_id))
                z = res.scalar_one_or_none()
                zname = z.name if z else None
            if area_id:
                from app.models.structure import Area
                res = await self.session.execute(select(Area).where(Area.id == area_id))
                a = res.scalar_one_or_none()
                aname = a.name if a else None
            auto_alloc = await self.alloc.allocate(
                user, property_id=prop.id, zone_id=zone_id, zone_name=zname,
                work_type=work_type, manager_employee_id=prop.manager_employee_id,
                area_id=area_id, area_name=aname,
            )
            if auto_alloc.employee:
                emp_id = auto_alloc.employee.id
                emp_name = auto_alloc.employee.name

        from app.services.maintenance import next_ticket_number

        task = Task(
            property_id=prop.id,
            ticket_number=await next_ticket_number(self.session, "task"),
            zone_id=zone_id,
            area_id=area_id,
            room_id=room_id,
            room_number=room_number,
            washroom_id=washroom_id,
            washroom_name=washroom_name,
            washroom_fixture_id=fixture_id,
            washroom_fixture_label=fixture_label,
            supervisor_id=sup_id,
            supervisor_name=sup_name,
            employee_id=emp_id,
            assigned_to_name=emp_name,
            title=payload.title.strip(),
            description=payload.description,
            task_type=payload.task_type,
            work_type=work_type,
            origin="automation" if payload.task_type == "automated"
                  else "manual",
            # automated rules are templates — scheduled until triggered;
            # a task with an assignee starts 'assigned', otherwise 'pending' (open)
            status=(
                "scheduled" if payload.task_type == "automated"
                else "assigned" if emp_id else "pending"
            ),
            priority=payload.priority or "medium",
            due_date=payload.due_date,
            due_time=payload.due_time,
            start_time=payload.start_time,
            recurrence_start_date=payload.recurrence_start_date,
            recurrence_end_date=payload.recurrence_end_date,
            recurrence_window_end=payload.recurrence_window_end,
            created_by_name=user.name,
            recurrence=payload.recurrence,
            recurrence_interval_days=payload.recurrence_interval_days,
            automation_rule=rule,
            allocation_batch_id=auto_alloc.batch.id if auto_alloc else None,
            allocation_status=(
                "auto_assigned" if auto_alloc and emp_id
                else "manually_assigned" if emp_id
                else "unassigned"
            ),
            allocation_method=(
                auto_alloc.method if auto_alloc else "manual" if emp_id else None
            ),
            allocation_reason=auto_alloc.reason if auto_alloc else None,
        )
        self.session.add(task)
        await self.session.flush()
        task._resolved_area_id = area_id
        if task.task_type == "repetitive":
            task.series_id = task.id  # self-rooted series
            anchor = _due_dt(task)
            if anchor is not None:
                await self._stamp_occurrence_window(task, anchor)
        if auto_alloc:
            self.alloc.log_task_allocation(
                auto_alloc, task_id=task.id, room=location.room_label,
                dorm=location.dorm_label, washroom=location.washroom_label,
                zone=location.zone.name if location.zone else None,
                area=location.area.name if location.area else None,
            )
        self._history(task, "allocated", user,
                      note=(f"Auto-assigned to {emp_name} (zone round-robin)"
                            if auto_alloc and emp_name
                            else f"Assigned to {emp_name}" if emp_name else "Created"))
        if emp_id or auto_alloc:
            await self.alloc.record(
                property_id=prop.id, zone_id=zone_id,
                batch=auto_alloc.batch if auto_alloc else None,
                ticket_kind="task", ticket_id=task.id,
                ticket_number=task.ticket_number,
                employee_id=emp_id, employee_name=emp_name,
                method=auto_alloc.method if auto_alloc else "manual",
                reason=auto_alloc.reason if auto_alloc else None,
                actor_name=user.name,
            )
        if emp_id:
            from app.services.notifications import NotificationService
            await NotificationService(self.session).notify(
                employee_id=emp_id, property_id=task.property_id,
                type="task_assigned", title="New Task Assigned",
                body=task.title, task_id=task.id, employee_name=emp_name,
            )
        await self.session.commit()
        return await self._get_task(user, task.id)

    async def update_task(
        self, user: User, task_id: uuid.UUID, payload: TaskUpdateRequest
    ) -> Task:
        task = await self._get_task(user, task_id)
        data = payload.model_dump(exclude_unset=True)
        if "status" in data:
            # Status is workflow state — it must move through the lifecycle
            # endpoints (start/submit/approve/reject/reopen) so evidence
            # gates, review and unit-status derivation are never bypassed.
            raise ValidationErr(
                "Task status can only change via the lifecycle endpoints "
                "(start, submit, approve, reject, reopen).",
                field="status",
            )
        if "work_type" in data:
            wt = data.pop("work_type")
            if wt is not None:
                from app.models.template import TEMPLATE_TYPES
                wt = str(wt).strip().lower()
                if wt not in TEMPLATE_TYPES:
                    raise ValidationErr(
                        "Invalid work_type.", field="work_type")
            task.work_type = wt
        if "employee_uid" in data:
            emp_id, emp_name = await self._employee_or_none(
                data.pop("employee_uid"), task.property_id,
                work_type=await self._task_work_type(task),
            )
            if emp_id != task.employee_id:
                prev_id, prev_name = task.employee_id, task.assigned_to_name
                task.employee_id = emp_id
                task.assigned_to_name = emp_name
                task.allocation_status = "manually_assigned" if emp_id else "unassigned"
                task.allocation_method = "reassign" if prev_id else "manual"
                task.allocation_reason = None
                self._history(task, "reassigned", user,
                              note=f"Reassigned to {emp_name or 'unassigned'}")
                # Audited — but the round-robin pointer is never touched
                await self.alloc.record(
                    property_id=task.property_id, zone_id=task.zone_id, batch=None,
                    ticket_kind="task", ticket_id=task.id,
                    ticket_number=task.ticket_number,
                    employee_id=emp_id, employee_name=emp_name,
                    previous_employee_id=prev_id, previous_employee_name=prev_name,
                    method=task.allocation_method, actor_name=user.name,
                )
                if emp_id:
                    from app.services.notifications import NotificationService
                    await NotificationService(self.session).notify(
                        employee_id=emp_id, property_id=task.property_id,
                        type="task_reassigned" if prev_id else "task_assigned",
                        title="Task Reassigned" if prev_id
                              else "New Task Assigned",
                        body=task.title, task_id=task.id,
                        employee_name=emp_name,
                    )
        if "supervisor_uid" in data:
            sup_id, sup_name = await self._employee_or_none(
                data.pop("supervisor_uid"), task.property_id
            )
            task.supervisor_id = sup_id
            task.supervisor_name = sup_name
        location_changed = (
            "room_uid" in data or "washroom_uid" in data or "zone_uid" in data
        )
        # A task's resource target is load-bearing state: retargeting while
        # work is in progress or under review would strand the old unit's
        # flag forever. Reject committed-work retargets outright; a pending
        # retarget re-derives the abandoned target in the same transaction.
        retarget_attempted = "room_uid" in data or "washroom_uid" in data
        old_target = (task.room_id, task.dorm_id, task.washroom_id)
        if retarget_attempted and task.status in {
            "in_progress", "submitted", "reopened",
        }:
            raise ConflictErr(
                "Cannot retarget a task while work is in progress or under "
                "review — reject/reopen or cancel it first."
            )
        if "room_uid" in data:
            room_uid = data.pop("room_uid")
            task.room_id, task.room_number = await self._room_or_none(
                room_uid, task.property_id
            )
            if room_uid:
                task.dorm_id = task.dorm_name = None
                task.bed_ids = None
                task.washroom_id = task.washroom_name = None
        if "washroom_uid" in data:
            washroom_uid = data.pop("washroom_uid")
            task.washroom_id, task.washroom_name = await self._washroom_or_none(
                washroom_uid, task.property_id
            )
            if washroom_uid:
                task.room_id = task.room_number = None
                task.dorm_id = task.dorm_name = None
                task.bed_ids = None
        if "zone_uid" in data:
            task.zone_id = await self._zone_or_none(
                data.pop("zone_uid"), task.property_id
            )
        if location_changed:
            from app.services.task_location import resolve_task_location
            location = await resolve_task_location(
                self.session, property_id=task.property_id,
                room_id=task.room_id, dorm_id=task.dorm_id,
                washroom_id=task.washroom_id, zone_id=task.zone_id,
            )
            task.zone_id = location.zone_id
            task.area_id = location.area_id
            # _resolved_area_id feeds area_uid serialization — keep it in
            # step with the retarget since we no longer refetch.
            task._resolved_area_id = location.area_id
        if retarget_attempted and (
            task.room_id, task.dorm_id, task.washroom_id
        ) != old_target:
            # The abandoned target may have been flagged cleaning by this
            # task — release it via the canonical resolver so retargeting
            # never strands a unit.
            from app.services.resource_state import ResourceStateService
            state = ResourceStateService(self.session)
            trig = f"task retargeted ({task.ticket_number or task.title})"
            for rtype, rid in (
                ("room", old_target[0]),
                ("dorm", old_target[1]),
                ("washroom", old_target[2]),
            ):
                if rid:
                    await state.derive(
                        rtype, rid, release_to="available", user=user,
                        reason=trig,
                    )
        if "automation_rule" in data and data["automation_rule"]:
            rule = data["automation_rule"]
            if rule.get("assign_to_uid"):
                await self._employee_or_none(
                    rule["assign_to_uid"], task.property_id,
                    work_type=await self._task_work_type(task),
                )
            data["automation_rule"] = {
                **rule,
                "scope_zone_uid": str(rule["scope_zone_uid"]) if rule.get("scope_zone_uid") else None,
                "assign_to_uid": str(rule["assign_to_uid"]) if rule.get("assign_to_uid") else None,
            }
        for k, v in data.items():
            setattr(task, k, v)
        self._history(task, "edited", user)
        await self.session.commit()
        return task

    async def delete_task(self, user: User, task_id: uuid.UUID) -> None:
        task = await self._get_task(user, task_id)
        # capture the resource target before the row disappears — the
        # delete must never strand a unit in cleaning/maintenance
        room_id, dorm_id, washroom_id = (
            task.room_id, task.dorm_id, task.washroom_id,
        )
        await self.session.delete(task)
        await self.session.flush()
        if room_id or dorm_id or washroom_id:
            from app.services.resource_state import ResourceStateService
            state = ResourceStateService(self.session)
            trig = f"task deleted ({task.ticket_number or task.title})"
            if room_id:
                await state.derive("room", room_id, release_to="available",
                                   user=user, reason=trig)
            if dorm_id:
                await state.derive("dorm", dorm_id, release_to="available",
                                   user=user, reason=trig)
            if washroom_id:
                await state.derive("washroom", washroom_id,
                                   release_to="available", user=user,
                                   reason=trig)
        await self.session.commit()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start_task(self, user: User, task_id: uuid.UUID, geo=None) -> Task:
        from app.services.location import parse_geo

        fix = parse_geo(geo)  # validate before any state moves
        task = await self._get_task(user, task_id)
        self._require_assignee(user, task)
        _raise_if_expired(task)
        if task.status not in {"pending", "assigned", "reopened"}:
            raise ConflictErr(
                f"Cannot start a {task.status} task."
            )
        task.status = "in_progress"
        self._history(task, "started", user)
        # Flag-on-start (spec §40): a STARTED cleaning task commits the
        # resource to CLEANING — queued/scheduled tasks never do.
        if await self._task_work_type(task) == "cleaning":
            await self._flag_resource_cleaning(task, user)
        if fix is not None:
            from app.services.location import LocationService
            await LocationService(self.session).record(
                property_id=task.property_id,
                employee_id=user.employee_id, fix=fix,
                source="task_start", task_id=task.id,
            )
        await self.session.commit()
        return task

    async def _flag_resource_cleaning(self, task: Task, user: User) -> None:
        """Commit the task's resource to CLEANING on task start. Targets
        already flagged maintenance keep that state — the legal transition
        table decides; an illegal flag is skipped, not forced."""
        from app.domain.resource_events import SRC_TASK_START
        from app.services.resource_state import ResourceStateService

        state = ResourceStateService(self.session)

        async def _try(resource_type: str, rid: uuid.UUID) -> None:
            try:
                await state.transition(
                    resource_type, rid, "cleaning", user=user,
                    source=SRC_TASK_START, task_id=task.id,
                    reason=f"Cleaning task started "
                           f"({task.ticket_number or task.title})",
                )
            except (ConflictErr, ValidationErr, NotFoundErr):
                return  # resource already in a higher-priority state

        if task.room_id:
            await _try("room", task.room_id)
        elif task.dorm_id:
            await _try("dorm", task.dorm_id)
            if task.bed_ids:
                bed_ids = [uuid.UUID(b) for b in task.bed_ids]
            else:
                res = await self.session.execute(
                    select(Bed.id).where(
                        Bed.dorm_id == task.dorm_id,
                        Bed.status != "inactive",
                    )
                )
                bed_ids = list(res.scalars())
            for bid in bed_ids:
                await _try("bed", bid)
        elif task.washroom_id:
            await _try("washroom", task.washroom_id)

    async def complete_task(
        self, user: User, task_id: uuid.UUID, payload: TaskCompleteRequest
    ) -> dict:
        task = await self._get_task(user, task_id)
        self._require_assignee(user, task)
        if user.role == UserRole.EMPLOYEE:
            # Employee completion must pass through the review gate —
            # /submit → PENDING_CHECK → Super Admin approval.
            from app.dependencies.auth import Forbidden
            raise Forbidden(
                "Employees submit work for approval; direct completion "
                "requires the Super Admin role."
            )
        if task.status in {"completed", "cancelled", "submitted", "abandoned"}:
            raise ConflictErr(f"Task is already {task.status}.")
        _raise_if_expired(task)
        self._require_resource_authority(user, task)
        urls = await self._evidence_urls(task, payload.photo_urls)
        if not urls:
            raise ValidationErr(
                "At least one photo is required to complete a task.",
                field="photo_urls",
            )
        task.status = "completed"
        task.completed_at = datetime.now(timezone.utc)
        await self._stamp_fixture_cleaned(task)
        event = self._history(task, "completed", user, note=payload.note,
                              photos=urls)
        await self.session.flush()
        submission = await self._new_submission(
            task, event, user, status="approved", review_note=payload.note
        )
        await self.session.flush()
        self._record_evidence(task, event, submission, urls, user)

        # Staff completing directly counts as supervisor acknowledgement —
        # the resource derives its status now. An employee's completion does
        # NOT release the room: a supervisor still has to approve (approve
        # accepts 'completed' tasks that still hold a blocked resource).
        if (task.room_id or task.dorm_id or task.washroom_id) and user.role != UserRole.EMPLOYEE:
            await self._refresh_unit(task, user, "approved via complete")

        generated = None
        if task.recurrence and task.task_type == "repetitive":
            generated = await self._next_instance(user, task)
        await self.session.commit()
        result = {"task": task}
        if generated:
            result["generated_task"] = await self._get_task(user, generated.id)
        return result

    async def _next_instance(self, user: User, task: Task) -> Task | None:
        """Create the next occurrence of a repetitive task on completion.

        The occurrence is rolled forward past `now` — completing a stale
        task spawns the NEXT future slot, not an already-overdue instance.
        Returns None once the schedule is exhausted, or when the occurrence
        already exists in the series (scheduler may have spawned it first).
        """
        now = _local_now()
        base = _due_dt(task)
        occ = next_occurrence(task, max(base, now) if base else now)
        if occ is None:
            return None
        return await self._spawn_instance(
            task, _occurrence_due_string(task, occ), actor=user.name,
            occ=occ,
        )

    async def _stamp_occurrence_window(
        self, task: Task, occ_naive: datetime
    ) -> None:
        """Validity window + op-day anchor for one series instance.

        scheduled_for = the occurrence instant; expires_at = the NEXT
        occurrence on the series grid (None once the schedule ends — the
        last instance then falls back to daily rollover). Values are
        naive-IST on the series grid and stored aware-UTC.
        """
        from app.models.company import Company
        from app.models.property import Property
        from app.services.rollover import (
            operational_day_key, parse_day_start,
        )
        task.scheduled_for = occ_naive.replace(
            tzinfo=IST).astimezone(timezone.utc)
        nxt = next_occurrence(task, occ_naive)
        task.expires_at = (
            nxt.replace(tzinfo=IST).astimezone(timezone.utc)
            if nxt else None
        )
        res = await self.session.execute(
            select(Company.operational_day_start)
            .join(Property, Property.company_id == Company.id)
            .where(Property.id == task.property_id)
        )
        task.operational_date = operational_day_key(
            occ_naive, parse_day_start(res.scalar_one_or_none()))

    async def _spawn_instance(
        self, task: Task, due: str, *, actor: str,
        occ: datetime | None = None,
    ) -> Task | None:
        """Clone `task` as the next series occurrence.

        Dedupes on (series, due) — completion and the scheduler sweep can
        race the same slot without producing two rows. Unassigned heads are
        handed to zone round-robin so generated work lands allocated.
        """
        series = task.series_id or task.id
        res = await self.session.execute(
            select(Task.id).where(
                or_(Task.series_id == series, Task.id == series),
                Task.due_date == due,
            )
        )
        if res.scalar_one_or_none() is not None:
            return None

        from app.services.task_location import resolve_task_location
        location = await resolve_task_location(
            self.session, property_id=task.property_id,
            room_id=task.room_id, dorm_id=task.dorm_id,
            washroom_id=task.washroom_id, zone_id=task.zone_id,
        )
        work_type = await self._task_work_type(task)
        emp_id, emp_name = task.employee_id, task.assigned_to_name
        if emp_id is not None:
            source_emp = await self.session.get(Employee, emp_id)
            if (
                source_emp is None
                or not self.alloc.employee_matches_work_type(source_emp, work_type)
            ):
                emp_id, emp_name = None, None
            elif not employee_is_assignable(source_emp):
                emp_id, emp_name = None, None
        batch = None
        amethod = task.allocation_method
        areason = None
        if emp_id is None:
            # unassigned/ineligible head → run the shared round-robin allocator
            # so generated work lands on an active eligible employee, not the
            # deactivated source assignee.
            from app.models.property import Property
            prop = await self.session.get(Property, task.property_id)
            zname = location.zone.name if location.zone else None
            area_id = location.area_id
            aname = location.area.name if location.area else None
            alloc = await self.alloc.allocate(
                None,
                property_id=task.property_id,
                zone_id=location.zone_id,
                zone_name=zname,
                work_type=work_type,
                manager_employee_id=prop.manager_employee_id if prop else None,
                company_id=prop.company_id if prop else None,
                actor_name=actor,
                area_id=area_id,
                area_name=aname,
            )
            batch = alloc.batch
            amethod, areason = alloc.method, alloc.reason
            if alloc.employee:
                emp_id, emp_name = alloc.employee.id, alloc.employee.name

        from app.services.maintenance import next_ticket_number

        new_task = Task(
            property_id=task.property_id,
            ticket_number=await next_ticket_number(self.session, "task"),
            zone_id=location.zone_id,
            area_id=location.area_id,
            room_id=task.room_id,
            room_number=task.room_number,
            dorm_id=task.dorm_id,
            dorm_name=task.dorm_name,
            bed_ids=task.bed_ids,
            washroom_id=task.washroom_id,
            washroom_name=task.washroom_name,
            supervisor_id=task.supervisor_id,
            supervisor_name=task.supervisor_name,
            employee_id=emp_id,
            assigned_to_name=emp_name,
            title=task.title,
            description=task.description,
            task_type="repetitive",
            work_type=task.work_type,
            origin=task.origin or "manual",
            status="assigned" if emp_id else "pending",
            priority=task.priority,
            due_date=due,
            due_time=task.due_time,
            start_time=task.start_time,
            recurrence_start_date=task.recurrence_start_date,
            recurrence_end_date=task.recurrence_end_date,
            recurrence_window_end=task.recurrence_window_end,
            created_by_name=task.created_by_name,
            recurrence=task.recurrence,
            recurrence_interval_days=task.recurrence_interval_days,
            series_id=series,
            allocation_batch_id=batch.id if batch else task.allocation_batch_id,
            allocation_status="auto_assigned" if batch and emp_id
                              else "manually_assigned" if emp_id else "unassigned",
            allocation_method=amethod,
            allocation_reason=areason,
        )
        if occ is not None:
            await self._stamp_occurrence_window(new_task, occ)
        self.session.add(new_task)
        await self.session.flush()
        new_task._resolved_area_id = location.area_id
        self.session.add(TaskHistoryEvent(
            task_id=new_task.id, type="auto_generated",
            actor_name=task.created_by_name or actor,
            note=f"Generated from recurring task '{task.title}'",
        ))
        if emp_id or batch:
            await self.alloc.record(
                property_id=task.property_id, zone_id=location.zone_id,
                batch=batch,
                ticket_kind="task", ticket_id=new_task.id,
                ticket_number=new_task.ticket_number,
                employee_id=emp_id, employee_name=emp_name,
                method=amethod or "manual", reason=areason,
                actor_name=actor,
            )
        if emp_id:
            from app.services.notifications import NotificationService
            await NotificationService(self.session).notify(
                employee_id=emp_id, property_id=new_task.property_id,
                type="task_assigned", title="New Task Assigned",
                body=new_task.title, task_id=new_task.id,
                employee_name=emp_name,
            )
        return new_task

    async def run_due_repetitive(self, now: datetime | None = None) -> dict:
        """Advance every repetitive task series whose next slot has come due.

        Repetitive tasks recur on the clock — an unfinished instance does
        not stop the series (completion also spawns ahead, deduped via
        series_id + due). Only the LATEST missed slot is generated per
        series so a long-stalled chain doesn't dump a backlog.
        """
        now_l = (now or _local_now()).replace(tzinfo=None)
        # Insurance for direct calls bypassing the ordered tick: expire
        # due instances first so a still-open predecessor can't block its
        # successor through uq_tasks_open_room_title.
        from app.services.rollover import RolloverService
        await RolloverService(self.session).expire_due(
            now_l.replace(tzinfo=IST).astimezone(timezone.utc))
        res = await self.session.execute(
            select(Task).where(
                Task.task_type == "repetitive",
                Task.recurrence.is_not(None),
            )
        )
        series: dict[uuid.UUID, list[Task]] = {}
        for t in res.scalars():
            series.setdefault(t.series_id or t.id, []).append(t)

        stats = {"series": 0, "generated": 0}
        for members in series.values():
            head = max(members, key=lambda t: (t.due_date or "", t.created_at))
            if head.status == "cancelled":
                continue  # series deliberately stopped
            stats["series"] += 1
            anchor = _due_dt(head)
            if anchor is None:
                # no due moment at all — anchor the grid at creation time so
                # the series still ticks (first slot = created + interval)
                anchor = (head.created_at.astimezone(IST).replace(tzinfo=None)
                          if head.created_at else now_l)
            # latest occurrence slot that has come due on this series' grid
            occ = None
            o = next_occurrence(head, anchor)
            while o is not None and o <= now_l:
                occ = o
                o = next_occurrence(head, o)
            if occ is None:
                continue
            try:
                if await self._spawn_instance(
                    head, _occurrence_due_string(head, occ),
                    actor="Scheduler", occ=occ,
                ):
                    stats["generated"] += 1
                await self.session.commit()
            except Exception:
                await self.session.rollback()
        return stats

    # ------------------------------------------------------------------
    # Ticket review workflow — submit / approve / reject / reopen
    # ------------------------------------------------------------------

    async def submit_task(
        self, user: User, task_id: uuid.UUID, payload: TaskSubmitRequest
    ) -> Task:
        """Employee submits work for supervisor review → 'submitted'
        (PENDING_CHECK — completion requires Property Manager approval)."""
        from app.services.location import parse_geo

        fix = parse_geo(payload)  # geo fields ride the submit body
        task = await self._get_task(user, task_id)
        self._require_assignee(user, task)
        if task.status == "submitted":
            raise ConflictErr("Task is already submitted for review.")
        if task.status in {"completed", "cancelled", "abandoned"}:
            raise ConflictErr(f"Task is already {task.status}.")
        _raise_if_expired(task)

        urls = await self._evidence_urls(task, payload.photo_urls)
        task.status = "submitted"
        task.submitted_at = datetime.now(timezone.utc)
        event = self._history(task, "submitted", user, note=payload.note,
                              photos=urls)
        await self.session.flush()
        submission = await self._new_submission(task, event, user)
        await self.session.flush()
        self._record_evidence(task, event, submission, urls, user)
        if fix is not None:
            from app.services.location import LocationService
            await LocationService(self.session).record(
                property_id=task.property_id,
                employee_id=user.employee_id, fix=fix,
                source="task_submit", task_id=task.id,
            )
        await self.session.commit()
        return task

    async def approve_task(self, user: User, task_id: uuid.UUID, note=None) -> dict:
        """Supervisor/manager approves a submitted task → 'completed'.

        This is the acknowledgement step — only here does the task's room
        re-derive its status (available only if no other blocking work
        remains). Employees cannot approve their own submissions.
        """
        task = await self._get_task(user, task_id)
        self._require_assignee(user, task)  # assigned employee can't self-approve
        self._require_resource_authority(user, task)
        already_completed = task.status == "completed"
        if already_completed:
            # the review already happened — only a still-blocked resource
            # (employee used /complete directly) can be acknowledged again
            still_blocked = False
            if task.room_id:
                res = await self.session.execute(
                    select(Room.status).where(Room.id == task.room_id)
                )
                still_blocked = res.scalar_one_or_none() in {"cleaning", "maintenance"}
            elif task.dorm_id:
                res = await self.session.execute(
                    select(Dorm.status).where(Dorm.id == task.dorm_id)
                )
                still_blocked = res.scalar_one_or_none() in {"cleaning", "maintenance"}
                if not still_blocked:
                    # the dorm row may not be flagged — check covered beds
                    # (bed_ids NULL = whole-dorm task → all its beds)
                    cond = (Bed.dorm_id == task.dorm_id) if not task.bed_ids \
                        else Bed.id.in_([uuid.UUID(x) for x in task.bed_ids])
                    res = await self.session.execute(
                        select(Bed.status).where(cond)
                    )
                    still_blocked = any(
                        s in {"cleaning", "maintenance"} for s in res.scalars()
                    )
            if not still_blocked:
                raise ConflictErr("Only submitted tasks can be approved.")
        elif task.status != "submitted":
            raise ConflictErr("Only submitted tasks can be approved.")
        if not already_completed:
            task.status = "completed"
            task.completed_at = datetime.now(timezone.utc)
            await self._stamp_fixture_cleaned(task)
            submission = self._latest_pending_submission(task)
            if submission:
                submission.status = "approved"
                submission.reviewed_at = datetime.now(timezone.utc)
                submission.reviewed_by_id = user.id
                submission.reviewed_by_name = user.name
                submission.review_comment = note
        self._history(task, "approved", user, note=note)
        if not already_completed and task.employee_id:
            from app.services.notifications import NotificationService
            await NotificationService(self.session).notify(
                employee_id=task.employee_id,
                property_id=task.property_id,
                type="submission_approved", title="Submission Approved",
                body=f"Your submission for '{task.title}' was approved.",
                task_id=task.id, employee_name=task.assigned_to_name,
            )

        # Supervisor acknowledgement → the resource re-derives its status
        # from remaining blocking work (other tickets keep it unavailable).
        if task.room_id or task.dorm_id or task.washroom_id:
            await self._refresh_unit(task, user, "supervisor approved")

        generated = None
        if not already_completed and task.recurrence \
                and task.task_type == "repetitive":
            generated = await self._next_instance(user, task)
        await self.session.commit()
        result = {"task": task}
        if generated:
            result["generated_task"] = await self._get_task(user, generated.id)
        return result

    async def reject_task(
        self, user: User, task_id: uuid.UUID, reason: str
    ) -> Task:
        """Supervisor rejects a submission → 'reopened' for the assignee."""
        task = await self._get_task(user, task_id)
        self._require_assignee(user, task)
        self._require_resource_authority(user, task)
        if task.status != "submitted":
            raise ConflictErr("Only submitted tasks can be rejected.")
        task.status = "reopened"
        task.submitted_at = None
        submission = self._latest_pending_submission(task)
        if submission:
            submission.status = "disapproved"
            submission.reviewed_at = datetime.now(timezone.utc)
            submission.reviewed_by_id = user.id
            submission.reviewed_by_name = user.name
            submission.review_comment = reason
        self._history(task, "rejected", user, note=reason)
        if task.employee_id:
            from app.services.notifications import NotificationService
            body = f"Your submission for '{task.title}' was sent back."
            if reason:
                body = f"{body} Reason: {reason}"
            await NotificationService(self.session).notify(
                employee_id=task.employee_id,
                property_id=task.property_id,
                type="submission_disapproved",
                title="Submission Disapproved",
                body=body, task_id=task.id,
                employee_name=task.assigned_to_name,
            )
        if task.room_id or task.dorm_id or task.washroom_id:
            await self._refresh_unit(task, user, "work rejected — reopened")
        await self.session.commit()
        return task

    async def delete_completion_image(
        self, user: User, task_id: uuid.UUID, image_id: uuid.UUID
    ) -> Task:
        """Permanently remove one evidence object without changing the task's
        review state. Managers only — the route uses the staff dependency."""
        task = await self._get_task(user, task_id)
        image = next(
            (i for i in task.completion_images if i.id == image_id), None
        )
        if image is None:
            raise NotFoundErr("Completion image not found.")

        event = await self.session.get(TaskHistoryEvent, image.history_event_id) \
            if image.history_event_id else None
        if event and event.photos:
            photos = list(event.photos)
            try:
                photos.remove(image.url)
                event.photos = photos
            except ValueError:
                pass

        storage_key = image.storage_key or storage_key_from_url(image.url)
        await self.session.delete(image)
        # Keep the loaded collections authoritative — no trailing refetch.
        task.completion_images.remove(image)
        owning_sub = next(
            (s for s in task.completion_submissions
             if s.id == image.submission_id), None,
        )
        if owning_sub is not None \
                and "images" not in sa_inspect(owning_sub).unloaded:
            try:
                owning_sub.images.remove(image)
            except ValueError:
                pass
        self._history(
            task, "evidence_deleted", user,
            note=f"Completion image {image.file_name or image.url} removed.",
        )
        await self.session.commit()

        if storage_key:
            try:
                await get_storage().delete(storage_key)
            except Exception as exc:
                logger.warning(
                    "Completion image %s deleted from task %s but object cleanup "
                    "failed: %s", image_id, task_id, exc,
                )
        return task

    async def reopen_task(self, user: User, task_id: uuid.UUID, note=None) -> Task:
        """Manually reopen a completed/cancelled task."""
        task = await self._get_task(user, task_id)
        _raise_if_expired(task)
        if task.status not in {"completed", "cancelled", "abandoned"}:
            raise ConflictErr(f"Cannot reopen a {task.status} task.")
        task.status = "assigned" if task.employee_id else "pending"
        task.completed_at = None
        task.abandoned_at = None
        task.abandoned_reason = None
        task.abandoned_from_status = None
        task.operational_date = None
        self._history(task, "reopened", user, note=note)
        if task.room_id or task.dorm_id or task.washroom_id:
            await self._refresh_unit(task, user, "task reopened")
        await self.session.commit()
        return task

    async def request_redo(
        self, user: User, task_id: uuid.UUID, note: str | None
    ) -> Task:
        task = await self._get_task(user, task_id)
        # Request-redo is staff orchestration (spec §13) — employees rework
        # after a supervisor rejects; they never requeue themselves.
        if user.role not in (UserRole.SUPER_ADMIN, UserRole.PROPERTY_MANAGER):
            from app.dependencies.auth import Forbidden
            raise Forbidden()
        # redo is only meaningful for active/queued work — a submitted task
        # goes through reject; completed/cancelled go through reopen.
        if task.status in {"submitted", "completed", "cancelled", "abandoned"}:
            raise ConflictErr(
                f"Cannot request a redo on a {task.status} task — "
                "use reject (submitted) or reopen (completed/cancelled)."
            )
        task.status = "pending"
        self._history(task, "redo_requested", user, note=note)
        if task.room_id or task.dorm_id or task.washroom_id:
            await self._refresh_unit(task, user, "redo requested")
        await self.session.commit()
        return task

    def _require_resource_authority(self, user: User, task: Task) -> None:
        """Review decisions that release a resource are Super-Admin-only
        (spec §13). Tasks with no resource target stay approvable by any
        staff member."""
        has_target = bool(task.room_id or task.dorm_id or task.washroom_id)
        if has_target and user.role != UserRole.SUPER_ADMIN:
            from app.dependencies.auth import Forbidden
            raise Forbidden(
                "Approving work on a physical resource requires the "
                "Super Admin role."
            )

    async def _refresh_unit(self, task: Task, user: User, trigger: str) -> None:
        """Re-derive the task's unit status (room/dorm+beds/washroom) via
        the central ResourceStateService and record transitions on this
        task's history."""
        from app.services.resource_state import ResourceStateService

        def _audit(note: str) -> None:
            task.history.append(TaskHistoryEvent(
                type="room_status_changed", actor_name=user.name, note=note,
            ))

        state = ResourceStateService(self.session)
        trig = f"{trigger} ({task.ticket_number or task.title})"
        if task.room_id:
            await state.derive(
                "room", task.room_id, release_to="available", user=user,
                reason=trig, task_id=task.id, audit=_audit,
            )
        elif task.dorm_id:
            # derive releases each covered bed that has no remaining blocker
            await state.derive(
                "dorm", task.dorm_id, release_to="available", user=user,
                reason=trig, task_id=task.id, audit=_audit,
            )
        elif task.washroom_id:
            await state.derive(
                "washroom", task.washroom_id, release_to="available",
                user=user, reason=trig, task_id=task.id, audit=_audit,
            )

    async def reassign(
        self, user: User, task_id: uuid.UUID, employee_uid: uuid.UUID | None
    ) -> Task:
        task = await self._get_task(user, task_id)
        emp_id, emp_name = await self._employee_or_none(
            employee_uid, task.property_id,
            work_type=await self._task_work_type(task),
        )
        prev_id, prev_name = task.employee_id, task.assigned_to_name
        task.employee_id = emp_id
        task.assigned_to_name = emp_name
        task.allocation_status = (
            "manually_assigned" if emp_id else "unassigned"
        )
        task.allocation_method = "reassign" if prev_id else "manual"
        task.allocation_reason = None
        self._history(task, "reassigned", user,
                      note=f"Reassigned to {emp_name or 'unassigned'}")
        # Audited through the same allocation history — manual overrides
        # never touch the round-robin pointer.
        await self.alloc.record(
            property_id=task.property_id, zone_id=task.zone_id, batch=None,
            ticket_kind="task", ticket_id=task.id,
            ticket_number=task.ticket_number,
            employee_id=emp_id, employee_name=emp_name,
            previous_employee_id=prev_id, previous_employee_name=prev_name,
            method=task.allocation_method, actor_name=user.name,
        )
        if emp_id:
            from app.services.notifications import NotificationService
            await NotificationService(self.session).notify(
                employee_id=emp_id, property_id=task.property_id,
                type="task_reassigned" if prev_id else "task_assigned",
                title="Task Reassigned" if prev_id else "New Task Assigned",
                body=task.title, task_id=task.id, employee_name=emp_name,
            )
        await self.session.commit()
        return task
