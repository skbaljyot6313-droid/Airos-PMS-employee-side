"""Partial unique index — one open cleaning task per (property, room, title)

Backstop for the checkout/bulk-cleaning dedupe: two concurrent requests
passing the same "is there already an open task?" check can no longer both
insert. Completed/cancelled tasks and room-less tasks don't participate.

Revision ID: d9e2f04a1c33
Revises: c4d81e7b2f05
Create Date: 2026-09-25 11:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd9e2f04a1c33'
down_revision: Union[str, Sequence[str], None] = 'c4d81e7b2f05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_tasks_open_room_title",
        "tasks",
        ["property_id", "room_id", "title"],
        unique=True,
        postgresql_where=sa.text(
            "room_id IS NOT NULL AND status NOT IN ('completed', 'cancelled')"
        ),
        sqlite_where=sa.text(
            "room_id IS NOT NULL AND status NOT IN ('completed', 'cancelled')"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_tasks_open_room_title", table_name="tasks")
