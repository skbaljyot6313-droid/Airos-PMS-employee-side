"""Optional guest name on occupancies.

Check-in can now be a pure occupancy toggle — a guest name is still
accepted and stored when provided, but is no longer required. NULL means
"occupied, unnamed".

Revision ID: j7a2c3e5f9b1
Revises: i6f1b2d4e8a0
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'j7a2c3e5f9b1'
down_revision: Union[str, Sequence[str], None] = 'i6f1b2d4e8a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("occupancies") as batch:
        batch.alter_column(
            "guest_name",
            existing_type=sa.String(length=255),
            nullable=True,
        )


def downgrade() -> None:
    # backfill NULLs before restoring NOT NULL
    op.execute("UPDATE occupancies SET guest_name = '' WHERE guest_name IS NULL")
    with op.batch_alter_table("occupancies") as batch:
        batch.alter_column(
            "guest_name",
            existing_type=sa.String(length=255),
            nullable=False,
        )
