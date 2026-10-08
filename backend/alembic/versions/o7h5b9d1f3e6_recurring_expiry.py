"""Recurring-instance validity window + series occurrence uniqueness.

- `tasks` gains `scheduled_for` (the scheduled occurrence instant) and
  `expires_at` (the next scheduled boundary — the instance's hard
  validity end, set at generation and never extended by downtime).
- `ix_tasks_expires_at` partial index supports the expiry sweep
  (WHERE expires_at <= now AND status IN expirable).
- `uq_tasks_series_due` is the DB-authoritative dedupe for the
  repetitive-series sweep/on-completion spawn racing the same slot:
  one task per (series_id, due_date) for repetitive rows.
- `scheduled_for` is backfilled for template-generated tasks from the
  TemplateGeneration ledger (occurrence_key = '<iso>|<target>').
  `expires_at` is intentionally NOT backfilled — legacy open rows keep
  being governed by the daily operational rollover; only instances
  generated after this migration carry a validity window.

Revision ID: o7h5b9d1f3e6
Revises: n6g4a8c0e2f5
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'o7h5b9d1f3e6'
down_revision: Union[str, Sequence[str], None] = 'n6g4a8c0e2f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SERIES_WHERE = (
    "task_type = 'repetitive' AND series_id IS NOT NULL "
    "AND due_date IS NOT NULL"
)


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(
            sa.Column("scheduled_for", sa.DateTime(timezone=True),
                      nullable=True)
        )
        batch.add_column(
            sa.Column("expires_at", sa.DateTime(timezone=True),
                      nullable=True)
        )
    op.create_index(
        "ix_tasks_expires_at", "tasks", ["expires_at"],
        postgresql_where=sa.text("expires_at IS NOT NULL"),
        sqlite_where=sa.text("expires_at IS NOT NULL"),
    )
    op.create_index(
        "uq_tasks_series_due", "tasks", ["series_id", "due_date"],
        unique=True,
        postgresql_where=sa.text(_SERIES_WHERE),
        sqlite_where=sa.text(_SERIES_WHERE),
    )
    # Backfill the occurrence instant for template-generated tasks — the
    # ledger's occurrence_key encodes it verbatim. Non-PG engines (test
    # sqlite) have no template_generations rows needing this anyway.
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            UPDATE tasks SET scheduled_for =
                (split_part(tg.occurrence_key, '|', 1))::timestamptz
            FROM template_generations tg
            WHERE tg.ticket_id = tasks.id AND tg.ticket_kind = 'task'
              AND tasks.scheduled_for IS NULL
            """
        )


def downgrade() -> None:
    op.drop_index("uq_tasks_series_due", table_name="tasks")
    op.drop_index("ix_tasks_expires_at", table_name="tasks")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("expires_at")
        batch.drop_column("scheduled_for")
