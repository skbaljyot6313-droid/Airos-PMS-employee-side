"""Attendance — workday sessions, break segments, day-off requests.

- `attendance_days`: one row per (employee, operational date). The date is
  the IST operational-day key ('YYYY-MM-DD'). `uq_attendance_open_session`
  is the race backstop for a second concurrent /start — at most one open
  'present' row per employee. CHECK constraints keep leave/absent rows
  stamp-free and stamp-less rows from pretending to be complete.
- `attendance_breaks`: contiguous break segments; `uq_break_open` allows
  at most one open break per day.
- `attendance_requests`: the week_off/holiday approval queue.
  `uq_request_open` dedupes pending/approved filings per employee+date.

Revision ID: p8d1f4a7c2e5
Revises: o7h5b9d1f3e6
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "p8d1f4a7c2e5"
down_revision: Union[str, Sequence[str], None] = "o7h5b9d1f3e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "attendance_days",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=True),
        sa.Column("employee_name", sa.String(255), nullable=False),
        sa.Column("zone_id", sa.Uuid(), nullable=True),
        sa.Column("attendance_date", sa.String(10), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "break_seconds", sa.Integer(), nullable=False,
            server_default="0",
        ),
        sa.Column("work_seconds", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["property_id"], ["properties.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"], ["employees.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "employee_id", "attendance_date",
            name="uq_attendance_employee_date",
        ),
        sa.CheckConstraint(
            "status IN ('present', 'absent', 'week_off', 'holiday')",
            name="ck_attendance_days_status",
        ),
        sa.CheckConstraint(
            "status = 'present' OR started_at IS NULL",
            name="ck_attendance_days_leave_no_start",
        ),
        sa.CheckConstraint(
            "(ended_at IS NULL) OR (started_at IS NOT NULL)",
            name="ck_attendance_days_end_needs_start",
        ),
        sa.CheckConstraint(
            "work_seconds IS NULL OR ended_at IS NOT NULL",
            name="ck_attendance_days_work_needs_end",
        ),
    )
    op.create_index(
        "ix_attendance_days_property_id", "attendance_days", ["property_id"]
    )
    op.create_index(
        "ix_attendance_days_employee_id", "attendance_days", ["employee_id"]
    )
    op.create_index(
        "ix_attendance_property_date", "attendance_days",
        ["property_id", "attendance_date"],
    )
    op.create_index(
        "uq_attendance_open_session", "attendance_days", ["employee_id"],
        unique=True,
        postgresql_where=sa.text(
            "status = 'present' AND ended_at IS NULL"
        ),
        sqlite_where=sa.text(
            "status = 'present' AND ended_at IS NULL"
        ),
    )

    op.create_table(
        "attendance_breaks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("attendance_day_id", sa.Uuid(), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["attendance_day_id"], ["attendance_days.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_attendance_breaks_attendance_day_id", "attendance_breaks",
        ["attendance_day_id"],
    )
    op.create_index(
        "uq_break_open", "attendance_breaks", ["attendance_day_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
        sqlite_where=sa.text("ended_at IS NULL"),
    )

    op.create_table(
        "attendance_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=True),
        sa.Column("employee_name", sa.String(255), nullable=False),
        sa.Column("attendance_date", sa.String(10), nullable=False),
        sa.Column("request_type", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(16), nullable=False,
            server_default="pending",
        ),
        sa.Column("reviewed_by_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_by_name", sa.String(255), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["property_id"], ["properties.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"], ["employees.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "request_type IN ('week_off', 'holiday')",
            name="ck_attendance_requests_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'cancelled')",
            name="ck_attendance_requests_status",
        ),
    )
    op.create_index(
        "ix_attendance_requests_property_id", "attendance_requests",
        ["property_id"],
    )
    op.create_index(
        "uq_request_open", "attendance_requests",
        ["employee_id", "attendance_date"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'approved')"),
        sqlite_where=sa.text("status IN ('pending', 'approved')"),
    )
    op.create_index(
        "ix_request_employee_status", "attendance_requests",
        ["employee_id", "status"],
    )
    op.create_index(
        "ix_request_property_date", "attendance_requests",
        ["property_id", "attendance_date"],
    )


def downgrade() -> None:
    op.drop_table("attendance_requests")
    op.drop_table("attendance_breaks")
    op.drop_table("attendance_days")
