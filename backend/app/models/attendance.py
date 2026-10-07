"""Attendance — workday sessions, break segments, and leave requests.

One AttendanceDay per (employee, operational date). The operational date
is an IST wall-clock 'YYYY-MM-DD' string computed server-side from the
company's configured `operational_day_start` — a shift that runs past
midnight stays on the same key (see services/rollover.py).

Status vocab (app-level strings, no PG enum — codebase convention):
    present | absent | week_off | leave

attendance_breaks are contiguous segments of an open day; at most one may
be open (ended_at IS NULL) per day — enforced by a partial unique index
so concurrent break taps can't double-open.

attendance_requests is the DATE-RANGE approval queue: employees file a
'pending' [from_date, to_date] request of type 'leave' (with a
leave_type) or 'week_off'; SUPER_ADMIN approves or rejects.
Approval materializes an AttendanceDay per covered date so the calendar
and the allocation pool see the leave immediately. Inclusive-range
overlap between open requests is app-checked and, on PostgreSQL,
backstopped by a daterange EXCLUDE constraint (added by migration —
deliberately NOT mapped here so sqlite tests stay valid).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, Uuid, func, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base

ATTENDANCE_STATUSES = ("present", "absent", "week_off", "leave")
# Day statuses an approved request can stamp — allocation pool treats
# both as "not working today".
DAY_OFF_STATUSES = ("week_off", "leave")
REQUEST_TYPES = ("leave", "week_off")
LEAVE_TYPES = (
    "casual_leave", "sick_leave", "paid_leave", "unpaid_leave", "other",
)
REQUEST_STATUSES = ("pending", "approved", "rejected", "cancelled")
OPEN_REQUEST_STATUSES = ("pending", "approved")


class AttendanceDay(Base):
    __tablename__ = "attendance_days"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    employee_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Zone the employee belonged to when the day started — snapshot only,
    # deliberately NOT an FK (matches users.property_id scoping fields).
    zone_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    # IST operational-day key — String(10) like tasks.operational_date.
    attendance_date: Mapped[str] = mapped_column(String(10), nullable=False)
    # present | absent | week_off | leave
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Accumulated closed-break seconds — added server-side on each resume.
    break_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # ended - started - breaks; stamped once at end-of-day.
    work_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )

    breaks: Mapped[list["AttendanceBreak"]] = relationship(
        back_populates="day", cascade="all, delete-orphan",
        order_by="AttendanceBreak.started_at",
    )

    __table_args__ = (
        UniqueConstraint(
            "employee_id", "attendance_date",
            name="uq_attendance_employee_date",
        ),
        Index(
            "ix_attendance_property_date",
            "property_id", "attendance_date",
        ),
        # One OPEN workday per employee — the race backstop for two
        # concurrent /start calls.
        Index(
            "uq_attendance_open_session", "employee_id", unique=True,
            postgresql_where=text(
                "status = 'present' AND ended_at IS NULL"
            ),
            sqlite_where=text(
                "status = 'present' AND ended_at IS NULL"
            ),
        ),
        CheckConstraint(
            "status IN ('present', 'absent', 'week_off', 'leave')",
            name="ck_attendance_days_status",
        ),
        # Leave/absent rows never carry a start stamp.
        CheckConstraint(
            "status = 'present' OR started_at IS NULL",
            name="ck_attendance_days_leave_no_start",
        ),
        # An ended day must have been started.
        CheckConstraint(
            "(ended_at IS NULL) OR (started_at IS NOT NULL)",
            name="ck_attendance_days_end_needs_start",
        ),
        # work_seconds is only computed at end-of-day.
        CheckConstraint(
            "work_seconds IS NULL OR ended_at IS NOT NULL",
            name="ck_attendance_days_work_needs_end",
        ),
    )


class AttendanceBreak(Base):
    __tablename__ = "attendance_breaks"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    attendance_day_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("attendance_days.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_seconds: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    day: Mapped[AttendanceDay] = relationship(back_populates="breaks")

    __table_args__ = (
        # At most one open break per day — races resolve to a 409.
        Index(
            "uq_break_open", "attendance_day_id", unique=True,
            postgresql_where=text("ended_at IS NULL"),
            sqlite_where=text("ended_at IS NULL"),
        ),
    )


class AttendanceRequest(Base):
    __tablename__ = "attendance_requests"

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
    employee_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Inclusive date range — IST 'YYYY-MM-DD' keys like attendance_days.
    from_date: Mapped[str] = mapped_column(String(10), nullable=False)
    to_date: Mapped[str] = mapped_column(String(10), nullable=False)
    # leave | week_off — the day status stamped on approval.
    request_type: Mapped[str] = mapped_column(
        String(16), nullable=False
    )
    # Required for 'leave', must be NULL for 'week_off' (CHECK below).
    leave_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Inclusive day count — computed server-side at filing time.
    requested_days: Mapped[int] = mapped_column(Integer, nullable=False)
    # pending | approved | rejected | cancelled
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending",
        server_default="pending",
    )
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_by_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "request_type IN ('leave', 'week_off')",
            name="ck_attendance_requests_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'cancelled')",
            name="ck_attendance_requests_status",
        ),
        # ISO dates compare lexically — 'YYYY-MM-DD' ordering is real.
        CheckConstraint(
            "from_date <= to_date",
            name="ck_attendance_requests_range",
        ),
        # leave ⇒ a leave_type; week_off ⇒ none. vocab on the value too.
        CheckConstraint(
            "(request_type = 'leave' AND leave_type IS NOT NULL "
            "AND leave_type IN "
            "('casual_leave', 'sick_leave', 'paid_leave', 'unpaid_leave', "
            "'other')) OR "
            "(request_type = 'week_off' AND leave_type IS NULL)",
            name="ck_attendance_requests_leave_type",
        ),
        CheckConstraint(
            "requested_days > 0",
            name="ck_attendance_requests_days",
        ),
        # Inclusive-overlap dedupe of open requests is enforced app-side
        # (works on sqlite); PostgreSQL additionally carries a
        # btree_gist EXCLUDE constraint over a generated daterange —
        # installed by the migration, unmapped here.
        Index(
            "ix_request_employee_status", "employee_id", "status",
        ),
        Index(
            "ix_request_property_from", "property_id", "from_date",
        ),
        Index(
            "ix_request_property_to", "property_id", "to_date",
        ),
    )
