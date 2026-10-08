"""employee area-level assignment

Revision ID: c4d81e7b2f05
Revises: b7f3c21a9e04
Create Date: 2026-09-24 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d81e7b2f05'
down_revision: Union[str, Sequence[str], None] = 'b7f3c21a9e04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('employees', sa.Column('area_id', sa.Uuid(), nullable=True))
    op.create_index('ix_employees_area_id', 'employees', ['area_id'])
    op.create_foreign_key(
        'fk_employees_area_id', 'employees', 'areas', ['area_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_employees_area_id', 'employees', type_='foreignkey')
    op.drop_index('ix_employees_area_id', table_name='employees')
    op.drop_column('employees', 'area_id')
