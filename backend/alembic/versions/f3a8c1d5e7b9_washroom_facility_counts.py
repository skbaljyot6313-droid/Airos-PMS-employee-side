"""washroom facility counts

Revision ID: f3a8c1d5e7b9
Revises: e9f2a4b6c8d0
Create Date: 2026-09-28 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3a8c1d5e7b9"
down_revision: Union[str, Sequence[str], None] = "e9f2a4b6c8d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "washrooms",
        sa.Column("stall_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "washrooms",
        sa.Column("urinal_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "washrooms",
        sa.Column("shower_count", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("washrooms", "shower_count")
    op.drop_column("washrooms", "urinal_count")
    op.drop_column("washrooms", "stall_count")
