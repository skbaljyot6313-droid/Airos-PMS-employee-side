import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.security import generate_organization_code
from app.models import Base


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    brand_name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    pin_code: Mapped[str] = mapped_column(String(10), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(32), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 12-char public code (A-Z2-9, no O/0/I/1) — the employee app's
    # self-registration flow resolves the company from this code.
    # Super-admin-only visibility; rotation invalidates it for new
    # requests without touching approved employees.
    organization_code: Mapped[str] = mapped_column(
        String(12),
        nullable=False,
        unique=True,
        index=True,
        default=generate_organization_code,
    )
    # 'HH:MM' IST wall-clock — rollover closes the operational day at this
    # time; analysis groups work by it. Default 06:00 (hotel convention).
    operational_day_start: Mapped[str] = mapped_column(
        String(5), nullable=False, default="06:00", server_default="06:00"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    users: Mapped[list["User"]] = relationship(back_populates="company")
