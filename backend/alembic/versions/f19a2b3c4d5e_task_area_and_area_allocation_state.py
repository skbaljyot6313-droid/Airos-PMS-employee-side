"""task area and area allocation state

Revision ID: f19a2b3c4d5e
Revises: e8b2c4d6f1a7
Create Date: 2026-09-28 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f19a2b3c4d5e"
down_revision: Union[str, Sequence[str], None] = "e8b2c4d6f1a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("area_id", sa.Uuid(), nullable=True))
    op.create_index("ix_tasks_area_id", "tasks", ["area_id"])
    op.create_foreign_key(
        "fk_tasks_area_id", "tasks", "areas", ["area_id"], ["id"],
        ondelete="SET NULL",
    )
    op.execute("""
        UPDATE tasks AS t
        SET zone_id = COALESCE(r.zone_id, t.zone_id),
            area_id = COALESCE(z.area_id, r.area_id)
        FROM rooms AS r
        LEFT JOIN zones AS z ON z.id = r.zone_id
        WHERE t.room_id = r.id
    """)
    op.execute("""
        UPDATE tasks AS t
        SET zone_id = COALESCE(d.zone_id, t.zone_id),
            area_id = COALESCE(z.area_id, d.area_id)
        FROM dorms AS d
        LEFT JOIN zones AS z ON z.id = d.zone_id
        WHERE t.dorm_id = d.id AND t.room_id IS NULL
    """)
    op.execute("""
        UPDATE tasks AS t
        SET area_id = z.area_id
        FROM zones AS z
        WHERE t.area_id IS NULL AND t.zone_id = z.id
    """)
    op.create_table(
        "area_allocation_state",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("area_id", sa.Uuid(), nullable=False),
        sa.Column("last_assigned_employee_id", sa.Uuid(), nullable=True),
        sa.Column("last_assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["area_id"], ["areas.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("area_id", name="uq_area_allocation_state_area"),
    )
    op.create_index("ix_area_allocation_state_area_id", "area_allocation_state", ["area_id"])
    op.create_index("ix_area_allocation_state_property_id", "area_allocation_state", ["property_id"])


def downgrade() -> None:
    op.drop_index("ix_area_allocation_state_property_id", table_name="area_allocation_state")
    op.drop_index("ix_area_allocation_state_area_id", table_name="area_allocation_state")
    op.drop_table("area_allocation_state")
    op.drop_constraint("fk_tasks_area_id", "tasks", type_="foreignkey")
    op.drop_index("ix_tasks_area_id", table_name="tasks")
    op.drop_column("tasks", "area_id")
