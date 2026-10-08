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

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.audit import AuditEvent
from app.models.notifications import (
    DEVICE_PLATFORMS,
    DeviceRegistration,
    Notification,
)
from app.models.user import User
from app.services.push import get_push_provider
from app.services.structure import NotFoundErr, ValidationErr

logger = get_logger(__name__)


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
        await self._dispatch(notification)
        return notification

    async def _dispatch(self, notification: Notification) -> None:
        """Push to the employee's ACTIVE devices. Every failure mode is
        swallowed to a warning — the in-app row is the source of truth."""
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
            data = {"type": notification.type}
            if notification.task_id:
                data["task_uid"] = str(notification.task_id)
            if notification.ticket_id:
                data["ticket_uid"] = str(notification.ticket_id)
            provider = self._push or get_push_provider()
            result = await provider.send(
                tokens, notification.title, notification.body, data,
            )
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
