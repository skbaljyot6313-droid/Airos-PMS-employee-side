"""camera warm-stream flag

Adds `cameras.warm` — keeps an upstream camera connection hot so a
viewer's first frame skips the cold RTSP dial/describe. Bounded by
VA_WARM_MAX_STREAMS on the application side.

Revision ID: b7e4f9a1c5d3
Revises: e3b7c9f2a4d1
"""
from alembic import op
import sqlalchemy as sa

revision = "b7e4f9a1c5d3"
down_revision = "e3b7c9f2a4d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column("warm", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("cameras", "warm")
