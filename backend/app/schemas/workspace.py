"""
Workspace DTOs — serialization for the collections the frontend's
`loadWorkspace` fetches. Field names match frontend/src/types.ts exactly
(`*_uid` keys, snake_case).
"""

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy import inspect as sa_inspect

from app.models.employee import Employee
from app.models.property import Property
from app.models.structure import Area, Bed, Dorm, Room, Washroom, Zone
from app.models.task import (
    Task, TaskCompletionImage, TaskCompletionSubmission, TaskHistoryEvent,
)

T = TypeVar("T")


class ListResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    limit: int = 20


# ---------------------------------------------------------------------------
# Serializers — ORM → plain dict matching the frontend types
# ---------------------------------------------------------------------------

def property_out(p: Property) -> dict:
    return {
        "property_uid": str(p.id),
        "company_uid": str(p.company_id),
        "name": p.name,
        "code": p.code,
        "location": p.location,
        "city": p.city,
        "state": p.state,
        "status": p.status,
        "manager_employee_uid": str(p.manager_employee_id) if p.manager_employee_id else None,
        "manager_name": p.manager_name,
        "manager_email": p.manager_email,
        "manager_phone": p.manager_phone,
        "created_at": p.created_at,
    }


def area_out(a: Area) -> dict:
    return {
        "area_uid": str(a.id),
        "property_uid": str(a.property_id),
        "name": a.name,
        "code": a.code,
        "level_number": a.level_number,
        "description": a.description,
        "created_at": a.created_at,
    }


def zone_out(z: Zone) -> dict:
    return {
        "zone_uid": str(z.id),
        "property_uid": str(z.property_id),
        "area_uid": str(z.area_id) if z.area_id else None,
        "name": z.name,
        "code": z.code,
        "zone_type": z.zone_type,
        "floor": z.floor,
        "description": z.description,
        "created_at": z.created_at,
    }


async def mark_open_occupancy(
    session, *, rooms: list[Room] | None = None,
    beds: list[Bed] | None = None, dorms: list[Dorm] | None = None,
) -> None:
    """Stamp `_open_occupancy` on ORM rows so serializers can expose the
    occupancy axis (`is_occupied`) independently of `status`. One query
    for the whole batch — call before serializing collections. A dorm's
    occupancy is derived from its beds' open occupancies."""
    from sqlalchemy import or_, select

    from app.models.occupancy import Occupancy

    dorm_beds = [b for d in (dorms or []) for b in getattr(d, "beds", [])]
    room_ids = [r.id for r in (rooms or [])]
    bed_ids = [b.id for b in [*(beds or []), *dorm_beds]]
    if not room_ids and not bed_ids:
        return
    conds = []
    if room_ids:
        conds.append(Occupancy.room_id.in_(room_ids))
    if bed_ids:
        conds.append(Occupancy.bed_id.in_(bed_ids))
    res = await session.execute(
        select(Occupancy.room_id, Occupancy.bed_id).where(
            or_(*conds), Occupancy.checked_out_at.is_(None)
        )
    )
    open_rooms, open_beds = set(), set()
    for room_id, bed_id in res.all():
        if room_id:
            open_rooms.add(room_id)
        if bed_id:
            open_beds.add(bed_id)
    for r in rooms or []:
        r._open_occupancy = r.id in open_rooms
    for b in [*(beds or []), *dorm_beds]:
        b._open_occupancy = b.id in open_beds
    for d in dorms or []:
        d._open_occupancy = any(
            getattr(b, "_open_occupancy", False) for b in getattr(d, "beds", [])
        )


