"""Location tracking sessions — the ONLY location data in PostgreSQL.

One row per tracking session (POST /location/start → /stop); raw GPS
points live exclusively in Redis. Sessions survive app restarts and may
recur several times within one operational day — they are deliberately
NOT coupled to attendance days (no FK) so a location outage can never
block attendance and vice versa.

status: active → stopped | expired (TTL lapse, applied lazily on read).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, func, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base

SESSION_STATUS_ACTIVE = "active"
SESSION_STATUS_STOPPED = "stopped"
SESSION_STATUS_EXPIRED = "expired"
SESSION_STATUSES = frozenset(
    (SESSION_STATUS_ACTIVE, SESSION_STATUS_STOPPED, SESSION_STATUS_EXPIRED)
)


class LocationTrackingSession(Base):
    __tablename__ = "location_tracking_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SESSION_STATUS_ACTIVE,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(), nullable=False,
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Number of points ingested under this session — bookkeeping only,
    # lets ops spot dead sessions without touching Redis.
    point_count: Mapped[int] = mapped_column(
        default=0, server_default="0", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )
