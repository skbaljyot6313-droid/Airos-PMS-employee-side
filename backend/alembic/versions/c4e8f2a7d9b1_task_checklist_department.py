"""tasks.checklist + tasks.department_id — department-head allocated work.

Department managers allocate work through the Super Admin app (and the
Employee app Team Work surface). Their work uses the same ``tasks`` table:

* ``checklist`` — a JSON list of manager-authored checklist items
  (``{"text": str, "required": bool}``), surfaced on task detail exactly
  like template checklists today. NULL keeps the legacy "checklist comes
  from the linked template" resolution.
* ``department_id`` — attribution + scoping column: which department the
  work belongs to, independent of who (if anyone) is assigned yet.
  SET NULL so deleting a department never deletes work history.

Additive, nullable — no backfill needed. Owned by the Super Admin
backend; the Employee repo maps ``tasks`` for its own reads, so this
revision must be mirrored verbatim in the employee repo's chain.

Revision ID: c4e8f2a7d9b1
Revises: b3d7e9a1f5c2
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c4e8f2a7d9b1'
down_revision: Union[str, Sequence[str], None] = 'b3d7e9a1f5c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'tasks',
        sa.Column('checklist', postgresql.JSON(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        'tasks',
        sa.Column(
            'department_id',
            sa.Uuid(),
            sa.ForeignKey('departments.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )
    op.create_index('ix_tasks_department_id', 'tasks', ['department_id'])


def downgrade() -> None:
    op.drop_index('ix_tasks_department_id', table_name='tasks')
    op.drop_column('tasks', 'department_id')
    op.drop_column('tasks', 'checklist')
