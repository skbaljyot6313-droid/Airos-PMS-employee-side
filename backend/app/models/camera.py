"""VA camera models — READ-ONLY mirror of the shared Super Admin tables.

The employee backend never writes camera configuration; this mapping exists
so Alembic autogenerate/metadata parity stays intact on the shared database
(the Super Admin backend owns the tables and the migration chain).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.models import Base


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    area_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("areas.id", ondelete="SET NULL"), nullable=True, index=True
    )
    zone_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("zones.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rtsp_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    sub_rtsp_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    transcode: Mapped[bool | None] = mapped_column(nullable=True)
    warm: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    transport: Mapped[str] = mapped_column(String(8), nullable=False, default="tcp")
    resolution: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    connection_status: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CameraStreamSession(Base):
    __tablename__ = "camera_stream_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    camera_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    protocol: Mapped[str] = mapped_column(String(16), nullable=False, default="webrtc")
    quality: Mapped[str] = mapped_column(String(8), nullable=False, default="main")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
