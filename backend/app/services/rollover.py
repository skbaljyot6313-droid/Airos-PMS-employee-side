"""Operational-day rollover — abandon unfinished tasks at the day boundary.

An operational day runs from `company.operational_day_start` (HH:MM, IST)
to the same time the next calendar day. When the clock crosses that
boundary every still-open task anchored to a PAST operational day is
marked `abandoned` with the full audit trail stamped on the row and an
`abandoned` TaskHistoryEvent.

Safety model:
  * Conditional UPDATE — a row is only abandoned while its status is in
    OPEN_STATUSES, so a task completed (or cancelled) between the
    candidate scan and the update is untouched. Deterministic under a
    completion race.
  * Idempotent — abandoned rows are no longer in the open set, so
    re-running the sweep is a no-op; no duplicate history events.
  * Tick-friendly — called from the embedded scheduler loop and the arq
    generation_tick; double execution is harmless by construction.

Maintenance tickets are deliberately NOT touched here — a ticket records
a real-world defect that persists across operational days (carry-forward
policy). Their daily history is reconstructed window-wise by
`services/maintenance_analysis.py` from the event stream instead.

This module ALSO owns the recurring-occurrence expiry sweep
(`expire_due`) — a deliberately DISTINCT concept from the daily rollover:

  * Daily rollover (REASON_SYSTEM_DAILY_ROLLOVER) closes live work whose
    operational DAY has ended.
  * Occurrence expiry (REASON_NEXT_SCHEDULED_OCCURRENCE) closes a
    recurring instance whose own validity window (`expires_at`) has
    ended — i.e. the next scheduled boundary of its template/series has
    arrived. `expires_at` is stamped at generation from the recurrence
    interval and is NEVER extended by scheduler downtime.

The tick runs expiry BEFORE generation, so a still-open predecessor is
abandoned before the next occurrence is inserted — an unfinished
instance can never block its successor.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import String, and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.company import Company
from app.models.property import Property
from app.models.task import Task, TaskHistoryEvent

logger = get_logger("app.rollover")

IST = ZoneInfo("Asia/Kolkata")

# Task statuses the rollover may close — open, non-terminal lifecycle
# states. Mirrors the non-terminal side of BLOCKING_TASK plus 'submitted'
# (still unfinished when the day ends) minus 'scheduled' (an automated
# rule waiting to trigger is a template, not live work).
OPEN_STATUSES = frozenset({
    "pending", "assigned", "in_progress", "submitted", "reopened",
    "overdue",
})

# Occurrence expiry is narrower — a 'submitted' instance is parked in the
# human review queue; the reviewer decides its fate, not the clock.
EXPIRABLE_STATUSES = OPEN_STATUSES - {"submitted"}

REASON = "SYSTEM_DAILY_ROLLOVER"
REASON_NEXT_OCCURRENCE = "NEXT_SCHEDULED_OCCURRENCE"

DEFAULT_DAY_START = "06:00"


def parse_day_start(value: str | None) -> time:
    """'HH:MM' → time; invalid/None falls back to the 06:00 default."""
    if not value:
        return time(6, 0)
    try:
        hh, mm = value.split(":")
        h, m = int(hh), int(mm)
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError
        return time(h, m)
    except (ValueError, AttributeError):
        return time(6, 0)


def operational_day_key(local_dt: datetime, start: time) -> str:
    """YYYY-MM-DD key of the operational day containing `local_dt`.

    `local_dt` is a naive-IST or IST-aware wall-clock instant. Before the
    configured start time the instant belongs to the previous day.
    """
    d = local_dt.date()
    if local_dt.time() < start:
        d -= timedelta(days=1)
    return d.isoformat()


def current_operational_day(now_utc: datetime, start: time) -> str:
    """Op-day key the current instant belongs to."""
    return operational_day_key(now_utc.astimezone(IST), start)


def operational_day_bounds(
    now_utc: datetime, start: time
) -> tuple[datetime, datetime]:
    """UTC [start, end) of the operational day containing `now_utc`."""
    local = now_utc.astimezone(IST)
    s = local.replace(
        hour=start.hour, minute=start.minute, second=0, microsecond=0
    )
    if local < s:
        s -= timedelta(days=1)
    return (
        s.astimezone(timezone.utc),
        (s + timedelta(days=1)).astimezone(timezone.utc),
    )


def _task_anchor_key(task: Task, start: time) -> str | None:
    """Operational-day key a task belongs to (for rollover + analysis).

    Priority: stamped operational_date > due_date > created_at.
      * operational_date — set by rollover; authoritative for abandoned rows.
      * due_date 'YYYY-MM-DD' — the calendar date is the op-day key.
      * due_date ISO timestamp — naive-IST wall clock (template scheduler
        convention); an aware value is converted to IST.
      * created_at — UTC instant converted to IST.
    """
    if task.operational_date:
        return task.operational_date
    due = (task.due_date or "").strip()
    if due:
        if "T" not in due and len(due) >= 10:
            return due[:10]
        try:
            dt = datetime.fromisoformat(due.replace("Z", "+00:00"))
        except ValueError:
            dt = None
        if dt is not None:
            local = dt.astimezone(IST) if dt.tzinfo else dt
            return operational_day_key(local.replace(tzinfo=None), start)
    if task.created_at is not None:
        created = task.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return operational_day_key(created.astimezone(IST), start)
    return None


class RolloverService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def run(self, now: datetime | None = None) -> dict:
        """Abandon unfinished tasks whose operational day has ended.

        One pass over every company; each company's own configured day
        start applies. Returns per-company counts for the scheduler log.
        """
        now_utc = now or datetime.now(timezone.utc)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)

        res = await self.session.execute(select(Company))
        companies = list(res.scalars())
        stats = {"companies": 0, "abandoned": 0}
        for company in companies:
            start = parse_day_start(company.operational_day_start)
            current_key = current_operational_day(now_utc, start)
            stats["companies"] += 1
            stats["abandoned"] += await self._roll_company(
                company, current_key, start, now_utc
            )

        if stats["abandoned"]:
            await self.session.commit()
            logger.info("Daily rollover: %s", stats)
        return stats

    async def _roll_company(
        self, company: Company, current_key: str, start: time,
        now_utc: datetime,
    ) -> int:
        res = await self.session.execute(
            select(Task)
            .join(Property, Task.property_id == Property.id)
            .where(
                Property.company_id == company.id,
                Task.status.in_(OPEN_STATUSES),
                # Rows whose occurrence window already ended are handled
                # here too — expire_due normally catches them first, but
                # a missed tick must not leak them past the day boundary.
                or_(
                    Task.expires_at.is_(None),
                    Task.expires_at <= now_utc,
                ),
            )
        )
        abandoned = 0
        for task in res.scalars():
            key = _task_anchor_key(task, start)
            if key is None or key >= current_key:
                continue
            from_status = task.status
            # Conditional UPDATE — deterministic under a completion race:
            # the row only transitions while still in an open status.
            res2 = await self.session.execute(
                update(Task)
                .where(Task.id == task.id, Task.status.in_(OPEN_STATUSES))
                .values(
                    status="abandoned",
                    abandoned_at=now_utc,
                    abandoned_reason=REASON,
                    abandoned_from_status=from_status,
                    operational_date=key,
                )
            )
            if res2.rowcount:
                self.session.add(TaskHistoryEvent(
                    task_id=task.id,
                    type="abandoned",
                    actor_name="System",
                    note=(
                        f"Daily rollover: unfinished '{from_status}' task "
                        f"closed at the start of operational day "
                        f"{current_key}."
                    ),
                ))
                if task.employee_id:
                    from app.services.notifications import (
                        NotificationService,
                    )
                    await NotificationService(self.session).notify(
                        employee_id=task.employee_id,
                        property_id=task.property_id,
                        type="task_cancelled",
                        title="Task Cancelled",
                        body=(
                            f"'{task.title}' was closed by the daily "
                            "rollover."
                        ),
                        task_id=task.id,
                        employee_name=task.assigned_to_name,
                    )
                abandoned += 1
        return abandoned

    async def expire_due(
        self,
        now: datetime | None = None,
        *,
        template_id=None,
        target: dict | None = None,
        boundary: datetime | None = None,
        include_windowless: bool = False,
    ) -> dict:
        """Abandon recurring instances whose validity window has ended.

        `expires_at` is the NEXT scheduled boundary — stamped at
        generation, never pushed out by scheduler downtime. The sweep is
        idempotent (abandoned rows leave the expirable set) and runs
        BEFORE generation in every tick so an unfinished predecessor
        releases its (property, room, title) slot and cannot block the
        next occurrence. Independent of target expansion — a zero-target
        occurrence still expires its predecessor.

        `template_id` scopes the pass to one template's instances (used
        when generation is invoked directly, outside the ordered tick).
        `target` narrows it to one expanded-target's predecessor —
        single-target "Generate Now" only supersedes the instance
        covering THAT unit (room/dorm/bed/washroom/zone), not the other
        targets of the same occurrence.
        `boundary` overrides the expiry cutoff — manual "Generate Now"
        expires predecessors up to the occurrence being generated while
        still stamping `abandoned_at` with the real time.
        `include_windowless` also matches open rows with `expires_at IS
        NULL` — legacy instances generated before occurrence windows
        existed. Scoped calls (template generation, Generate Now) use it
        because a windowless open task in the same template+target scope
        is necessarily a predecessor and would otherwise block the next
        occurrence forever (only daily rollover could clear it). The
        global tick sweep leaves it off — windowless rows stay under
        daily-rollover governance.
        """
        now_utc = now or datetime.now(timezone.utc)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)
        cutoff = boundary or now_utc
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)

        window_pred = Task.expires_at <= cutoff
        if include_windowless:
            window_pred = window_pred | Task.expires_at.is_(None)
        q = (
            select(Task, Property.company_id)
            .join(Property, Task.property_id == Property.id)
            .where(
                window_pred,
                Task.status.in_(EXPIRABLE_STATUSES),
            )
        )
        if template_id is not None:
            q = q.where(Task.template_id == template_id)
        if target is not None:
            q = q.where(_target_clause(target))
        rows = (await self.session.execute(q)).all()
        if not rows:
            return {"expired": 0}

        # Per-company day starts for the stamped operational_date — one
        # query for the whole batch, not one per row.
        cres = await self.session.execute(
            select(Company.id, Company.operational_day_start)
        )
        starts = {cid: parse_day_start(s) for cid, s in cres.all()}

        expired = 0
        for task, company_id in rows:
            from_status = task.status
            res = await self.session.execute(
                update(Task)
                .where(
                    Task.id == task.id,
                    Task.status.in_(EXPIRABLE_STATUSES),
                )
                .values(
                    status="abandoned",
                    abandoned_at=now_utc,
                    abandoned_reason=REASON_NEXT_OCCURRENCE,
                    abandoned_from_status=from_status,
                    operational_date=_occurrence_op_key(
                        task, starts.get(company_id)
                    ),
                )
            )
            if not res.rowcount:
                continue
            self.session.add(TaskHistoryEvent(
                task_id=task.id,
                type="abandoned",
                actor_name="System",
                note="Failed to complete allocated task in said time.",
            ))
            if task.employee_id:
                from app.services.notifications import NotificationService
                await NotificationService(self.session).notify(
                    employee_id=task.employee_id,
                    property_id=task.property_id,
                    type="task_cancelled",
                    title="Task Cancelled",
                    body=(
                        f"'{task.title}' was closed when its scheduled "
                        "window ended."
                    ),
                    task_id=task.id,
                    employee_name=task.assigned_to_name,
                )
            expired += 1
        if expired:
            await self.session.commit()
            logger.info("Occurrence expiry: %d abandoned", expired)
        return {"expired": expired}


def _target_clause(target: dict):
    """Match the task row covering one expanded target — a target dict as
    produced by TemplateService._expand_targets. Zone-level targets
    (common area, empty-zone fallbacks) carry no unit ids, so they match
    the task that is itself unit-less within the zone."""
    if target.get("room_id"):
        return Task.room_id == target["room_id"]
    if target.get("washroom_id"):
        return Task.washroom_id == target["washroom_id"]
    if target.get("bed_id"):
        return and_(
            Task.bed_ids.is_not(None),
            func.cast(Task.bed_ids, String).like(f'%"{target["bed_id"]}"%'),
        )
    if target.get("dorm_id"):
        return and_(
            Task.dorm_id == target["dorm_id"],
            Task.bed_ids.is_(None),
        )
    if target.get("zone_id"):
        return and_(
            Task.zone_id == target["zone_id"],
            Task.room_id.is_(None),
            Task.dorm_id.is_(None),
            Task.washroom_id.is_(None),
        )
    return and_(
        Task.room_id.is_(None),
        Task.dorm_id.is_(None),
        Task.washroom_id.is_(None),
        Task.zone_id.is_(None),
    )


def _occurrence_op_key(task: Task, start: time | None) -> str | None:
    """Operational-day key of the task's scheduled occurrence."""
    sched = task.scheduled_for
    if sched is None:
        return _task_anchor_key(task, start or time(6, 0))
    if sched.tzinfo is None:
        sched = sched.replace(tzinfo=timezone.utc)
    return operational_day_key(
        sched.astimezone(IST), start or time(6, 0)
    )


async def rollover_now(session_factory, now: datetime | None = None):
    """Standalone entry — own session so callers needn't manage one."""
    async with session_factory() as session:
        await RolloverService(session).run(now=now)
