import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security import generate_organization_code
from app.models import Base


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)  # e.g. PROP-001
    location: Mapped[str] = mapped_column(String(255), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="Setup")
    # 12-char public code (A-Z2-9, no O/0/I/1) — the employee app's
    # self-registration flow resolves this property (and transitively
    # the company) from the code. Rotation invalidates it for new
    # requests without touching approved employees.
    organization_code: Mapped[str] = mapped_column(
        String(12),
        nullable=False,
        unique=True,
        index=True,
        default=generate_organization_code,
    )
    manager_employee_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    manager_name: Mapped[str] = mapped_column(String(255), nullable=False)
    manager_email: Mapped[str] = mapped_column(String(255), nullable=False)
    manager_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Geofence anchor — NULL means the feature is OFF for this property;
    # attendance geo captures record unflagged until all three are set.
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    geofence_radius_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
