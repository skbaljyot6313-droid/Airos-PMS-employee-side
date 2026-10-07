"""washroom resources

Revision ID: e9f2a4b6c8d0
Revises: d8e1f2a3b4c5
Create Date: 2026-09-28 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e9f2a4b6c8d0"
down_revision: Union[str, Sequence[str], None] = "d8e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "washrooms",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("zone_id", sa.Uuid(), nullable=True),
        sa.Column("area_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("washroom_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False,
                  server_default="available"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["area_id"], ["areas.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["property_id"], ["properties.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["zone_id"], ["zones.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "property_id", "name", name="uq_washrooms_property_name"
        ),
    )
    op.create_index("ix_washrooms_property_id", "washrooms", ["property_id"])
    op.create_index("ix_washrooms_zone_id", "washrooms", ["zone_id"])
    op.create_index("ix_washrooms_area_id", "washrooms", ["area_id"])

    op.add_column("tasks", sa.Column("washroom_id", sa.Uuid(), nullable=True))
    op.add_column(
        "tasks", sa.Column("washroom_name", sa.String(length=255), nullable=True)
    )
    op.create_index("ix_tasks_washroom_id", "tasks", ["washroom_id"])
    op.create_foreign_key(
        "fk_tasks_washroom_id", "tasks", "washrooms",
        ["washroom_id"], ["id"], ondelete="SET NULL",
    )

    op.add_column(
        "maintenance_tickets", sa.Column("washroom_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "maintenance_tickets",
        sa.Column("washroom_name", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_maintenance_tickets_washroom_id",
        "maintenance_tickets",
        ["washroom_id"],
    )
    op.create_foreign_key(
        "fk_maintenance_tickets_washroom_id", "maintenance_tickets",
        "washrooms", ["washroom_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_maintenance_tickets_washroom_id",
        "maintenance_tickets",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_maintenance_tickets_washroom_id", table_name="maintenance_tickets"
    )
    op.drop_column("maintenance_tickets", "washroom_name")
    op.drop_column("maintenance_tickets", "washroom_id")

    op.drop_constraint("fk_tasks_washroom_id", "tasks", type_="foreignkey")
    op.drop_index("ix_tasks_washroom_id", table_name="tasks")
    op.drop_column("tasks", "washroom_name")
    op.drop_column("tasks", "washroom_id")

    op.drop_index("ix_washrooms_area_id", table_name="washrooms")
    op.drop_index("ix_washrooms_zone_id", table_name="washrooms")
    op.drop_index("ix_washrooms_property_id", table_name="washrooms")
    op.drop_table("washrooms")
