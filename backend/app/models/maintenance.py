"""Maintenance tickets — operational workflow records for rooms/dorms.

A ticket is the permanent operational record; the room's `maintenance`
status is the *derived* current state, never the source of truth.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class MaintenanceTicket(Base):
    __tablename__ = "maintenance_tickets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    ticket_number: Mapped[str] = mapped_column(
        String(32), nullable=False, unique=True, index=True
    )  # MT-YYYY-NNNNN — generated server-side from a PG sequence
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    room_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True, index=True
    )
    room_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Alternative targets — exactly one of room_id / dorm_id / bed_id is set
    dorm_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("dorms.id", ondelete="SET NULL"), nullable=True, index=True
    )
    dorm_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bed_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("beds.id", ondelete="SET NULL"), nullable=True, index=True
    )
    bed_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    washroom_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("washrooms.id", ondelete="SET NULL"), nullable=True,
        index=True,
    )
    washroom_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Optional fixture-level targeting within the washroom — SET NULL keeps
    # the ticket history if the fixture is later removed.
    washroom_fixture_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("washroom_fixtures.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    washroom_fixture_label: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    reported_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    reported_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    maintenance_type: Mapped[str] = mapped_column(String(64), nullable=False)
    issue: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    # open | assigned | in_progress | on_hold | resolved | closed | cancelled
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open", index=True)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True
    )
    assigned_to_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Work allocation engine — zone resolved at creation, batch, method
    zone_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("zones.id", ondelete="SET NULL"), nullable=True, index=True
    )
    allocation_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("work_allocation_batches.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    # auto_assigned | manually_assigned | unassigned
    allocation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unassigned"
    )
    allocation_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    allocation_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Work-template provenance (scheduler-generated tickets)
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("work_templates.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    template_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    due_date: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolution_notes: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    events: Mapped[list["MaintenanceTicketEvent"]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="MaintenanceTicketEvent.created_at",
    )
    attachments: Mapped[list["MaintenanceTicketAttachment"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan"
    )


class MaintenanceTicketEvent(Base):
    """Append-only activity timeline for a ticket."""

    __tablename__ = "maintenance_ticket_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("maintenance_tickets.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # created | assigned | started | held | resumed | resolved | closed | cancelled | edited | commented
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    comment: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    ticket: Mapped[MaintenanceTicket] = relationship(back_populates="events")


class MaintenanceTicketAttachment(Base):
    """File metadata — binaries live in /uploads (dev) or object storage."""

    __tablename__ = "maintenance_ticket_attachments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("maintenance_tickets.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False, default="issue")
    # issue | resolution
    # resolution iteration — NULL/1 = first resolution submission; a
    # disapproved→re-resolved ticket uploads the next attempt's evidence
    # under a higher number so each submission round stays distinguishable.
    attempt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    ticket: Mapped[MaintenanceTicket] = relationship(back_populates="attachments")
