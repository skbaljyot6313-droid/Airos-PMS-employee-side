"""Maintenance ticket request/response schemas — flat *_uid conventions."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


MAINTENANCE_TYPES = {
    "electrical", "plumbing", "civil", "carpentry", "hvac", "painting",
    "furniture", "appliance", "internet", "water_drainage",
    "cleaning_equipment", "safety_security", "other",
}
PRIORITIES = {"low", "medium", "high", "critical"}
TICKET_STATUSES = {
    "open", "assigned", "in_progress", "on_hold", "resolved", "closed", "cancelled"
}


class MaintenanceCreateRequest(BaseModel):
    property_uid: uuid.UUID
    room_uid: uuid.UUID | None = None
    dorm_uid: uuid.UUID | None = None
    bed_uid: uuid.UUID | None = None
    washroom_uid: uuid.UUID | None = None
    # Fixture-level targeting — must belong to washroom_uid
    washroom_fixture_uid: uuid.UUID | None = None
    maintenance_type: str = Field(..., max_length=64)
    issue: str = Field(..., min_length=3, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    priority: str = "medium"
    due_date: str | None = Field(default=None, max_length=64)
    attachment_urls: list[str] = Field(default_factory=list)


class MaintenanceUpdateRequest(BaseModel):
    maintenance_type: str | None = None
    issue: str | None = Field(default=None, min_length=3, max_length=255)
    description: str | None = None
    priority: str | None = None
    due_date: str | None = None
    assigned_to: uuid.UUID | None = None
    status: str | None = None  # limited transitions — see service


class MaintenanceAssignRequest(BaseModel):
    employee_uid: uuid.UUID | None = None  # null → unassign


class MaintenanceActionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class MaintenanceResolveRequest(BaseModel):
    resolution_notes: str = Field(..., min_length=3, max_length=4000)
    photo_urls: list[str] = Field(default_factory=list)


class MaintenanceDisapproveRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=2000)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def attachment_out(a) -> dict:
    return {
        "attachment_uid": str(a.id),
        "url": a.url,
        "file_name": a.file_name,
        "mime_type": a.mime_type,
        "size_bytes": a.size_bytes,
        "kind": a.kind,
        "attempt": a.attempt,
        "uploaded_by_name": a.uploaded_by_name,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def event_out(e) -> dict:
    return {
        "event_uid": str(e.id),
        "action": e.action,
        "actor_name": e.actor_name,
        "comment": e.comment,
        "at": e.created_at.isoformat() if e.created_at else None,
    }


def ticket_out(t) -> dict:
    return {
        "ticket_uid": str(t.id),
        "ticket_number": t.ticket_number,
        "company_uid": str(t.company_id),
        "property_uid": str(t.property_id),
        "room_uid": str(t.room_id) if t.room_id else None,
        "room_number": t.room_number,
        "dorm_uid": str(t.dorm_id) if t.dorm_id else None,
        "dorm_name": t.dorm_name,
        "bed_uid": str(t.bed_id) if t.bed_id else None,
        "bed_number": t.bed_number,
        "washroom_uid": str(t.washroom_id) if t.washroom_id else None,
        "washroom_name": t.washroom_name,
        "washroom_fixture_uid": (
            str(t.washroom_fixture_id) if t.washroom_fixture_id else None
        ),
        "washroom_fixture_label": t.washroom_fixture_label,
        "location_label": (
            t.room_number
            or (f"{t.dorm_name} · {t.bed_number}" if t.bed_number else t.dorm_name)
            or t.washroom_name
        ),
        "reported_by_name": t.reported_by_name,
        "maintenance_type": t.maintenance_type,
        "issue": t.issue,
        "description": t.description,
        "priority": t.priority,
        "status": t.status,
        "assigned_to": str(t.assigned_to) if t.assigned_to else None,
        "assigned_to_name": t.assigned_to_name,
        "zone_uid": str(t.zone_id) if t.zone_id else None,
        "allocation_batch_id": str(t.allocation_batch_id) if t.allocation_batch_id else None,
        "allocation_status": t.allocation_status,
        "allocation_method": t.allocation_method,
        "allocation_reason": t.allocation_reason,
        "due_date": t.due_date,
        "resolved_at": t.resolved_at.isoformat() if t.resolved_at else None,
        "closed_at": t.closed_at.isoformat() if t.closed_at else None,
        "resolution_notes": t.resolution_notes,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        "events": [event_out(e) for e in getattr(t, "events", [])],
        "attachments": [attachment_out(a) for a in getattr(t, "attachments", [])],
    }
