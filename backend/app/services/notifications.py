"""NotificationService + DeviceRegistry — in-app feed, push dispatch,
and device lifecycle.

Conventions (mirrors AttendanceService):
  * notify() persists in ONE flush and does NOT commit — the caller's
    commit keeps the notification atomic with the event that caused it.
  * Push is dispatched AFTER persist; provider failures log a warning
    and are NEVER raised — allocation must not fail on push.
  * audit_events carry lifecycle actions only: notification_read,
    device_registered, device_deactivated (creation rows are the
    notifications themselves, not audit noise).
  * Employee scope is user.employee_id — NULL → 403/404, never widened.
"""

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, exists, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import metrics
from app.core.logging import get_logger
from app.models.audit import AuditEvent
from app.models.maintenance import MaintenanceTicket
from app.models.notifications import (
    DEVICE_PLATFORMS,
    DeviceRegistration,
    Notification,
)
from app.models.task import Task
from app.models.user import User
from app.models.work_allocation import WorkAllocationHistory
from app.services.push import get_push_provider
from app.services.structure import NotFoundErr, ValidationErr

logger = get_logger(__name__)

# Allocation synthesis — the shared work_allocation_history ledger is
# written by the SUPER ADMIN backend (this app's task services are never
# invoked for SA-side assignments). The feed derives rows from it at read
# time; the window bounds the scan and stops pre-feature history from
# flooding a fresh feed.
ALLOCATION_SYNC_WINDOW = timedelta(days=14)
ALLOCATION_SYNC_CAP = 50  # materialized rows per sync — backstop only

# Post-commit push queue — snapshots parked on session.info are drained
# AFTER the business transaction commits (database.py after_commit hook),
# so external FCM HTTPS calls never hold a pool connection hostage.
PUSH_QUEUE = "airos_queued_pushes"


def queue_push(session: AsyncSession, snapshot: dict) -> None:
    session.info.setdefault(PUSH_QUEUE, []).append(snapshot)


def _push_snapshot(n: Notification) -> dict:
    data = {
        "type": n.type,
        "notification_uid": str(n.id),
    }
    if n.task_id:
        data["task_uid"] = str(n.task_id)
    if n.ticket_id:
        data["ticket_uid"] = str(n.ticket_id)
    return {
        "notification_id": str(n.id),
        "employee_id": n.employee_id,
        "title": n.title,
        "body": n.body,
        "data": data,
    }


async def _dispatch_snapshot(session: AsyncSession, snap: dict) -> None:
    """One queued push: token lookup → provider.send → dead-token cleanup.
    Runs on the drain's own session — failures are per-notification and
    never propagate (push must never break committed work)."""
    res = await session.execute(
        select(DeviceRegistration.push_token).where(
            DeviceRegistration.employee_id == snap["employee_id"],
            DeviceRegistration.is_active.is_(True),
        )
    )
    tokens = [t for t in res.scalars() if t]
    if not tokens:
        return
    provider = get_push_provider()
    t0 = time.monotonic()
    try:
        result = await provider.send(
            tokens, snap["title"], snap["body"], snap["data"],
            tag=snap["notification_id"],
        )
    finally:
        metrics.record_ext((time.monotonic() - t0) * 1000)
    dead = getattr(result, "invalid_tokens", None) or []
    if dead:
        await session.execute(
            update(DeviceRegistration)
            .where(DeviceRegistration.push_token.in_(dead))
            .values(is_active=False)
        )
        logger.info(
            "Push: deactivated %d dead registration token(s)", len(dead),
        )


# Bound concurrent drain batches — every commit can schedule one task;
# the semaphore keeps post-commit fan-out from stampeding the provider
# or the connection pool during a notification burst.
_PUSH_DRAIN_SEMAPHORE = asyncio.Semaphore(4)


