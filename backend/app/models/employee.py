import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base

EMPLOYEE_STATUS_ACTIVE = "Active"
EMPLOYEE_STATUS_DEACTIVATED = "Deactivated"


def employee_is_assignable(employee: "Employee") -> bool:
    """Whether the employee may receive NEW work or allocation."""
    return (
        (employee.status or "").lower() == "active"
        and not employee.leave_status
    )


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    zone_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("zones.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Secondary zone coverage — an optional SECOND zone the employee is
    # eligible for (max 2 zones total). Only meaningful when zone_id is
    # set; may coexist with area coverage.
    secondary_zone_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("zones.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Primary area assignment — the employee is eligible for work in
    # EVERY zone inside that area ("responsible for the whole floor").
    # Coexists with zone coverage; additional areas live in
    # employee_area_assignments.
    area_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("areas.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Property-wide coverage — the employee is eligible for work in EVERY
    # zone of the property. The one EXCLUSIVE mode — setting it clears
    # zone/area coverage; setting zone/area coverage narrows it.
    # Written by the Super Admin backend; read-only here.
    covers_property: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # FK to the SA-owned departments table (managed by the super-admin
    # backend; mapped here for shared-schema compatibility).
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="Active")
    salary: Mapped[str | None] = mapped_column(String(64), nullable=True)
    shift: Mapped[str | None] = mapped_column(String(64), nullable=True)
    start_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    avatar_color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    leave_balance_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    leave_status: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        # client-side µs precision — the round-robin ORDER BY depends on
        # real creation order; second-precision timestamps tie on bulk adds
        default=lambda: datetime.now(UTC),
        server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class EmployeeAreaAssignment(Base):
    """ADDITIONAL whole-area coverage rows — shared table owned by the
    Super Admin backend; mapped here READ-ONLY so coverage predicates can
    union ``area_id`` with these extra areas (multi-area allocation)."""

    __tablename__ = "employee_area_assignments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    area_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("areas.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
