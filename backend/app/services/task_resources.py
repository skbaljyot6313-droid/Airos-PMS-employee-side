"""Resolve per-resource identities for grouped tasks.

Grouped cleaning tasks cover several physical resources (e.g. every dirty
bed in one dorm) but persist them only as `Task.bed_ids` — a JSON list of
uuid strings. `task_out` serializes those raw uuids as `bed_uids`; this
module resolves them once per response into readable resource dicts
(`bed_uid` + `bed_number` + `status`) and stashes them on the task as
`_bed_infos` for `task_out` to emit as `beds`.

Extensible: rooms, washroom fixtures and other grouped resources can get
the same treatment here without touching the task lifecycle.
"""

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.structure import Bed
from app.models.task import Task

_NUM_SPLIT = re.compile(r"(\d+)")


def natural_label_key(label: str):
    """Sort 'P2-2' before 'P2-10' — identifiers order the way staff read
    them, not by raw string comparison."""
    return [
        int(part) if part.isdigit() else part.lower()
        for part in _NUM_SPLIT.split(label or "")
    ]


async def attach_task_resources(
    session: AsyncSession, tasks: list[Task]
) -> None:
    """Batch-resolve `Task.bed_ids` -> `task._bed_infos` on each task.

    One SELECT for the whole page — never per task. Malformed uuid strings
    and beds that no longer exist are skipped silently (a deleted bed must
    not break the task list); duplicates collapse on first occurrence.
    """
    wanted: set[uuid.UUID] = set()
    for task in tasks:
        for raw in task.bed_ids or []:
            try:
                wanted.add(uuid.UUID(str(raw)))
            except (ValueError, TypeError, AttributeError):
                continue
    if not wanted:
        return

    res = await session.execute(select(Bed).where(Bed.id.in_(wanted)))
    by_id = {str(b.id): b for b in res.scalars()}

    for task in tasks:
        if not task.bed_ids:
            continue
        seen: set[uuid.UUID] = set()
        infos: list[dict] = []
        for raw in task.bed_ids:
            bed = by_id.get(str(raw))
            if bed is None or bed.id in seen:
                continue
            seen.add(bed.id)
            infos.append(
                {
                    "bed_uid": str(bed.id),
                    "bed_number": bed.bed_number,
                    "status": bed.status,
                }
            )
        infos.sort(key=lambda i: natural_label_key(i["bed_number"]))
        task._bed_infos = infos
