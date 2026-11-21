"""employee extended coverage — secondary zone + property-wide flag.

Mirrors the Super Admin backend's revision y5d8f2a6c4e1 verbatim — this
database is SHARED, and both services run their Alembic chains over the
same alembic_version row.

Adds ``secondary_zone_id`` (optional SECOND coverage zone; only
meaningful while ``zone_id`` is set) and ``covers_property``
(property-wide eligibility) to ``employees``. Owned and written by the
Super Admin backend; this service maps the columns read-only — coverage
queries (maintenance, allocation, live-location scoping) union primary
zone, secondary zone, area and property-wide scopes.

Do NOT "fix" divergent deployments by stamping over this revision — that
would misreport the shared schema state for the Super Admin backend.

Revision ID: y5d8f2a6c4e1
Revises: x8b3d6f1a4c7
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'y5d8f2a6c4e1'
down_revision: Union[str, Sequence[str], None] = 'x8b3d6f1a4c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'employees', sa.Column('secondary_zone_id', sa.Uuid(), nullable=True)
    )
    op.create_index(
        'ix_employees_secondary_zone_id', 'employees', ['secondary_zone_id']
    )
    op.create_foreign_key(
        'fk_employees_secondary_zone_id', 'employees', 'zones',
        ['secondary_zone_id'], ['id'], ondelete='SET NULL',
    )
    op.add_column(
        'employees',
        sa.Column(
            'covers_property', sa.Boolean(),
            server_default=sa.false(), nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column('employees', 'covers_property')
    op.drop_constraint(
        'fk_employees_secondary_zone_id', 'employees', type_='foreignkey'
    )
    op.drop_index('ix_employees_secondary_zone_id', table_name='employees')
    op.drop_column('employees', 'secondary_zone_id')