def resource_state_out(status: str, open_occupancy: bool | None) -> dict:
    """Canonical two-axis state contract — emitted identically on every
    resource payload (room / bed / dorm / washroom / fixture).

        status            the materialized projection (legacy column)
        is_occupied       occupancy axis — open occupancy record
        occupancy_state   occupied | unoccupied | null (no axis)
        operational_state available | cleaning | maintenance | inactive
                          (fixture: operational | maintenance | inactive)
        visual_state      the ONE visual classification the UI renders:
                          maintenance → red · cleaning → beige ·
                          inactive → neutral · occupied → violet ·
                          available → green

    The frontend must never recompute these — a resource's color follows
    ONLY from its current axes, never task history or call order."""
    has_occupancy = open_occupancy is not None
    occupied = bool(open_occupancy) or status == "occupied"
    if has_occupancy:
        # 'occupied'/'available' are projections of the occupancy axis —
        # the operational axis is whatever remains
        operational = (
            status if status in ("cleaning", "maintenance", "inactive")
            else "available"
        )
    else:
        operational = status
    if operational == "maintenance":
        visual = "maintenance"
    elif operational == "cleaning":
        visual = "cleaning"
    elif operational == "inactive":
        visual = "inactive"
    elif occupied:
        visual = "occupied"
    else:
        visual = "available"
    return {
        "is_occupied": occupied if has_occupancy else False,
        "occupancy_state": (
            ("occupied" if occupied else "unoccupied")
            if has_occupancy else None
        ),
        "operational_state": operational,
        "visual_state": visual,
    }


async def room_payload(session, room: Room) -> dict:
    """Room serialization with the canonical state contract — ALWAYS
    stamps open occupancy first so no endpoint can emit `status` without
    the occupancy axis."""
    await mark_open_occupancy(session, rooms=[room])
    return room_out(room)


async def dorm_payload(session, dorm: Dorm) -> dict:
    await mark_open_occupancy(session, dorms=[dorm])
    return dorm_out(dorm)


async def rooms_payload(session, rooms: list[Room]) -> list[dict]:
    await mark_open_occupancy(session, rooms=rooms)
    return [room_out(r) for r in rooms]


async def dorms_payload(session, dorms: list[Dorm]) -> list[dict]:
    await mark_open_occupancy(session, dorms=dorms)
    return [dorm_out(d) for d in dorms]


def room_out(r: Room) -> dict:
    return {
        "room_uid": str(r.id),
        "property_uid": str(r.property_id),
        "zone_uid": str(r.zone_id) if r.zone_id else None,
        "area_uid": str(r.area_id) if r.area_id else None,
        "room_number": r.room_number,
        "type": r.type,
        "area_sqft": r.area_sqft,
        "status": r.status,
        # Canonical two-axis contract — is_occupied / occupancy_state /
        # operational_state / visual_state, all resolved server-side.
        **resource_state_out(
            r.status, getattr(r, "_open_occupancy", None)
        ),
        "bed_count": r.bed_count,
        "cleaning_note": r.cleaning_note,
        "current_guest": r.current_guest,
        "created_at": r.created_at,
    }


def bed_out(b: Bed) -> dict:
    return {
        "bed_uid": str(b.id),
        "dorm_uid": str(b.dorm_id),
        "bed_number": b.bed_number,
        "status": b.status,
        **resource_state_out(
            b.status, getattr(b, "_open_occupancy", None)
        ),
        "guest_name": b.guest_name,
    }


def dorm_out(d: Dorm) -> dict:
    return {
        "dorm_uid": str(d.id),
        "property_uid": str(d.property_id),
        "zone_uid": str(d.zone_id) if d.zone_id else None,
        "area_uid": str(d.area_id) if d.area_id else None,
        "name": d.name,
        "dorm_type": d.dorm_type,
        "washroom": d.washroom,
        "status": d.status,
        # Dorm occupancy is an aggregate of its beds' open occupancies —
        # stamped by mark_open_occupancy.
        **resource_state_out(
            d.status, getattr(d, "_open_occupancy", None)
        ),
        "is_active": d.is_active,
        "floor": d.floor,
        "area_sqft": d.area_sqft,
        "description": d.description,
        "beds": [bed_out(b) for b in d.beds],
        "created_at": d.created_at,
    }


_FIXTURE_BUILTIN = {
    "shower", "stall", "urinal", "sink", "mirror", "bath_tub", "jacuzzi",
}


