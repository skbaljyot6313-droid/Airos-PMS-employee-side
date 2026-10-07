"""backfill task completion images

Revision ID: c7e8f1a2b3d4
Revises: b4c6d8e0f2a1
Create Date: 2026-09-29 12:30:00.000000
"""
from typing import Sequence, Union
from datetime import timedelta
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "c7e8f1a2b3d4"
down_revision: Union[str, Sequence[str], None] = "b4c6d8e0f2a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


events = sa.table(
    "task_history_events",
    sa.column("id", sa.Uuid()),
    sa.column("task_id", sa.Uuid()),
    sa.column("at", sa.DateTime(timezone=True)),
    sa.column("actor_name", sa.String()),
    sa.column("photos", sa.JSON()),
)

images = sa.table(
    "task_completion_images",
    sa.column("id", sa.Uuid()),
    sa.column("task_id", sa.Uuid()),
    sa.column("history_event_id", sa.Uuid()),
    sa.column("url", sa.String()),
    sa.column("storage_key", sa.String()),
    sa.column("file_name", sa.String()),
    sa.column("created_by_id", sa.Uuid()),
    sa.column("created_by_name", sa.String()),
    sa.column("created_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.select(sa.func.count(images.c.id)).where(
        images.c.history_event_id == events.c.id
    ).scalar_subquery()

    rows = conn.execute(
        sa.select(
            events.c.id, events.c.task_id, events.c.at, events.c.actor_name,
            events.c.photos,
        ).where(events.c.photos.is_not(None), existing == 0)
    )
    inserts = []
    for event_id, task_id, event_at, actor_name, photos in rows:
        if not isinstance(photos, list):
            continue
        urls = list(dict.fromkeys(
            str(u).strip() for u in photos if str(u).strip()
        ))
        for index, url in enumerate(urls):
            inserts.append({
                "id": uuid.uuid4(),
                "task_id": task_id,
                "history_event_id": event_id,
                "url": url,
                "storage_key": None,
                "file_name": url.rsplit("/", 1)[-1] or None,
                "created_by_id": None,
                "created_by_name": actor_name,
                "created_at": (
                    event_at + timedelta(milliseconds=index)
                    if event_at else None
                ),
            })

    if inserts:
        conn.execute(sa.insert(images).values(inserts))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.delete(images).where(
            images.c.history_event_id.is_not(None),
            images.c.created_by_id.is_(None),
            images.c.storage_key.is_(None),
        )
    )
