"""Task dorm/bed linkage — dorm_id, dorm_name, bed_ids

Dorm/bed cleaning tasks previously carried no unit link, so supervisor
approval could never release the covered beds (stuck in 'cleaning').
bed_ids is a JSON list of uuid strings — portable across postgres/sqlite.

Revision ID: e8b2c4d6f1a7
Revises: d9e2f04a1c33
Create Date: 2026-09-25 14:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'e8b2c4d6f1a7'
down_revision: Union[str, Sequence[str], None] = 'd9e2f04a1c33'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("dorm_id", sa.Uuid(), nullable=True))
    op.add_column("tasks", sa.Column("dorm_name", sa.String(length=255), nullable=True))
    op.add_column("tasks", sa.Column("bed_ids", sa.JSON(), nullable=True))
    op.create_foreign_key(
        "fk_tasks_dorm_id", "tasks", "dorms", ["dorm_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_tasks_dorm_id", "tasks", ["dorm_id"])


def downgrade() -> None:
    op.drop_index("ix_tasks_dorm_id", table_name="tasks")
    op.drop_constraint("fk_tasks_dorm_id", "tasks", type_="foreignkey")
    op.drop_column("tasks", "bed_ids")
    op.drop_column("tasks", "dorm_name")
    op.drop_column("tasks", "dorm_id")