def washroom_fixture_out(f) -> dict:
    t = f.fixture_type.strip()
    singular = t.replace("_", " ").title() if t else "Fixture"
    return {
        "fixture_uid": str(f.id),
        "washroom_uid": str(f.washroom_id),
        "fixture_type": f.fixture_type,
        "fixture_number": f.fixture_number,
        "label": f"{singular} {f.fixture_number:02d}",
        "status": f.status,
        **resource_state_out(f.status, None),  # fixtures: no occupancy
        "last_cleaned_at": f.last_cleaned_at,
        "last_maintenance_at": f.last_maintenance_at,
    }


def washroom_out(w: Washroom) -> dict:
    fixtures = sorted(
        w.fixtures, key=lambda f: (f.fixture_type, f.fixture_number)
    )
    counts: dict[str, int] = {}
    for f in fixtures:
        counts[f.fixture_type] = counts.get(f.fixture_type, 0) + 1
    custom = {k: v for k, v in counts.items() if k not in _FIXTURE_BUILTIN}
    return {
        "washroom_uid": str(w.id),
        "property_uid": str(w.property_id),
        "zone_uid": str(w.zone_id) if w.zone_id else None,
        "area_uid": str(w.area_id) if w.area_id else None,
        "dorm_uid": str(w.dorm_id) if w.dorm_id else None,
        "name": w.name,
        "washroom_type": w.washroom_type,
        # Derived from real fixture rows — single source of truth
        "stall_count": counts.get("stall", 0),
        "urinal_count": counts.get("urinal", 0),
        "shower_count": counts.get("shower", 0),
        "sink_count": counts.get("sink", 0),
        "mirror_count": counts.get("mirror", 0),
        "bath_tub_count": counts.get("bath_tub", 0),
        "jacuzzi_count": counts.get("jacuzzi", 0),
        "custom_fixtures": custom,
        "fixtures": [washroom_fixture_out(f) for f in fixtures],
        "status": w.status,
        **resource_state_out(w.status, None),  # washrooms: no occupancy
        "created_at": w.created_at,
    }


def employee_out(e: Employee) -> dict:
    return {
        "employee_uid": str(e.id),
        "company_uid": str(e.company_id),
        "property_uid": str(e.property_id),
        "zone_uid": str(e.zone_id) if e.zone_id else None,
        "area_uid": str(e.area_id) if e.area_id else None,
        "name": e.name,
        "email": e.email,
        "phone": e.phone,
        "username": e.username,
        "job_title": e.job_title,
        "department": e.department,
        "status": e.status,
        "role": None,
        "salary": e.salary,
        "shift": e.shift,
        "joined_date": e.created_at.date().isoformat() if e.created_at else None,
        "start_date": e.start_date,
        "avatar_color": e.avatar_color,
        "leave_balance_days": e.leave_balance_days,
        "leave_status": e.leave_status,
        "deactivated_at": e.deactivated_at.isoformat() if e.deactivated_at else None,
        "reactivated_at": e.reactivated_at.isoformat() if e.reactivated_at else None,
        "created_at": e.created_at,
    }


def history_out(h: TaskHistoryEvent) -> dict:
    return {
        "event_uid": str(h.id),
        "type": h.type,
        "at": h.at,
        "actor_name": h.actor_name,
        "note": h.note,
        "photos": h.photos or [],
    }


def completion_image_out(i: TaskCompletionImage) -> dict:
    return {
        "image_uid": str(i.id),
        "task_uid": str(i.task_id),
        "event_uid": str(i.history_event_id) if i.history_event_id else None,
        "submission_uid": str(i.submission_id) if i.submission_id else None,
        "url": i.url,
        "file_name": i.file_name,
        "created_by_name": i.created_by_name,
        "created_at": i.created_at,
    }


def completion_submission_out(
    s: TaskCompletionSubmission, event: TaskHistoryEvent | None = None
) -> dict:
    images = [completion_image_out(i) for i in s.images]
    if not images and event and event.photos:
        images = [
            {
                "image_uid": None,
                "task_uid": str(s.task_id),
                "event_uid": str(event.id),
                "submission_uid": str(s.id),
                "url": url,
                "file_name": url.rsplit("/", 1)[-1],
                "created_by_name": s.employee_name,
                "created_at": s.submitted_at,
            }
            for url in event.photos
        ]
    return {
        "submission_uid": str(s.id),
        "task_uid": str(s.task_id),
        "event_uid": str(s.history_event_id) if s.history_event_id else None,
        "attempt_number": s.attempt_number,
        "employee_uid": str(s.employee_id) if s.employee_id else None,
        "employee_name": s.employee_name,
        "submitted_at": s.submitted_at.isoformat() if s.submitted_at else None,
        "status": s.status,
        "reviewed_at": s.reviewed_at.isoformat() if s.reviewed_at else None,
        "reviewer_uid": str(s.reviewed_by_id) if s.reviewed_by_id else None,
        "reviewed_by_name": s.reviewed_by_name,
        "review_comment": s.review_comment,
        "images": images,
    }


def task_out(t: Task) -> dict:
    unloaded = sa_inspect(t).unloaded
    events = {h.id: h for h in t.history} if "history" not in unloaded else {}
    submissions = (
        t.completion_submissions
        if "completion_submissions" not in unloaded else []
    )
    return {
        "task_uid": str(t.id),
        "ticket_number": t.ticket_number,
        "property_uid": str(t.property_id),
        "zone_uid": str(t.zone_id) if t.zone_id else None,
        "area_uid": (
            str(t.area_id) if t.area_id
            else str(t._resolved_area_id)
            if getattr(t, "_resolved_area_id", None) else None
        ),
        "room_uid": str(t.room_id) if t.room_id else None,
        "room_number": t.room_number,
        "dorm_uid": str(t.dorm_id) if t.dorm_id else None,
        "dorm_name": t.dorm_name,
        "bed_uids": list(t.bed_ids) if t.bed_ids else None,
        "washroom_uid": str(t.washroom_id) if t.washroom_id else None,
        "washroom_name": t.washroom_name,
        "washroom_fixture_uid": (
            str(t.washroom_fixture_id) if t.washroom_fixture_id else None
        ),
        "washroom_fixture_label": t.washroom_fixture_label,
        "supervisor_uid": str(t.supervisor_id) if t.supervisor_id else None,
        "supervisor_name": t.supervisor_name,
        "employee_uid": str(t.employee_id) if t.employee_id else None,
        "assigned_to_name": t.assigned_to_name,
        "allocation_batch_id": str(t.allocation_batch_id) if t.allocation_batch_id else None,
        "allocation_status": t.allocation_status,
        "allocation_method": t.allocation_method,
        "allocation_reason": t.allocation_reason,
        "title": t.title,
        "description": t.description,
        "task_type": t.task_type,
        "work_type": t.work_type,
        "origin": t.origin,
        "status": t.status,
        "priority": t.priority,
        "due_date": t.due_date,
        "due_time": t.due_time,
        "start_time": t.start_time,
        "recurrence_start_date": t.recurrence_start_date,
        "recurrence_end_date": t.recurrence_end_date,
        "recurrence_window_end": t.recurrence_window_end,
        "created_by_name": t.created_by_name,
        "recurrence": t.recurrence,
        "recurrence_interval_days": t.recurrence_interval_days,
        "series_id": str(t.series_id) if t.series_id else None,
        "scheduled_for": t.scheduled_for,
        "expires_at": t.expires_at,
        "template_id": str(t.template_id) if t.template_id else None,
        "abandoned_at": t.abandoned_at,
        "abandoned_reason": t.abandoned_reason,
        "abandoned_from_status": t.abandoned_from_status,
        "automation_rule": t.automation_rule,
        "history": [
            history_out(h) for h in (
                [] if "history" in unloaded else t.history
            )
        ],
        "completion_images": [
            completion_image_out(i) for i in (
                [] if "completion_images" in unloaded
                else t.completion_images
            )
        ],
        "completion_submissions": [
            completion_submission_out(s, events.get(s.history_event_id))
            for s in submissions
        ],
        "submitted_at": t.submitted_at.isoformat() if t.submitted_at else None,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        "created_at": t.created_at,
        # Detail-only: template checklist + evidence rules resolved by
        # TaskService.get_task; absent/null on list payloads.
        "checklist": getattr(t, "_checklist", None),
        "verification": getattr(t, "_verification", None),
    }