async def dispatch_queued_pushes(snapshots: list[dict]) -> None:
    """Drain queued push snapshots on a FRESH session after commit.

    Runs as a background task (scheduled by the after_commit hook), so it
    must be fully self-contained and never raise — a dead database or a
    misconfigured provider only costs a warning line. It never touches
    the request-scoped session: a new AsyncSessionLocal is opened here."""
    if not snapshots:
        return
    try:
        from app.core.database import AsyncSessionLocal
    except Exception as exc:  # engine unconfigured (unit-test context)
        logger.warning("push drain unavailable: %s", exc)
        return
    async with _PUSH_DRAIN_SEMAPHORE:
        try:
            async with AsyncSessionLocal() as session:
                for snap in snapshots:
                    try:
                        await _dispatch_snapshot(session, snap)
                    except Exception as exc:
                        logger.warning(
                            "Push dispatch failed for notification %s: %s",
                            snap.get("notification_id"), exc,
                        )
                try:
                    await session.commit()
                except Exception as exc:
                    logger.warning(
                        "push drain token cleanup commit failed: %s", exc,
                    )
        except Exception as exc:
            logger.warning("push drain failed: %s", exc)


def _allocation_notice_parts(kind: str, reassigned: bool) -> tuple[str, str]:
    """(n_type, title) — the single mapping shared by ledger synthesis
    and the SA push endpoint so both emit identical notifications."""
    if kind == "task":
        return (
            "task_reassigned" if reassigned else "task_assigned",
            "Task Reassigned" if reassigned else "New Task Assigned",
        )
    return (
        "ticket_assigned",
        "Maintenance Ticket Reassigned" if reassigned
        else "New Maintenance Ticket",
    )


def _audit(session: AsyncSession, *, user: User, action: str,
           entity_id: uuid.UUID | None, property_id: uuid.UUID | None,
           entity_name: str | None = None, detail: dict | None = None) -> None:
    session.add(AuditEvent(
        property_id=property_id,
        actor_user_id=user.id,
        actor_name=user.name,
        entity_type="notification",
        entity_id=entity_id,
        entity_name=entity_name,
        action=action,
        detail=detail or {},
    ))


