"""Task work_type column — the selected domain work kind.

`tasks.work_type` stores the operating department chosen at creation
(cleaning | maintenance | inspection | housekeeping | …) so generated and
manual work items carry their kind durably instead of re-inferring it from
the title or template join on every allocation/reassignment.

Template-generated rows backfill from work_templates.template_type;
checkout/manual cleaning rows backfill from origin/title; the rest stay
NULL and keep resolving through the existing inference path.

Revision ID: m5f3a7c9e1b4
Revises: l2c5d7e9f1a3
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'm5f3a7c9e1b4'
down_revision: Union[str, Sequence[str], None] = 'l2c5d7e9f1a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(
            sa.Column("work_type", sa.String(length=32), nullable=True)
        )
    op.execute(
        sa.text(
            "UPDATE tasks SET work_type = wt.template_type "
            "FROM work_templates wt WHERE tasks.template_id = wt.id"
        )
    )
    op.execute(
        sa.text(
            "UPDATE tasks SET work_type = 'cleaning' "
            "WHERE work_type IS NULL AND ("
            "origin = 'checkout' "
            "OR lower(title) LIKE 'cleaning%' "
            "OR lower(title) LIKE 'checkout cleaning%' "
            "OR lower(title) LIKE 'clean %')"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("work_type")
