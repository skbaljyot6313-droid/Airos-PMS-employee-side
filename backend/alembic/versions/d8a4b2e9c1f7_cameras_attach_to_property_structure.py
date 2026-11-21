"""VA cameras attach to existing property structure.

Replaces the standalone ``camera_sections`` registry with direct FKs into
the property's existing ``areas``/``zones`` — camera "sections" are the
real property zones (or whole areas), not a parallel taxonomy.

- drops ``cameras.section_id`` + the ``camera_sections`` table;
- adds ``cameras.area_id`` / ``cameras.zone_id`` (nullable, SET NULL).

A camera assigned to a zone inherits its area for grouping; ``area_id``
without ``zone_id`` is area-level placement.

Mirrored verbatim in the employee repo's chain — do NOT stamp over it.

Revision ID: d8a4b2e9c1f7
Revises: c7f3a8b1d9e4
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8a4b2e9c1f7'
down_revision: Union[str, Sequence[str], None] = 'c7f3a8b1d9e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cameras", sa.Column("area_id", sa.Uuid(), nullable=True))
    op.add_column("cameras", sa.Column("zone_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_cameras_area_id", "cameras", "areas", ["area_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_cameras_zone_id", "cameras", "zones", ["zone_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_cameras_area_id", "cameras", ["area_id"])
    op.create_index("ix_cameras_zone_id", "cameras", ["zone_id"])

    op.drop_constraint("cameras_section_id_fkey", "cameras", type_="foreignkey")
    op.drop_index("ix_cameras_section_id", table_name="cameras")
    op.drop_column("cameras", "section_id")
    op.drop_index("ix_camera_sections_property_id", table_name="camera_sections")
    op.drop_table("camera_sections")


def downgrade() -> None:
    op.create_table(
        "camera_sections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("property_id", "name", name="uq_camera_sections_property_name"),
    )
    op.create_index("ix_camera_sections_property_id", "camera_sections", ["property_id"])
    op.add_column("cameras", sa.Column("section_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "cameras_section_id_fkey", "cameras", "camera_sections",
        ["section_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_cameras_section_id", "cameras", ["section_id"])
    op.drop_index("ix_cameras_zone_id", table_name="cameras")
    op.drop_index("ix_cameras_area_id", table_name="cameras")
    op.drop_constraint("fk_cameras_zone_id", "cameras", type_="foreignkey")
    op.drop_constraint("fk_cameras_area_id", "cameras", type_="foreignkey")
    op.drop_column("cameras", "zone_id")
    op.drop_column("cameras", "area_id")
