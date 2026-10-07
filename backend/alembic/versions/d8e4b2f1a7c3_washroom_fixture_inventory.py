"""washroom fixture inventory — sinks, mirrors, custom fixture types

Revision ID: d8e4b2f1a7c3
Revises: c5f7a9b1d3e2
Create Date: 2026-09-29

Adds real fixture-inventory columns to washrooms:
- sink_count, mirror_count — built-in counters like stall/urinal/shower
- custom_fixtures     — JSON map of arbitrary extra fixture types, e.g. {"Hand Dryer": 2}

Existing rows get backfilled: sinks/mirrors default to 0 (declared later via
the edit form), so no existing data is altered.
"""

from alembic import op
import sqlalchemy as sa


revision = "d8e4b2f1a7c3"
down_revision = "c5f7a9b1d3e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "washrooms",
        sa.Column("sink_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "washrooms",
        sa.Column("mirror_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "washrooms",
        sa.Column("custom_fixtures", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("washrooms", "custom_fixtures")
    op.drop_column("washrooms", "mirror_count")
    op.drop_column("washrooms", "sink_count")
