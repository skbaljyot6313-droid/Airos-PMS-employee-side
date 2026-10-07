"""Work allocation engine — persistent zone round-robin state, batches, audit.

One allocation step selects one employee from the final zone or area pool.
Zone state rows serialize zone allocations; area rows serialize fallback.
Committed allocation history provides the work-type-specific pointer.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class ZoneAllocationState(Base):
    """Per-zone round-robin pointer. One row per (property, zone)."""

    __tablename__ = "zone_allocation_state"
    __table_args__ = (
        UniqueConstraint("zone_id", name="uq_zone_allocation_state_zone"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    zone_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("zones.id", ondelete="CASCADE"), nullable=False, index=True
    )
    last_assigned_employee_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    last_assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class WorkAllocationBatch(Base):
    """A group of tickets allocated together — always to ONE employee."""

    __tablename__ = "work_allocation_batches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    batch_number: Mapped[str] = mapped_column(
        String(32), nullable=False, unique=True, index=True
    )  # WB-YYYY-NNNNN
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    zone_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("zones.id", ondelete="SET NULL"), nullable=True, index=True
    )
    zone_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True
    )
    employee_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # cleaning | maintenance | task | mixed — drives department eligibility
    work_type: Mapped[str] = mapped_column(String(24), nullable=False)
    # auto_assigned | unassigned
    allocation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    allocation_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WorkAllocationHistory(Base):
    """Audit trail — every allocation decision (auto + manual + reassign)."""

    __tablename__ = "work_allocation_history"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    zone_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("work_allocation_batches.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    batch_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # maintenance | task
    ticket_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    ticket_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    ticket_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    employee_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    previous_employee_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    previous_employee_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # round_robin | manual | reassign
    allocation_method: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
