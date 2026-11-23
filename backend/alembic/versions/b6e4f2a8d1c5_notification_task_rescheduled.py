"""notifications.type — allow 'task_rescheduled'.

The unified work calendar sends employees a notification when an
assignment is rescheduled (both backends emit ``task_rescheduled``).
The original ``ck_notifications_type`` CHECK predates that type, so
reschedule writes would fail outright. Drop and recreate the constraint
with the widened set — no data touched, no rows rewritten.

Additive/backward-compatible. Shared schema: this revision must be
mirrored verbatim in the super-admin repo's chain — do NOT stamp over it.

Revision ID: b6e4f2a8d1c5
Revises: a4b8e2f1c9d3
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b6e4f2a8d1c5'
down_revision: Union[str, Sequence[str], None] = 'a4b8e2f1c9d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TYPES_NEW = (
    "'task_assigned', 'task_reassigned', 'task_cancelled', "
    "'task_rescheduled', 'task_due_soon', 'task_overdue', "
    "'submission_approved', 'submission_disapproved', "
    "'ticket_assigned', 'ticket_disapproved'"
)
_TYPES_OLD = (
    "'task_assigned', 'task_reassigned', 'task_cancelled', "
    "'task_due_soon', 'task_overdue', 'submission_approved', "
    "'submission_disapproved', 'ticket_assigned', 'ticket_disapproved'"
)


def upgrade() -> None:
    op.drop_constraint("ck_notifications_type", "notifications", type_="check")
    op.create_check_constraint(
        "ck_notifications_type",
        "notifications",
        f"type IN ({_TYPES_NEW})",
    )


def downgrade() -> None:
    op.drop_constraint("ck_notifications_type", "notifications", type_="check")
    op.create_check_constraint(
        "ck_notifications_type",
        "notifications",
        f"type IN ({_TYPES_OLD})",
    )
