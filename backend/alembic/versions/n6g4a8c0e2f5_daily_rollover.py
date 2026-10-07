"""Daily operational-day rollover + abandoned lifecycle.

- `tasks` gains the abandonment audit fields (`abandoned_at`,
  `abandoned_reason`, `abandoned_from_status`) and `operational_date`
  (IST YYYY-MM-DD op-day key stamped when the task is abandoned).
- `companies.operational_day_start` ('HH:MM', default 06:00) is the
  Super-Admin-configurable boundary used by rollover and day analysis.
- `uq_tasks_open_room_title` is rebuilt to exclude `abandoned` — an
  abandoned task must release its (property, room, title) slot.

Revision ID: n6g4a8c0e2f5
Revises: m5f3a7c9e1b4
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'n6g4a8c0e2f5'
down_revision: Union[str, Sequence[str], None] = 'm5f3a7c9e1b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CLOSED = "('completed', 'cancelled', 'abandoned')"
_CLOSED_OLD = "('completed', 'cancelled')"


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(
            sa.Column("abandoned_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(
            sa.Column("abandoned_reason", sa.String(length=64), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "abandoned_from_status", sa.String(length=32), nullable=True
            )
        )
        batch.add_column(
            sa.Column("operational_date", sa.String(length=10), nullable=True)
        )
    with op.batch_alter_table("companies") as batch:
        batch.add_column(
            sa.Column(
                "operational_day_start",
                sa.String(length=5),
                nullable=False,
                server_default="06:00",
            )
        )
    op.drop_index("uq_tasks_open_room_title", table_name="tasks")
    op.create_index(
        "uq_tasks_open_room_title",
        "tasks",
        ["property_id", "room_id", "title"],
        unique=True,
        postgresql_where=sa.text(
            f"room_id IS NOT NULL AND status NOT IN {_CLOSED}"
        ),
        sqlite_where=sa.text(
            f"room_id IS NOT NULL AND status NOT IN {_CLOSED}"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_tasks_open_room_title", table_name="tasks")
    op.create_index(
        "uq_tasks_open_room_title",
        "tasks",
        ["property_id", "room_id", "title"],
        unique=True,
        postgresql_where=sa.text(
            f"room_id IS NOT NULL AND status NOT IN {_CLOSED_OLD}"
        ),
        sqlite_where=sa.text(
            f"room_id IS NOT NULL AND status NOT IN {_CLOSED_OLD}"
        ),
    )
    with op.batch_alter_table("companies") as batch:
        batch.drop_column("operational_day_start")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("operational_date")
        batch.drop_column("abandoned_from_status")
        batch.drop_column("abandoned_reason")
        batch.drop_column("abandoned_at")
