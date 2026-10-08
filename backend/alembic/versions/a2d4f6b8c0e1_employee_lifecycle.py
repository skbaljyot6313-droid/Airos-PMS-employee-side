"""employee lifecycle timestamps

Revision ID: a2d4f6b8c0e1
Revises: f19a2b3c4d5e
Create Date: 2026-09-28 16:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a2d4f6b8c0e1"
down_revision: Union[str, Sequence[str], None] = "f19a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "employees",
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "employees",
        sa.Column("reactivated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("""
        UPDATE employees
        SET status = 'Deactivated'
        WHERE lower(status) IN ('inactive', 'deactivated')
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE employees
        SET status = 'Inactive'
        WHERE lower(status) = 'deactivated' AND deactivated_at IS NULL
    """)
    op.drop_column("employees", "reactivated_at")
    op.drop_column("employees", "deactivated_at")
