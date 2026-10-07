"""Attendance requests — rename request_category → request_type.

Pure column rename: PostgreSQL rewrites the CHECK expressions that
reference the column (ck_attendance_requests_type vocab +
ck_attendance_requests_leave_type pairing) automatically, and live rows
carry over unchanged. The category CHECK is also renamed to match the
model's declared name (ck_attendance_requests_type — the same name the
old single-date shape used for a different rule before q9e2f5a8c3d7,
and it was dropped there, so no collision). The generated leave_range
column and the ex_request_no_overlap EXCLUDE constraint are untouched —
they don't reference the renamed column.

Revision ID: r4b8d2f6a0c3e
Revises: q9e2f5a8c3d7
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "r4b8d2f6a0c3e"
down_revision: Union[str, Sequence[str], None] = "q9e2f5a8c3d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PG rewrites dependent CHECK expressions on RENAME COLUMN.
    op.alter_column(
        "attendance_requests", "request_category",
        new_column_name="request_type",
        existing_type=sa.String(16),
    )
    if op.get_bind().dialect.name == "postgresql":
        # sqlite (test env) creates fresh schemas from the model —
        # constraint names there are irrelevant, and RENAME CONSTRAINT
        # isn't supported anyway.
        op.execute(
            "ALTER TABLE attendance_requests "
            "RENAME CONSTRAINT ck_attendance_requests_category "
            "TO ck_attendance_requests_type"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE attendance_requests "
            "RENAME CONSTRAINT ck_attendance_requests_type "
            "TO ck_attendance_requests_category"
        )
    op.alter_column(
        "attendance_requests", "request_type",
        new_column_name="request_category",
        existing_type=sa.String(16),
    )
