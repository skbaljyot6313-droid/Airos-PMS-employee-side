"""task completion images

Revision ID: b4c6d8e0f2a1
Revises: a2d4f6b8c0e1
Create Date: 2026-09-29 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b4c6d8e0f2a1"
down_revision: Union[str, Sequence[str], None] = "a2d4f6b8c0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "task_completion_images",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("history_event_id", sa.Uuid(), nullable=True),
        sa.Column("url", sa.String(length=2000), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_name", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["history_event_id"], ["task_history_events.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_task_completion_images_task_id",
        "task_completion_images",
        ["task_id"],
    )
    op.create_index(
        "ix_task_completion_images_history_event_id",
        "task_completion_images",
        ["history_event_id"],
    )
    op.create_index(
        "ix_task_completion_images_created_by_id",
        "task_completion_images",
        ["created_by_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_task_completion_images_created_by_id",
        table_name="task_completion_images",
    )
    op.drop_index(
        "ix_task_completion_images_history_event_id",
        table_name="task_completion_images",
    )
    op.drop_index(
        "ix_task_completion_images_task_id",
        table_name="task_completion_images",
    )
    op.drop_table("task_completion_images")
