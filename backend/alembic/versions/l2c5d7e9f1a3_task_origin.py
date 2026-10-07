"""Task provenance column — why a task exists.

`tasks.origin` ('manual' | 'checkout' | 'template' | 'automation') is a
reliable semantic marker for checkout-generated cleaning. Business logic
must never match on the title string ("Checkout cleaning — 101") to tell
a checkout task from a queued cleaning task.

Revision ID: l2c5d7e9f1a3
Revises: k8b3d4f6a1c2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'l2c5d7e9f1a3'
down_revision: Union[str, Sequence[str], None] = 'k8b3d4f6a1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(
            sa.Column(
                "origin", sa.String(length=32), nullable=False,
                server_default="manual",
            )
        )
    # historical checkout cleanings were created under the fixed title
    # prefix — backfill them so reporting/derivation is consistent
    op.execute(
        sa.text(
            "UPDATE tasks SET origin = 'checkout' "
            "WHERE origin = 'manual' AND title LIKE 'Checkout cleaning — %'"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("origin")
