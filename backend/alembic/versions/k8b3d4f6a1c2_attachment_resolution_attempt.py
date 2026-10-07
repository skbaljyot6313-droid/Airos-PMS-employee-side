"""attachment resolution attempt

Resolution attachments get an iteration number so evidence from the first
submission and a disapproved→resubmitted round stay distinguishable.
NULL (existing rows) reads as attempt 1.

Revision ID: k8b3d4f6a1c2
Revises: j7a2c3e5f9b1
Create Date: 2026-09-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'k8b3d4f6a1c2'
down_revision: Union[str, Sequence[str], None] = 'j7a2c3e5f9b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'maintenance_ticket_attachments',
        sa.Column('attempt', sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('maintenance_ticket_attachments', 'attempt')
