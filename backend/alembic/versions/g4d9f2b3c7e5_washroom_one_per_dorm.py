"""one attached washroom per dorm

Revises: f3c8e1a2b6d4
Create Date: 2026-09-29

Unique constraint on washrooms.dorm_id — a dorm can own at most one
attached washroom. NULL dorm_ids are distinct in Postgres, so
zone-level facilities are unaffected.

"""
from alembic import op
import sqlalchemy as sa

revision = "g4d9f2b3c7e5"
down_revision = "f3c8e1a2b6d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_washrooms_dorm_id", "washrooms", ["dorm_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_washrooms_dorm_id", "washrooms", type_="unique")
