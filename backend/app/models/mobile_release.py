import uuid
from datetime import datetime

from sqlalchemy import Uuid, Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class MobileRelease(Base):
    """Mobile app release registry — one row per published build.

    Only one row per platform carries is_active=True; that row answers the
    public GET /mobile/version check. Old rows are kept so a bad release
    can be rolled back by re-activating a previous one — never deleted.
    """

    __tablename__ = "mobile_releases"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    platform: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    version_code: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_version: Mapped[str] = mapped_column(String(32), nullable=False)
    minimum_version_code: Mapped[int] = mapped_column(Integer, nullable=False)
    download_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    release_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    force_update: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
