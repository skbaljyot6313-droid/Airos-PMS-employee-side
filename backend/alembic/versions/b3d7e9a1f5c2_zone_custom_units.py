"""zones.custom_units — free-text unit list for non-stay zones.

Non-stay zones (Kitchen, Pool, Back of House…) have no rooms/dorms/beds;
``custom_units`` is a JSONB list of arbitrary unit names (e.g.
"Walk-in freezer", "Fryer 2") managed from the Super Admin app.

Additive nullable-with-default column — existing zones get ``[]``.
Owned by the Super Admin backend; the Employee backend maps ``zones``
read-only, so this revision must be mirrored verbatim in the employee
repo's chain — do NOT stamp over it.

Revision ID: b3d7e9a1f5c2
Revises: z6f1c8a4d2e5
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b3d7e9a1f5c2'
down_revision: Union[str, Sequence[str], None] = 'z6f1c8a4d2e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'zones',
        sa.Column(
            'custom_units',
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default='[]',
        ),
    )


def downgrade() -> None:
    op.drop_column('zones', 'custom_units')
