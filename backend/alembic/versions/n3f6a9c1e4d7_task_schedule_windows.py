"""task schedule windows — end/break times and estimated duration.

Department-head allocated work carries a full daily schedule: start
(already on tasks.start_time), end, break window and estimated duration.
Adds four nullable columns so the employee calendar, the department-head
team calendar and the Super Admin work calendar all render the same
window without encoding it in the description.

* ``tasks.end_time``           — 'HH:MM' (nullable; window may cross
  midnight — consumers treat end < start as next-day).
* ``tasks.break_start_time``   — 'HH:MM', nullable.
* ``tasks.break_end_time``     — 'HH:MM', nullable.
* ``tasks.estimated_minutes``  — integer, nullable; net working estimate.

All columns are additive/backward-compatible — existing rows keep NULL.
This revision is shared schema: it must be mirrored verbatim in the
super-admin repo's chain — do NOT stamp over it.

Revision ID: n3f6a9c1e4d7
Revises: c4e8f2a7d9b1
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'n3f6a9c1e4d7'
down_revision: Union[str, Sequence[str], None] = 'c4e8f2a7d9b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tasks', sa.Column('end_time', sa.String(length=16), nullable=True))
    op.add_column('tasks', sa.Column('break_start_time', sa.String(length=16), nullable=True))
    op.add_column('tasks', sa.Column('break_end_time', sa.String(length=16), nullable=True))
    op.add_column('tasks', sa.Column('estimated_minutes', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('tasks', 'estimated_minutes')
    op.drop_column('tasks', 'break_end_time')
    op.drop_column('tasks', 'break_start_time')
    op.drop_column('tasks', 'end_time')
