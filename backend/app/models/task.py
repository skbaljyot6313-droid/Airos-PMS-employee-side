"""Tasks + audit history events."""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint,
    func, Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    zone_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("zones.id", ondelete="SET NULL"), nullable=True, index=True
    )
    area_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("areas.id", ondelete="SET NULL"), nullable=True, index=True
    )
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True
    )
    ticket_number: Mapped[str | None] = mapped_column(
        String(32), nullable=True, unique=True, index=True
    )  # TASK-YYYY-NNNNN — generated server-side
    room_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True, index=True
    )
    room_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Dorm/bed linkage — mirrors MaintenanceTicket: one task can cover a whole
    # dorm or a subset of its beds. bed_ids holds uuid strings (JSON so it is
    # portable across postgres and sqlite).
    dorm_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("dorms.id", ondelete="SET NULL"), nullable=True, index=True
    )
    dorm_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bed_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    washroom_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("washrooms.id", ondelete="SET NULL"), nullable=True,
        index=True,
    )
    washroom_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Optional fixture-level targeting within the washroom — SET NULL keeps
    # the task history if the fixture is later removed.
    washroom_fixture_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("washroom_fixtures.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    washroom_fixture_label: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    supervisor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True
    )
    supervisor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    assigned_to_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    allocation_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("work_allocation_batches.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    # auto_assigned | manually_assigned | unassigned
    allocation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unassigned"
    )
    allocation_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    allocation_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Work-template provenance (scheduler-generated tasks)
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("work_templates.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    template_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False, default="fixed")
    # Domain work kind (cleaning | maintenance | inspection | housekeeping |
    # other | …) — stamped at creation; drives department eligibility for
    # allocation/reassignment. task_type is the lifecycle shape
    # (fixed/repetitive/automated); work_type is the operating department.
    work_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Why the task exists — 'manual' | 'checkout' | 'template' |
    # 'automation'. Checkout-generated cleaning must be identifiable by
    # DATA, not by matching on the title string.
    origin: Mapped[str] = mapped_column(
        String(32), nullable=False, default="manual"
    )
    # pending | assigned | in_progress | submitted | reopened |
    # completed | cancelled | abandoned | overdue | scheduled
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    priority: Mapped[str] = mapped_column(String(32), nullable=False, default="medium")
    # Date (YYYY-MM-DD) or ISO timestamp for hourly schedules
    due_date: Mapped[str | None] = mapped_column(String(64), nullable=True)
    due_time: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # HH:MM — anchor time a repetitive schedule starts from each cycle
    start_time: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Repetition window — from date to end date (None = runs forever), and
    # an optional daily time window for multi-per-day recurrences
    recurrence_start_date: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recurrence_end_date: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recurrence_window_end: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Daily-rollover outcome — set only by RolloverService. operational_date
    # is the IST operational-day key (YYYY-MM-DD) the task belonged to.
    abandoned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    abandoned_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    abandoned_from_status: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    operational_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # Recurring-instance validity window — stamped at generation for
    # template- and series-produced occurrences. `scheduled_for` is the
    # scheduled occurrence instant; `expires_at` is the NEXT scheduled
    # boundary (the instance is valid until then, never extended by
    # scheduler downtime). NULL on manual/one-time tasks — those are
    # governed by the daily operational rollover instead.
    scheduled_for: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recurrence: Mapped[str | None] = mapped_column(String(32), nullable=True)
    recurrence_interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Repetitive-task lineage — all clones of one recurring series share the
    # root task's id. Lets the scheduler find the series head and dedupe
    # occurrences without relying on matching cloned fields.
    series_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Automation rule for task_type='automated' — JSON document
    automation_rule: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    history: Mapped[list["TaskHistoryEvent"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TaskHistoryEvent.at"
    )
    completion_images: Mapped[list["TaskCompletionImage"]] = relationship(
        back_populates="task", cascade="all, delete-orphan",
        order_by="TaskCompletionImage.created_at",
    )
    completion_submissions: Mapped[list["TaskCompletionSubmission"]] = relationship(
        back_populates="task", cascade="all, delete-orphan",
        order_by="TaskCompletionSubmission.attempt_number.desc()",
    )

    # One OPEN cleaning ticket per (property, room, title) — backstop for
    # the dedupe check so two concurrent checkouts can't double-book.
    __table_args__ = (
        Index(
            "uq_tasks_open_room_title",
            "property_id", "room_id", "title",
            unique=True,
            postgresql_where=(room_id.isnot(None) & ~status.in_(
                ("completed", "cancelled", "abandoned"))),
            sqlite_where=(room_id.isnot(None) & ~status.in_(
                ("completed", "cancelled", "abandoned"))),
        ),
        # Expiry sweep: WHERE expires_at <= now AND status IN (expirable).
        # Partial — only recurring instances carry a validity window.
        Index(
            "ix_tasks_expires_at", "expires_at",
            postgresql_where=expires_at.isnot(None),
            sqlite_where=expires_at.isnot(None),
        ),
        # One row per (series, occurrence) — the scheduler sweep and the
        # on-completion spawn can race the same slot; this is the
        # DB-authoritative dedupe (the app-level select is only a hint).
        Index(
            "uq_tasks_series_due", "series_id", "due_date",
            unique=True,
            postgresql_where=(series_id.isnot(None) & due_date.isnot(None)
                              & (task_type == "repetitive")),
            sqlite_where=(series_id.isnot(None) & due_date.isnot(None)
                          & (task_type == "repetitive")),
        ),
    )


class TaskHistoryEvent(Base):
    __tablename__ = "task_history_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # allocated | started | completed | redo_requested | reassigned |
    # edited | auto_generated | abandoned
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    photos: Mapped[list | None] = mapped_column(JSON, nullable=True)

    task: Mapped[Task] = relationship(back_populates="history")
    completion_images: Mapped[list["TaskCompletionImage"]] = relationship(
        back_populates="history_event"
    )
    completion_submission: Mapped["TaskCompletionSubmission | None"] = relationship(
        back_populates="history_event", uselist=False
    )


class TaskCompletionSubmission(Base):
    """One employee evidence submission/review cycle for a task."""

    __tablename__ = "task_completion_submissions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    history_event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("task_history_events.id", ondelete="SET NULL"),
        nullable=True, unique=True
    )
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="SET NULL"), nullable=True,
        index=True
    )
    employee_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    task: Mapped[Task] = relationship(back_populates="completion_submissions")
    history_event: Mapped[TaskHistoryEvent | None] = relationship(
        back_populates="completion_submission"
    )
    images: Mapped[list["TaskCompletionImage"]] = relationship(
        back_populates="submission", order_by="TaskCompletionImage.created_at"
    )

    __table_args__ = (
        UniqueConstraint("task_id", "attempt_number", name="uq_task_attempt"),
    )


class TaskCompletionImage(Base):
    """Durable image belonging to one completion submission attempt."""
    __tablename__ = "task_completion_images"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    history_event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("task_history_events.id", ondelete="SET NULL"),
        nullable=True, index=True
    )
    submission_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("task_completion_submissions.id", ondelete="SET NULL"),
        nullable=True, index=True
    )
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    task: Mapped[Task] = relationship(back_populates="completion_images")
    history_event: Mapped[TaskHistoryEvent | None] = relationship(
        back_populates="completion_images"
    )
    submission: Mapped[TaskCompletionSubmission | None] = relationship(
        back_populates="images"
    )
