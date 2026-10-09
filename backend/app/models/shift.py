"""Shift definitions + dated employee assignments — SHARED tables.

These tables are owned by the Super Admin backend (scheduling authority
lives there — create/update/assign are SA/PM operations). This repo owns
the matching alembic revision v9f2b5c8d1e4 in the shared chain and maps
the tables read-only for the employee 'My Shift' profile card.

Column semantics (kept identical to the SA models):
- start_time/end_time are IST wall-clock; end_time <= start_time means
  the shift runs overnight into the next calendar day.
- working_days is a Monday-first 7-char '0'/'1' bitmap.
- effective_from/effective_until are inclusive IST 'YYYY-MM-DD' op-day
  keys, the same vocabulary as attendance_days.attendance_date.
"""

import uuid
from datetime import datetime, time

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Time,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class Shift(Base):
    __tablename__ = "shifts"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # IST wall-clock; end_time <= start_time => overnight shift.
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    grace_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default="10"
    )
    early_exit_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    working_days: Mapped[str] = mapped_column(
        String(7), nullable=False, default="1111111",
        server_default="1111111",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )


class EmployeeShiftAssignment(Base):
    __tablename__ = "employee_shift_assignments"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    shift_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("shifts.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Inclusive IST 'YYYY-MM-DD' bounds; NULL until = open-ended.
    effective_from: Mapped[str] = mapped_column(String(10), nullable=False)
    effective_until: Mapped[str | None] = mapped_column(
        String(10), nullable=True
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )
