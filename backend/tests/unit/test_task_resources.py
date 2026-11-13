"""Grouped-task resource identity — `attach_task_resources` + `beds` on
the wire. Beds persist on `Task.bed_ids` as uuid strings; the API must
resolve them into readable identifiers so staff can see exactly which
physical beds a grouped cleaning task covers."""
import uuid

from app.models.structure import Bed
from app.models.task import Task
from app.schemas.workspace import task_out
from app.services.task_resources import attach_task_resources, natural_label_key


def _mk_task(prop, dorm, beds=None, **kw):
    t = Task(
        property_id=prop.id,
        title="Cleaning — Dorm A",
        status="assigned",
        task_type="fixed",
        work_type="cleaning",
        dorm_id=dorm.id if dorm else None,
        dorm_name=dorm.name if dorm else None,
        bed_ids=[str(b.id) for b in beds] if beds else None,
        **kw,
    )
    return t


async def test_grouped_task_resolves_every_bed(session, seed):
    """A 5-bed cleaning task exposes all five bed numbers + statuses."""
    dorm, prop = seed["dorm"], seed["prop"]
    beds = [
        Bed(dorm_id=dorm.id, property_id=prop.id, bed_number=f"P2-{i:02d}")
        for i in (1, 3, 5, 8, 10)
    ]
    session.add_all(beds)
    await session.flush()  # ids mint on flush — bed_ids snapshots them
    task = _mk_task(prop, dorm, beds)
    session.add(task)
    await session.commit()

    await attach_task_resources(session, [task])
    out = task_out(task)

    assert [b["bed_number"] for b in out["beds"]] == [
        "P2-01", "P2-03", "P2-05", "P2-08", "P2-10",
    ]
    assert all(b["status"] == "available" for b in out["beds"])
    assert all(uuid.UUID(b["bed_uid"]) for b in out["beds"])
    # backward compat — raw uid list still on the wire
    assert sorted(out["bed_uids"]) == sorted(str(b.id) for b in beds)
    assert out["dorm_name"] == "Dorm A"


async def test_bed_list_has_no_duplicates(session, seed):
    dorm, prop = seed["dorm"], seed["prop"]
    bed = seed["bed"]
    task = _mk_task(prop, dorm, beds=[bed])
    task.bed_ids = [str(bed.id), str(bed.id), str(bed.id)]
    session.add(task)
    await session.commit()

    await attach_task_resources(session, [task])
    out = task_out(task)
    assert [b["bed_number"] for b in out["beds"]] == ["Bed 01"]


async def test_missing_bed_is_skipped(session, seed):
    """A bed_id pointing at a deleted/foreign bed is dropped silently —
    it must never break the list response."""
    dorm, prop = seed["dorm"], seed["prop"]
    task = _mk_task(prop, dorm, beds=[seed["bed"]])
    task.bed_ids = [str(seed["bed"].id), str(uuid.uuid4()), "not-a-uuid"]
    session.add(task)
    await session.commit()

    await attach_task_resources(session, [task])
    out = task_out(task)
    assert [b["bed_number"] for b in out["beds"]] == ["Bed 01"]


async def test_task_without_beds_stays_backward_compatible(session, seed):
    task = _mk_task(seed["prop"], None)
    task.room_number = "101"
    session.add(task)
    await session.commit()

    await attach_task_resources(session, [task])
    out = task_out(task)
    assert out["beds"] is None
    assert out["bed_uids"] is None
    assert out["title"] == "Cleaning — Dorm A"


async def test_natural_ordering_of_identifiers():
    keys = ["P2-1", "P2-10", "P2-2", "Bed 01", "Bed 10", "Bed 2"]
    assert sorted(keys, key=natural_label_key) == [
        "Bed 01", "Bed 2", "Bed 10", "P2-1", "P2-2", "P2-10",
    ]


async def test_completion_fields_unaffected(session, seed):
    """The resolved list is additive — lifecycle fields serialize exactly
    as before so completion/review flows are untouched."""
    dorm, prop = seed["dorm"], seed["prop"]
    task = _mk_task(prop, dorm, beds=[seed["bed"]])
    task.status = "submitted"
    session.add(task)
    await session.commit()

    await attach_task_resources(session, [task])
    out = task_out(task)
    assert out["status"] == "submitted"
    assert out["completion_submissions"] == []
    assert out["beds"][0]["bed_number"] == "Bed 01"
