"""task completion submissions

Revision ID: d8e1f2a3b4c5
Revises: c7e8f1a2b3d4
Create Date: 2026-09-29 13:00:00.000000
"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "d8e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = "c7e8f1a2b3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


tasks = sa.table(
    "tasks",
    sa.column("id", sa.Uuid()),
    sa.column("status", sa.String()),
    sa.column("employee_id", sa.Uuid()),
)

events = sa.table(
    "task_history_events",
    sa.column("id", sa.Uuid()),
    sa.column("task_id", sa.Uuid()),
    sa.column("type", sa.String()),
    sa.column("at", sa.DateTime(timezone=True)),
    sa.column("actor_name", sa.String()),
    sa.column("note", sa.String()),
)

submissions = sa.table(
    "task_completion_submissions",
    sa.column("id", sa.Uuid()),
    sa.column("task_id", sa.Uuid()),
    sa.column("history_event_id", sa.Uuid()),
    sa.column("employee_id", sa.Uuid()),
    sa.column("employee_name", sa.String()),
    sa.column("attempt_number", sa.Integer()),
    sa.column("status", sa.String()),
    sa.column("submitted_at", sa.DateTime(timezone=True)),
    sa.column("reviewed_at", sa.DateTime(timezone=True)),
    sa.column("reviewed_by_id", sa.Uuid()),
    sa.column("reviewed_by_name", sa.String()),
    sa.column("review_comment", sa.String()),
    sa.column("created_at", sa.DateTime(timezone=True)),
)

images = sa.table(
    "task_completion_images",
    sa.column("id", sa.Uuid()),
    sa.column("task_id", sa.Uuid()),
    sa.column("submission_id", sa.Uuid()),
    sa.column("history_event_id", sa.Uuid()),
    sa.column("created_by_name", sa.String()),
    sa.column("created_at", sa.DateTime(timezone=True)),
)


def _submission_status(task_status: str, event_type: str, review_type: str | None,
                       is_latest: bool) -> str:
    if event_type == "completed" or review_type in {"approved", "completed"}:
        return "approved"
    if review_type == "rejected" or not (is_latest and task_status == "submitted"):
        return "disapproved"
    return "pending"


def upgrade() -> None:
    op.create_table(
        "task_completion_submissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("history_event_id", sa.Uuid(), nullable=True),
        sa.Column("employee_id", sa.Uuid(), nullable=True),
        sa.Column("employee_name", sa.String(length=255), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "submitted_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_by_name", sa.String(length=255), nullable=True),
        sa.Column("review_comment", sa.String(length=2000), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["history_event_id"], ["task_history_events.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "attempt_number", name="uq_task_attempt"),
        sa.UniqueConstraint("history_event_id", name="uq_completion_submission_event"),
    )
    op.create_index(
        "ix_task_completion_submissions_task_id",
        "task_completion_submissions", ["task_id"],
    )
    op.create_index(
        "ix_task_completion_submissions_employee_id",
        "task_completion_submissions", ["employee_id"],
    )
    op.create_index(
        "ix_task_completion_submissions_status",
        "task_completion_submissions", ["status"],
    )

    op.add_column("task_completion_images", sa.Column("submission_id", sa.Uuid(), nullable=True))
    op.create_index(
        "ix_task_completion_images_submission_id",
        "task_completion_images", ["submission_id"],
    )
    op.create_foreign_key(
        "fk_completion_image_submission",
        "task_completion_images", "task_completion_submissions",
        ["submission_id"], ["id"], ondelete="SET NULL",
    )

    conn = op.get_bind()
    task_rows = conn.execute(
        sa.select(tasks.c.id, tasks.c.status, tasks.c.employee_id)
    ).all()
    for task_id, task_status, employee_id in task_rows:
        event_rows = conn.execute(
            sa.select(
                events.c.id, events.c.type, events.c.at,
                events.c.actor_name, events.c.note,
            ).where(
                events.c.task_id == task_id,
                events.c.type.in_(("submitted", "completed")),
            ).order_by(events.c.at, events.c.id)
        ).all()
        latest_submitted = next(
            (e[0] for e in reversed(event_rows) if e[1] == "submitted"), None
        )
        inserts = []
        event_submissions = {}
        for index, (event_id, event_type, event_at, actor, note) in enumerate(event_rows, 1):
            review = conn.execute(
                sa.select(events.c.type, events.c.at, events.c.actor_name, events.c.note)
                .where(
                    events.c.task_id == task_id,
                    events.c.at >= event_at,
                    events.c.id != event_id,
                    events.c.type.in_(("approved", "rejected", "completed")),
                ).order_by(events.c.at, events.c.id).limit(1)
            ).first()
            review_type = review[0] if review else None
            reviewed_at = review[1] if review else None
            reviewer = review[2] if review else None
            comment = review[3] if review else None
            if event_type == "completed" and reviewed_at is None:
                reviewed_at = event_at
                reviewer = actor
                comment = note
            submission_id = uuid.uuid4()
            event_submissions[event_id] = submission_id
            inserts.append({
                "id": submission_id,
                "task_id": task_id,
                "history_event_id": event_id,
                "employee_id": employee_id,
                "employee_name": actor,
                "attempt_number": index,
                "status": _submission_status(
                    task_status, event_type, review_type,
                    event_id == latest_submitted,
                ),
                "submitted_at": event_at,
                "reviewed_at": reviewed_at,
                "reviewed_by_id": None,
                "reviewed_by_name": reviewer,
                "review_comment": comment,
                "created_at": event_at,
            })
        if inserts:
            conn.execute(sa.insert(submissions).values(inserts))
        for event_id, submission_id in event_submissions.items():
            conn.execute(
                sa.update(images)
                .where(images.c.history_event_id == event_id)
                .values(submission_id=submission_id)
            )

        unattached = conn.execute(
            sa.select(images.c.id, images.c.created_by_name, images.c.created_at)
            .where(
                images.c.task_id == task_id,
                images.c.submission_id.is_(None),
            ).order_by(images.c.created_at, images.c.id)
        ).all()
        if unattached:
            submission_id = uuid.uuid4()
            status = {
                "submitted": "pending",
                "completed": "approved",
            }.get(task_status, "disapproved")
            conn.execute(sa.insert(submissions).values({
                "id": submission_id,
                "task_id": task_id,
                "history_event_id": None,
                "employee_id": employee_id,
                "employee_name": unattached[0][1],
                "attempt_number": len(event_rows) + 1,
                "status": status,
                "submitted_at": unattached[0][2],
                "reviewed_at": None,
                "reviewed_by_id": None,
                "reviewed_by_name": None,
                "review_comment": None,
                "created_at": unattached[0][2],
            }))
            conn.execute(
                sa.update(images)
                .where(images.c.id.in_([row[0] for row in unattached]))
                .values(submission_id=submission_id)
            )


def downgrade() -> None:
    op.drop_constraint(
        "fk_completion_image_submission", "task_completion_images", type_="foreignkey"
    )
    op.drop_index(
        "ix_task_completion_images_submission_id",
        table_name="task_completion_images",
    )
    op.drop_column("task_completion_images", "submission_id")
    op.drop_index(
        "ix_task_completion_submissions_status",
        table_name="task_completion_submissions",
    )
    op.drop_index(
        "ix_task_completion_submissions_employee_id",
        table_name="task_completion_submissions",
    )
    op.drop_index(
        "ix_task_completion_submissions_task_id",
        table_name="task_completion_submissions",
    )
    op.drop_table("task_completion_submissions")
