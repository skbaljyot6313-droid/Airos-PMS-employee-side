"""washroom dorm ownership — per-dorm independent configurations

Revises: e2b7d4a8c1f5
Create Date: 2026-09-29

Adds `washrooms.dorm_id` → dorms. Set = an attached washroom owned by
exactly one dorm (independent fixture configuration per dorm); NULL =
zone-level/common facility. CASCADE — attached washrooms die with
their dorm, matching the hierarchical-delete model.

Existing washrooms have dorm_id NULL and remain zone-level facilities —
no data is lost or re-parented.

"""
from alembic import op
import sqlalchemy as sa

revision = "f3c8e1a2b6d4"
down_revision = "e2b7d4a8c1f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("washrooms", sa.Column("dorm_id", sa.Uuid(), nullable=True))
    op.create_index("ix_washrooms_dorm_id", "washrooms", ["dorm_id"])
    op.create_foreign_key(
        "fk_washrooms_dorm_id", "washrooms", "dorms",
        ["dorm_id"], ["id"], ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_washrooms_dorm_id", "washrooms", type_="foreignkey")
    op.drop_index("ix_washrooms_dorm_id", table_name="washrooms")
    op.drop_column("washrooms", "dorm_id")
