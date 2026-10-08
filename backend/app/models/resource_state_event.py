"""Immutable audit record for every authoritative resource-state transition.

task_id / ticket_id / occupancy_id are plain UUIDs (no FK) on purpose —
deleting a task or ticket must never destroy the resource's transition
history (spec §28/§32).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class ResourceStateEvent(Base):
    __tablename__ = "resource_state_events"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    previous_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_state: Mapped[str] = mapped_column(String(32), nullable=False)
    # task_start | task_approved | task_rejected | ticket_created |
    # ticket_resolved | ticket_closed | occupancy_checkin | occupancy_checkout |
    # admin_override | reconciliation | derive | fixture_restored
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    actor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    occupancy_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
