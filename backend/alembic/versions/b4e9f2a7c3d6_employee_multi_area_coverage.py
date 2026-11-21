"""employee multi-area coverage — additional whole-area assignments.

Adds ``employee_area_assignments``: rows pair an employee with an
ADDITIONAL area they cover, on top of the primary ``employees.area_id``.
An employee may now cover several whole areas at once
(e.g. Entire DORMS *and* Entire PRIVATE ROOMS); coverage for work
allocation, maintenance scope, and directory filtering is the union of
``area_id`` + all rows here (plus the existing zone/property-wide modes).

Unique per (employee, area); both FKs CASCADE so deleting an area or an
employee removes the join row automatically. Owned by the Super Admin
backend; the Employee Backend shares this table and maps it read-only,
so this revision must be mirrored verbatim in the employee repo's
chain — do NOT stamp over it.

Revision ID: b4e9f2a7c3d6
Revises: y5d8f2a6c4e1
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4e9f2a7c3d6'
down_revision: Union[str, Sequence[str], None] = 'y5d8f2a6c4e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'employee_area_assignments',
        sa.Column(
            'id', sa.Uuid(),
            server_default=sa.text('gen_random_uuid()'), nullable=False,
        ),
        sa.Column('employee_id', sa.Uuid(), nullable=False),
        sa.Column('area_id', sa.Uuid(), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['employee_id'], ['employees.id'], ondelete='CASCADE',
            name='fk_employee_area_assignments_employee_id',
        ),
        sa.ForeignKeyConstraint(
            ['area_id'], ['areas.id'], ondelete='CASCADE',
            name='fk_employee_area_assignments_area_id',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'employee_id', 'area_id',
            name='uq_employee_area_assignments_employee_area',
        ),
    )
    op.create_index(
        'ix_employee_area_assignments_employee_id',
        'employee_area_assignments', ['employee_id'],
    )
    op.create_index(
        'ix_employee_area_assignments_area_id',
        'employee_area_assignments', ['area_id'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_employee_area_assignments_area_id',
        table_name='employee_area_assignments',
    )
    op.drop_index(
        'ix_employee_area_assignments_employee_id',
        table_name='employee_area_assignments',
    )
    op.drop_table('employee_area_assignments')
