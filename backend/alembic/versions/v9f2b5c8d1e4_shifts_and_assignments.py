"""Shift definitions + employee shift assignments.

Reusable shift templates per property (IST wall-clock start/end —
end <= start means the shift crosses midnight into the next calendar
day) and dated assignments to employees. Assignments keep effective_from
/effective_until so historical attendance metrics always resolve against
the schedule that was in force on the date being evaluated — never the
employee's current shift.

Times are stored as `time` columns read against the company's IST
operational-day configuration; assignment dates use the same IST
'YYYY-MM-DD' op-day keys as attendance_days.attendance_date. Overlapping
assignments for one employee are rejected at the service layer (same
convention as attendance request overlap checks) — no exclusion
constraint so rollback stays trivial.

This file is identical in the Super Admin and Employee Backend repos:
both chains share one alembic_version row, so the revision must exist in
both graphs.

Revision ID: v9f2b5c8d1e4
Revises: u7e1f5a9d3c6
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v9f2b5c8d1e4"
down_revision: Union[str, Sequence[str], None] = "u7e1f5a9d3c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shifts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        # IST wall-clock times; end_time <= start_time => overnight.
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("grace_minutes", sa.Integer(), nullable=False,
                  server_default="10"),
        sa.Column("early_exit_minutes", sa.Integer(), nullable=False,
                  server_default="0"),
        # Monday-first 7-char bitmap, e.g. '1111110'.
        sa.Column("working_days", sa.String(length=7), nullable=False,
                  server_default="1111111"),
        sa.Column("is_active", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["property_id"], ["properties.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_shifts_company_id", "shifts", ["company_id"])
    op.create_index("ix_shifts_property_id", "shifts", ["property_id"])

    op.create_table(
        "employee_shift_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("shift_id", sa.Uuid(), nullable=False),
        # IST op-day keys, inclusive; NULL until = open-ended.
        sa.Column("effective_from", sa.String(length=10), nullable=False),
        sa.Column("effective_until", sa.String(length=10), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["employee_id"], ["employees.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["shift_id"], ["shifts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_employee_shift_assignments_employee_id",
        "employee_shift_assignments", ["employee_id"],
    )
    op.create_index(
        "ix_employee_shift_assignments_shift_id",
        "employee_shift_assignments", ["shift_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_employee_shift_assignments_shift_id",
        table_name="employee_shift_assignments",
    )
    op.drop_index(
        "ix_employee_shift_assignments_employee_id",
        table_name="employee_shift_assignments",
    )
    op.drop_table("employee_shift_assignments")
    op.drop_index("ix_shifts_property_id", table_name="shifts")
    op.drop_index("ix_shifts_company_id", table_name="shifts")
    op.drop_table("shifts")
