"""departments.is_system — non-deletable auto-provisioned departments

Revision ID: e6a3c9f1b8d4
Revises: d4f1b8a3e7c2
"""
from alembic import op
import sqlalchemy as sa

revision = "e6a3c9f1b8d4"
down_revision = "d4f1b8a3e7c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "departments",
        sa.Column(
            "is_system",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("departments", "is_system")
