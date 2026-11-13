"""Push delivery tracking on notifications — the durable outbox.

Adds truthful per-notification push state (queued → dispatching →
accepted | retry_pending → failed | opened; 'delivered' is reserved for
independently confirmed device delivery, which FCM HTTP v1 cannot
provide and therefore stays unused). Existing rows get 'accepted':
they were created before tracking existed — treating them as accepted
keeps the sweep from resending every historical notification.

Revision ID: w3b7d9f1a4c6
Revises: v9f2b5c8d1e4
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "w3b7d9f1a4c6"
down_revision: Union[str, Sequence[str], None] = "v9f2b5c8d1e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column(
            "push_status", sa.String(24), nullable=False,
            server_default=sa.text("'queued'"),
        ),
    )
    op.add_column(
        "notifications",
        sa.Column(
            "push_attempts", sa.Integer(), nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "notifications",
        sa.Column(
            "push_next_attempt_at", sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "notifications",
        sa.Column("push_last_error", sa.String(120), nullable=True),
    )
    op.add_column(
        "notifications",
        sa.Column("push_provider_ref", sa.String(255), nullable=True),
    )
    op.add_column(
        "notifications",
        sa.Column(
            "push_updated_at", sa.DateTime(timezone=True), nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_notifications_push_status",
        "notifications",
        "push_status IN ("
        "'queued', 'dispatching', 'retry_pending', 'accepted', "
        "'failed', 'delivered', 'opened'"
        ")",
    )
    op.create_index(
        "ix_notif_push_due",
        "notifications",
        ["push_status", "push_next_attempt_at"],
    )
    # Historical rows: no dispatch record existed — mark accepted so the
    # outbox sweep never replays old notifications to devices.
    op.execute(
        "UPDATE notifications SET push_status = 'accepted' "
        "WHERE push_status = 'queued'"
    )


def downgrade() -> None:
    op.drop_index("ix_notif_push_due", table_name="notifications")
    op.drop_constraint(
        "ck_notifications_push_status", "notifications", type_="check"
    )
    for col in (
        "push_updated_at",
        "push_provider_ref",
        "push_last_error",
        "push_next_attempt_at",
        "push_attempts",
        "push_status",
    ):
        op.drop_column("notifications", col)