class NotificationService:
    def __init__(self, session: AsyncSession, push=None):
        self.session = session
        # Injectable for tests; lazily resolved per-send otherwise so
        # PUSH_PROVIDER settings changes apply without a restart.
        self._push = push

    # ------------------------------------------------------------------
    # Creation — called by work/task/ticket services, never by clients
    # ------------------------------------------------------------------

    async def notify(
        self,
        *,
        employee_id: uuid.UUID | None,
        property_id: uuid.UUID,
        type: str,
        title: str,
        body: str,
        task_id: uuid.UUID | None = None,
        ticket_id: uuid.UUID | None = None,
        employee_name: str | None = None,
    ) -> Notification | None:
        """Persist one notification + best-effort push. Flushes, never
        commits — the caller's commit makes it atomic with its event."""
        if employee_id is None:
            return None
        notification = Notification(
            property_id=property_id,
            employee_id=employee_id,
            employee_name=employee_name,
            task_id=task_id,
            ticket_id=ticket_id,
            type=type,
            title=(title or "")[:200],
            body=(body or "")[:500],
        )
        self.session.add(notification)
        await self.session.flush()
        if self._push is not None:
            # Injected-provider seam (tests) — dispatch inline so callers
            # can assert sends synchronously.
            await self._dispatch(notification)
        else:
            # Production path — the send leaves the transaction entirely:
            # queued snapshots drain post-commit on a fresh session.
            queue_push(self.session, _push_snapshot(notification))
        return notification

    async def _dispatch(self, notification: Notification) -> None:
        """Push to the employee's ACTIVE devices. Every failure mode is
        swallowed to a warning — the in-app row is the source of truth.

        Only reached when a provider was injected (self._push); the
        production path queues for post-commit drain instead, so external
        HTTPS never runs inside an open transaction."""
        try:
            res = await self.session.execute(
                select(DeviceRegistration.push_token).where(
                    DeviceRegistration.employee_id
                    == notification.employee_id,
                    DeviceRegistration.is_active.is_(True),
                )
            )
            tokens = [t for t in res.scalars() if t]
            if not tokens:
                return
            data = {
                "type": notification.type,
                "notification_uid": str(notification.id),
            }
            if notification.task_id:
                data["task_uid"] = str(notification.task_id)
            if notification.ticket_id:
                data["ticket_uid"] = str(notification.ticket_id)
            provider = self._push or get_push_provider()
            t0 = time.monotonic()
            try:
                result = await provider.send(
                    tokens, notification.title, notification.body, data,
                    tag=str(notification.id),
                )
            finally:
                metrics.record_ext((time.monotonic() - t0) * 1000)
            dead = getattr(result, "invalid_tokens", None) or []
            if dead:
                await self.session.execute(
                    update(DeviceRegistration)
                    .where(DeviceRegistration.push_token.in_(dead))
                    .values(is_active=False)
                )
                logger.info(
                    "Push: deactivated %d dead registration token(s)",
                    len(dead),
                )
        except Exception as exc:  # provider must never break the caller
            logger.warning(
                "Push dispatch failed for notification %s: %s",
                notification.id, exc,
            )

    # ------------------------------------------------------------------
    # Employee reads — own rows only
    # ------------------------------------------------------------------

    def _require_employee(self, user: User) -> uuid.UUID:
        from app.dependencies.auth import Forbidden

        if user.employee_id is None:
            raise Forbidden(
                "Your account is not linked to an employee record."
            )
        return user.employee_id

    async def list_notifications(
        self, user: User, *, limit: int = 50, unread_only: bool = False
    ) -> list[Notification]:
        """The caller's own feed, newest first — real LIMIT, not _paged."""
        employee_id = self._require_employee(user)
        q = select(Notification).where(
            Notification.employee_id == employee_id
        )
        if unread_only:
            q = q.where(Notification.is_read.is_(False))
        res = await self.session.execute(
            q.order_by(Notification.created_at.desc()).limit(limit)
        )
        return list(res.scalars())

    # ------------------------------------------------------------------
    # Allocation sync — derive feed rows from the shared ledger
    # ------------------------------------------------------------------

    async def sync_assignment_notifications(self, user: User) -> int:
        """Materialize notifications for allocations made OUTSIDE this
        backend — SA assigns work by writing the shared
        work_allocation_history ledger directly, so this app's notify()
        paths never see those events.

        Dedupe rule: a same-kind notification with created_at >= the
        ledger event's created_at already covers it — this app's own
        notify() calls (which run AFTER the ledger write in the same
        commit) satisfy it, so double emission is impossible.
        Synthesized rows are stamped WITH the event's created_at, not
        now() — the feed orders by when the work was allocated, and a
        later same-second event is not swallowed by coarse clock
        resolution. Only events whose ticket is still assigned to the
        caller notify — reassigned-away work stays silent. Commits only
        when rows were created; returns the count."""
        employee_id = self._require_employee(user)
        cutoff = datetime.now(timezone.utc) - ALLOCATION_SYNC_WINDOW
        created = await self._sync_allocations(employee_id, cutoff)
        if created:
            await self.session.commit()
            logger.info(
                "Allocation sync: %d notification(s) for employee %s",
                created, employee_id,
            )
        return created

    async def _sync_allocations(
        self, employee_id: uuid.UUID, cutoff: datetime
    ) -> int:
        """One round trip for both ledger kinds — task and maintenance
        branches UNIONed with a `kind` discriminator (was two sequential
        queries; each costs a full remote RTT)."""
        from sqlalchemy import literal, union_all

        def _branch(entity, assign_col, link_col, types, subject_col,
                   kind):
            return (
                select(
                    WorkAllocationHistory.ticket_id,
                    WorkAllocationHistory.property_id,
                    WorkAllocationHistory.employee_name,
                    WorkAllocationHistory.previous_employee_id,
                    WorkAllocationHistory.created_at,
                    subject_col.label("subject"),
                    literal(kind).label("kind"),
                )
                .join(
                    entity,
                    and_(
                        entity.id == WorkAllocationHistory.ticket_id,
                        assign_col == employee_id,
                    ),
                )
                .where(
                    WorkAllocationHistory.ticket_kind == kind,
                    WorkAllocationHistory.employee_id == employee_id,
                    WorkAllocationHistory.created_at >= cutoff,
                    ~exists().where(
                        Notification.employee_id == employee_id,
                        link_col == WorkAllocationHistory.ticket_id,
                        Notification.type.in_(types),
                        Notification.created_at
                        >= WorkAllocationHistory.created_at,
                    ),
                )
            )

        u = union_all(
            _branch(Task, Task.employee_id, Notification.task_id,
                    ("task_assigned", "task_reassigned"),
                    Task.title, "task"),
            _branch(MaintenanceTicket, MaintenanceTicket.assigned_to,
                    Notification.ticket_id, ("ticket_assigned",),
                    MaintenanceTicket.issue, "maintenance"),
        ).subquery()
        res = await self.session.execute(
            select(u).order_by(u.c.created_at).limit(ALLOCATION_SYNC_CAP)
        )
        count = 0
        for row in res.all():
            n_type, title = _allocation_notice_parts(
                row.kind, row.previous_employee_id is not None
            )
            n = await self.notify(
                employee_id=employee_id,
                property_id=row.property_id,
                type=n_type,
                title=title,
                body=row.subject or "A work item was assigned to you.",
                task_id=row.ticket_id if row.kind == "task" else None,
                ticket_id=(
                    row.ticket_id if row.kind == "maintenance" else None
                ),
                employee_name=row.employee_name,
            )
            # Stamp the row at the event's instant — see method docstring.
            if n is not None:
                n.created_at = row.created_at
            count += 1
        return count

    async def notify_allocation_event(
        self,
        *,
        ticket_kind: str,
        ticket_id: uuid.UUID,
        employee_id: uuid.UUID,
        employee_name: str | None = None,
        previous_employee_id: uuid.UUID | None = None,
        event_created_at: datetime | None = None,
    ) -> Notification | None:
        """Server-to-server allocation event pushed by the SA backend
        (POST /admin/notify-allocation). Unlike ledger synthesis this
        fires at allocation time — real-time push becomes possible.

        The event is honored only while the ticket is still assigned to
        that employee — a torn or stale SA-side event never notifies.
        Dedupe: an existing same-kind row at-or-after the event's
        timestamp already covers it (mirrors synthesis), or ANY such row
        when no timestamp is supplied."""
        if ticket_kind == "task":
            entity, assign_col = Task, Task.employee_id
            link_col, types = Notification.task_id, (
                "task_assigned", "task_reassigned"
            )
            subject_col = Task.title
        elif ticket_kind == "maintenance":
            entity = MaintenanceTicket
            assign_col = MaintenanceTicket.assigned_to
            link_col, types = Notification.ticket_id, ("ticket_assigned",)
            subject_col = MaintenanceTicket.issue
        else:
            raise ValidationErr(
                "ticket_kind must be 'task' or 'maintenance'.",
                field="ticket_kind",
            )
        res = await self.session.execute(
            select(subject_col, entity.property_id, assign_col).where(
                entity.id == ticket_id
            )
        )
        row = res.first()
        if row is None or row[2] != employee_id:
            raise NotFoundErr("Work item not found.")
        subject, property_id, _ = row

        covered = exists().where(
            Notification.employee_id == employee_id,
            link_col == ticket_id,
            Notification.type.in_(types),
        )
        if event_created_at is not None:
            covered = covered.where(
                Notification.created_at >= event_created_at
            )
        if (await self.session.execute(select(covered))).scalar():
            return None

        n_type, title = _allocation_notice_parts(
            ticket_kind, previous_employee_id is not None
        )
        n = await self.notify(
            employee_id=employee_id,
            property_id=property_id,
            type=n_type,
            title=title,
            body=subject or "A work item was assigned to you.",
            task_id=ticket_id if ticket_kind == "task" else None,
            ticket_id=ticket_id if ticket_kind == "maintenance" else None,
            employee_name=employee_name,
        )
        if n is not None:
            n.created_at = event_created_at or n.created_at
        await self.session.commit()
        return n

    async def unread_count(self, user: User) -> int:
        employee_id = self._require_employee(user)
        res = await self.session.execute(
            select(func.count()).select_from(Notification).where(
                Notification.employee_id == employee_id,
                Notification.is_read.is_(False),
            )
        )
        return int(res.scalar_one())

    async def mark_read(
        self, user: User, notification_id: uuid.UUID
    ) -> Notification:
        """Own rows only — another employee's notification is invisible
        (404, never a leak). Idempotent: an already-read row returns
        as-is without a second audit entry."""
        notification = await self.session.get(Notification, notification_id)
        if (
            notification is None
            or user.employee_id is None
            or notification.employee_id != user.employee_id
        ):
            raise NotFoundErr("Notification not found.")
        if notification.is_read:
            return notification
        notification.is_read = True
        notification.read_at = datetime.now(timezone.utc)
        _audit(
            self.session, user=user, action="notification_read",
            entity_id=notification.id,
            property_id=notification.property_id,
            entity_name=notification.title,
            detail={"type": notification.type},
        )
        await self.session.commit()
        return notification


