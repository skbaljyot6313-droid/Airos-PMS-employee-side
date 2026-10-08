"""task series_id for repetitive lineage

Revision ID: b7f3c21a9e04
Revises: 6920e7a5283e
Create Date: 2026-09-24 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7f3c21a9e04'
down_revision: Union[str, Sequence[str], None] = '6920e7a5283e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tasks', sa.Column('series_id', sa.Uuid(), nullable=True))
    op.create_index('ix_tasks_series_id', 'tasks', ['series_id'])
    op.create_foreign_key(
        'fk_tasks_series_id', 'tasks', 'tasks', ['series_id'], ['id'],
        ondelete='SET NULL',
    )
    # Existing repetitive tasks become their own series root.
    op.execute(
        "UPDATE tasks SET series_id = id "
        "WHERE task_type = 'repetitive' AND recurrence IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_constraint('fk_tasks_series_id', 'tasks', type_='foreignkey')
    op.drop_index('ix_tasks_series_id', table_name='tasks')
    op.drop_column('tasks', 'series_id')
