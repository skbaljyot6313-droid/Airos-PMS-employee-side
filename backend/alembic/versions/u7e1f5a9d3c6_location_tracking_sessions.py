"""location_tracking_sessions — session metadata for location tracking.

Session lifecycle rows only (start/stop/status/point_count). Raw GPS
points live exclusively in Redis (daily ZSET partitions + GEO index) —
this table must never take a row per fix.

Revision ID: u7e1f5a9d3c6
Revises: t6d0e4a8f2b5
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "u7e1f5a9d3c6"
down_revision: Union[str, Sequence[str], None] = "t6d0e4a8f2b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "location_tracking_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False,
                  server_default="active"),
        sa.Column("started_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("point_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["employee_id"], ["employees.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_location_tracking_sessions_employee_id",
        "location_tracking_sessions", ["employee_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_location_tracking_sessions_employee_id",
        table_name="location_tracking_sessions",
    )
    op.drop_table("location_tracking_sessions")
