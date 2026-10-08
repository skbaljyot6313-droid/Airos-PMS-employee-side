"""Allocation history — who/what/when/from/to for every move."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class AllocationEvent(Base):
    """
    One row per allocation/move: employee→zone, room→zone/area,
    dorm→zone/area. `to_*` = NULL means "unassigned".

    Replaces separate employee_zone_allocations / room_allocation_history /
    dorm_allocation_history tables — one event log answers all three.
    """

    __tablename__ = "allocation_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # employee | room | dorm
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_zone_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    to_zone_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    from_area_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    to_area_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    actor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
