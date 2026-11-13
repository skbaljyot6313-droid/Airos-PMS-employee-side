"""Employee language preferences.

One row per employee (unique employee_id) holding UI text and TTS audio
language choices. Defaults are 'en' so existing employees need no action;
absence of a row simply means defaults.

Revision ID: x8b3d6f1a4c7
Revises: w3b7d9f1a4c6
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "x8b3d6f1a4c7"
down_revision: Union[str, Sequence[str], None] = "w3b7d9f1a4c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "employee_preferences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column(
            "text_language",
            sa.String(length=8),
            server_default=sa.text("'en'"),
            nullable=False,
        ),
        sa.Column(
            "audio_language",
            sa.String(length=8),
            server_default=sa.text("'en'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"], ["employees.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "employee_id", name="uq_employee_preferences_employee_id"
        ),
    )
    op.create_index(
        "ix_employee_preferences_employee_id",
        "employee_preferences",
        ["employee_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_employee_preferences_employee_id",
        table_name="employee_preferences",
    )
    op.drop_table("employee_preferences")
