"""Notifications, push-device registrations, and location captures.

Notification — one row per employee-facing event (task assigned,
submission reviewed, ticket assigned...). task_id / ticket_id are plain
UUIDs (no FK) on purpose — deleting a task or ticket must never destroy
the employee's notification history (resource_state_events precedent).

DeviceRegistration — one row per (employee, device_id); the push_token
is a credential and NEVER leaves the server (serializers omit it).
user_id scopes logout teardown — revoking a session deactivates that
user's devices without touching other users on a shared employee link.

LocationEvent — append-only geo capture stamped by the SERVER at
attendance/task actions. recorded_at is server-only; client clocks are
never trusted. `flagged` is app-set (outside_geofence | low_accuracy) —
the row records the fix even when it fails policy; flag, don't reject.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer,
    String, UniqueConstraint, Uuid, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base

NOTIFICATION_TYPES = (
    "task_assigned",
    "task_reassigned",
    "task_cancelled",
    "task_due_soon",
    "task_overdue",
    "submission_approved",
    "submission_disapproved",
    "ticket_assigned",
    "ticket_disapproved",
)

DEVICE_PLATFORMS = ("android", "ios", "web")

LOCATION_SOURCES = (
    "attendance_start",
    "attendance_end",
    "task_start",
    "task_submit",
)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Denormalized for audit-survival — survives employee deletion like
    # attendance_days.employee_name.
    employee_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    # Plain UUIDs, no FK — see module docstring.
    task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(String(500), nullable=False)
    is_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "type IN ("
            + ", ".join(f"'{t}'" for t in NOTIFICATION_TYPES)
            + ")",
            name="ck_notifications_type",
        ),
        # Badge count + list ordering — the two hot read paths.
        Index("ix_notif_employee_read", "employee_id", "is_read"),
        Index("ix_notif_employee_created", "employee_id", "created_at"),
        Index("ix_notif_property_created", "property_id", "created_at"),
    )


class DeviceRegistration(Base):
    __tablename__ = "device_registrations"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Client-chosen stable install id — upsert key with employee_id.
    device_id: Mapped[str] = mapped_column(String(128), nullable=False)
    push_token: Mapped[str] = mapped_column(String(255), nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    app_version: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "employee_id", "device_id", name="uq_device_employee_device",
        ),
        CheckConstraint(
            "platform IN ('android', 'ios', 'web')",
            name="ck_device_platform",
        ),
        Index("ix_device_employee_active", "employee_id", "is_active"),
    )


class LocationEvent(Base):
    __tablename__ = "location_events"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Plain UUIDs, no FK — captures survive task/day deletion.
    task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    attendance_day_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, nullable=True
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    accuracy_meters: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    # App-set flags only — e.g. 'outside_geofence', 'low_accuracy'.
    flagged: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # SERVER timestamp — client-reported times are never trusted.
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "source IN ("
            + ", ".join(f"'{s}'" for s in LOCATION_SOURCES)
            + ")",
            name="ck_location_events_source",
        ),
        Index("ix_location_employee_time", "employee_id", "recorded_at"),
        Index("ix_location_property_time", "property_id", "recorded_at"),
    )
