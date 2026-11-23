"""sections — functional grouping of areas (Stay, Kitchen, Pool, Reception).

Adds a `sections` table between property and area:
    property → section → area → zone → units

* ``sections`` — id, property_id (CASCADE), name (unique per property),
  code (SECTION-###), description, status, timestamps.
* ``areas.section_id`` — nullable FK, SET NULL on section delete so
  removing a section never deletes areas/zones/units.

Both columns/tables are additive — existing areas keep section_id NULL
(ungrouped). Owned by the Super Admin backend; the Employee backend maps
``areas`` read-only and ignores the new column, so this revision must be
mirrored verbatim in the employee repo's chain — do NOT stamp over it.

Revision ID: z6f1c8a4d2e5
Revises: g8c3e0f5b2d9
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'z6f1c8a4d2e5'
down_revision: Union[str, Sequence[str], None] = 'g8c3e0f5b2d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'sections',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('property_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('code', sa.String(length=32), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('property_id', 'name', name='uq_sections_property_name'),
    )
    op.create_index('ix_sections_property_id', 'sections', ['property_id'])
    op.add_column(
        'areas',
        sa.Column('section_id', sa.Uuid(), nullable=True),
    )
    op.create_index('ix_areas_section_id', 'areas', ['section_id'])
    op.create_foreign_key(
        'fk_areas_section_id_sections', 'areas', 'sections',
        ['section_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_areas_section_id_sections', 'areas', type_='foreignkey')
    op.drop_index('ix_areas_section_id', table_name='areas')
    op.drop_column('areas', 'section_id')
    op.drop_index('ix_sections_property_id', table_name='sections')
    op.drop_table('sections')
