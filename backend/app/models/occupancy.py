"""Occupancy — the authoritative record behind a resource's `occupied` state.

Exactly one of room_id / bed_id is populated (DB CHECK). At most one OPEN
occupancy (checked_out_at IS NULL) per room and per bed (partial unique
indexes) — `OCCUPIED` is illegal without this row existing.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, String, func, text, Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class Occupancy(Base):
    __tablename__ = "occupancies"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # room_id / bed_id are deliberately NOT FKs — an occupancy is a
    # permanent stay record; deleting a room/bed must not null out or
    # cascade history (the audit trail keeps the target id, which dangles
    # after deletion — reconciliation reports it).
    room_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, nullable=True, index=True
    )
    bed_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, nullable=True, index=True
    )
    # NULL guest_name = "occupied, unnamed" — a pure occupancy toggle may
    # skip the name; a real name is stored whenever one is provided.
    guest_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    checked_in_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    checked_out_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    checked_in_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    checked_out_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )

    # table args AFTER the column defs — the partial-unique WHERE clauses
    # reference checked_out_at
    __table_args__ = (
        CheckConstraint(
            "(room_id IS NOT NULL AND bed_id IS NULL)"
            " OR (room_id IS NULL AND bed_id IS NOT NULL)",
            name="ck_occupancies_one_target",
        ),
        Index(
            "uq_occupancies_open_room", "room_id", unique=True,
            postgresql_where=text("checked_out_at IS NULL"),
            sqlite_where=text("checked_out_at IS NULL"),
        ),
        Index(
            "uq_occupancies_open_bed", "bed_id", unique=True,
            postgresql_where=text("checked_out_at IS NULL"),
            sqlite_where=text("checked_out_at IS NULL"),
        ),
    )