class DeviceRegistry:
    """Push-device lifecycle — upsert on (employee_id, device_id)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    def _require_employee(self, user: User) -> uuid.UUID:
        from app.dependencies.auth import Forbidden

        if user.employee_id is None:
            raise Forbidden(
                "Your account is not linked to an employee record."
            )
        return user.employee_id

    async def _find(
        self, employee_id: uuid.UUID, device_id: str
    ) -> DeviceRegistration | None:
        res = await self.session.execute(
            select(DeviceRegistration).where(
                DeviceRegistration.employee_id == employee_id,
                DeviceRegistration.device_id == device_id,
            )
        )
        return res.scalar_one_or_none()

    async def register(
        self,
        user: User,
        *,
        device_id: str,
        push_token: str,
        platform: str,
        app_version: str | None = None,
    ) -> DeviceRegistration:
        """Upsert by (employee_id, device_id) — the unique constraint is
        the race backstop; a losing insert re-selects the winner."""
        employee_id = self._require_employee(user)
        platform = (platform or "").strip().lower()
        if platform not in DEVICE_PLATFORMS:
            raise ValidationErr(
                "platform must be one of: " + ", ".join(DEVICE_PLATFORMS) + ".",
                field="platform",
            )
        device = await self._find(employee_id, device_id)
        if device is None:
            device = DeviceRegistration(
                employee_id=employee_id,
                device_id=device_id,
                push_token=push_token,
                platform=platform,
            )
            self.session.add(device)
            try:
                async with self.session.begin_nested():
                    await self.session.flush()
            except IntegrityError:
                # Concurrent register won the (employee, device) slot —
                # expunge the loser (get_or_create_day convention) and
                # take the winner's row.
                if device in self.session:
                    self.session.expunge(device)
                device = await self._find(employee_id, device_id)
                if device is None:  # pragma: no cover — winner rolled back
                    raise
        device.user_id = user.id
        device.push_token = push_token
        device.platform = platform
        device.app_version = app_version
        device.is_active = True
        device.last_seen_at = datetime.now(timezone.utc)
        _audit(
            self.session, user=user, action="device_registered",
            entity_id=device.id, property_id=user.property_id,
            entity_name=device_id,
            detail={"platform": platform, "app_version": app_version},
        )
        await self.session.commit()
        return device

    async def unregister(
        self, user: User, *, device_id: str
    ) -> DeviceRegistration | None:
        """Deactivate the caller's own device — idempotent; an unknown
        device_id is a no-op (logout paths must not 404)."""
        employee_id = self._require_employee(user)
        device = await self._find(employee_id, device_id)
        if device is None or not device.is_active:
            return device
        device.is_active = False
        _audit(
            self.session, user=user, action="device_deactivated",
            entity_id=device.id, property_id=user.property_id,
            entity_name=device_id, detail={"platform": device.platform},
        )
        await self.session.commit()
        return device

    async def deactivate_for_user(self, user_id: uuid.UUID) -> int:
        """Logout teardown — every active registration owned by this
        USER (not the employee link) goes inactive. Flush only; the
        caller commits with the token revocation."""
        res = await self.session.execute(
            update(DeviceRegistration)
            .where(
                DeviceRegistration.user_id == user_id,
                DeviceRegistration.is_active.is_(True),
            )
            .values(is_active=False)
        )
        return res.rowcount or 0
