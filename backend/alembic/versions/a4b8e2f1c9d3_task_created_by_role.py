"""task created_by_role — actor role at creation.

The unified work calendar distinguishes assignments created by Super
Admin staff from ones created by Department Heads on mobile. ``created_by_name``
already carries the display name; this adds the role so every interface
(SA work calendar, department views, employee calendar) can label the
source without guessing from names or history notes.

* ``tasks.created_by_role`` — nullable String(32); stamped at creation
  with the acting user's role. NULL on pre-existing rows and
  machine-generated work (template/checkout/rollover spawns keep NULL
  unless a user action creates them).

Additive/backward-compatible. Shared schema: this revision must be
mirrored verbatim in the super-admin repo's chain — do NOT stamp over it.

Revision ID: a4b8e2f1c9d3
Revises: n3f6a9c1e4d7
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4b8e2f1c9d3'
down_revision: Union[str, Sequence[str], None] = 'n3f6a9c1e4d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'tasks',
        sa.Column('created_by_role', sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('tasks', 'created_by_role')
