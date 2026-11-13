"""Employee preferences — per-employee UI/audio settings.

One row per employee (unique employee_id). Holds only preference data —
profile fields stay on the employees row; never duplicate them here.

`employee_id` references the employees row (the person), NOT users.id —
a login account (users) and the workforce record (employees) are
different identities; the API resolves user.employee_id first.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.languages import DEFAULT_LANGUAGE
from app.models import Base


class EmployeePreference(Base):
    __tablename__ = "employee_preferences"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    text_language: Mapped[str] = mapped_column(
        String(8), nullable=False, default=DEFAULT_LANGUAGE
    )
    audio_language: Mapped[str] = mapped_column(
        String(8), nullable=False, default=DEFAULT_LANGUAGE
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
