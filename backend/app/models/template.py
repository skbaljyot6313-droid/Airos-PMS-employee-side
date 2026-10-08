"""Work templates — reusable operational definitions + generation ledger.

A template declares WHAT / WHERE / WHO / WHEN / VERIFY. The backend
scheduler expands the location rule live (dynamic zones/rooms), hands each
zone group to WorkAllocationService, and stamps generated work with
template_id + template_version. Structured config lives in JSONB columns —
the same convention `tasks.automation_rule` already uses.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base

TEMPLATE_TYPES = {
    "task", "maintenance", "inspection", "cleaning", "checklist",
    "operations", "housekeeping", "other",
}
TEMPLATE_STATUSES = {"draft", "active", "paused", "archived"}


class WorkTemplate(Base):
    __tablename__ = "work_templates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    template_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="task", index=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # draft | active | paused | archived
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft",
                                        index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Structured config — see schemas/template.py for the shape
    assignment: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    location: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    schedule: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    checklist: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    verification: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    overdue: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    notifications: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Scheduler bookkeeping — backend owns generation
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    generated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
        nullable=False,
    )


class WorkTemplateVersion(Base):
    """Immutable config snapshot — generated work keeps the version it was
    created under, so editing a template never rewrites history."""

    __tablename__ = "work_template_versions"
    __table_args__ = (
        UniqueConstraint("template_id", "version", name="uq_template_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("work_templates.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    config: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TemplateGeneration(Base):
    """Idempotency ledger — one row per generated work item.

    occurrence_key = '<scheduled_iso>|<target_uid>' so a scheduler double-run
    hits the unique constraint instead of creating duplicate tasks."""

    __tablename__ = "template_generations"
    __table_args__ = (
        UniqueConstraint("template_id", "occurrence_key",
                         name="uq_template_generation"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("work_templates.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    occurrence_key: Mapped[str] = mapped_column(String(128), nullable=False)
    # maintenance | task
    ticket_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    ticket_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    ticket_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
