"""Write DTOs for the property-structure module — frontend `*_uid` names."""

import uuid

from pydantic import BaseModel, Field


def _uid(v):
    if v is None or isinstance(v, uuid.UUID):
        return v
    return uuid.UUID(str(v))


# ---------------------------------------------------------------------------
# Areas
# ---------------------------------------------------------------------------

class AreaCreateRequest(BaseModel):
    property_uid: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    level_number: int = 0
    description: str | None = None


class AreaUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    level_number: int | None = None
    description: str | None = None
    status: str | None = None


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------

class ZoneCreateRequest(BaseModel):
    property_uid: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    floor: str | None = None
    area_uid: uuid.UUID | None = None
    zone_type: str | None = None
    description: str | None = None


class ZoneUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    floor: str | None = None
    area_uid: uuid.UUID | None = None
    zone_type: str | None = None
    description: str | None = None
    status: str | None = None


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------

class RoomCreateRequest(BaseModel):
    property_uid: uuid.UUID
    room_number: str = Field(min_length=1, max_length=32)
    type: str = Field(min_length=1, max_length=64)
    area_sqft: int | None = None
    zone_uid: uuid.UUID | None = None
    area_uid: uuid.UUID | None = None
    bed_count: int | None = Field(default=None, ge=0, le=20)


class RoomBulkCreateRequest(BaseModel):
    property_uid: uuid.UUID
    start: int
    end: int
    type: str = Field(min_length=1, max_length=64)
    # Optional name prefix — "Special" + range 101-103 creates
    # "Special 101", "Special 102", "Special 103"
    prefix: str | None = Field(default=None, max_length=20)
    area_sqft: int | None = None
    zone_uid: uuid.UUID | None = None
    area_uid: uuid.UUID | None = None


class RoomUpdateRequest(BaseModel):
    room_number: str | None = Field(default=None, min_length=1, max_length=32)
    type: str | None = Field(default=None, max_length=64)
    area_sqft: int | None = None
    zone_uid: uuid.UUID | None = None
    area_uid: uuid.UUID | None = None
    cleaning_note: str | None = None
    # status / current_guest are NOT updatable here — resource state moves
    # through the command endpoints (check-in/out, transition) only.


class RoomBulkDeleteRequest(BaseModel):
    property_uid: uuid.UUID
    room_uids: list[uuid.UUID] = Field(min_length=1)


# ---------------------------------------------------------------------------
# Dorms / Beds
# ---------------------------------------------------------------------------

class DormCreateRequest(BaseModel):
    property_uid: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    dorm_type: str = Field(min_length=1, max_length=32)
    washroom: str = Field(min_length=1, max_length=32)
    bed_count: int = Field(ge=1, le=200)
    zone_uid: uuid.UUID | None = None
    area_uid: uuid.UUID | None = None
    floor: str | None = None
    area_sqft: int | None = None
    description: str | None = None


class DormBulkItem(BaseModel):
    """One row of the bulk-dorm form — same fields as DormCreateRequest."""
    name: str = Field(min_length=1, max_length=255)
    dorm_type: str = Field(min_length=1, max_length=32)
    washroom: str = Field(min_length=1, max_length=32)
    bed_count: int = Field(ge=1, le=200)
    zone_uid: uuid.UUID | None = None
    area_uid: uuid.UUID | None = None
    floor: str | None = None
    area_sqft: int | None = None
    description: str | None = None


class DormBulkCreateRequest(BaseModel):
    property_uid: uuid.UUID
    dorms: list[DormBulkItem] = Field(min_length=1, max_length=50)


class DormUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    dorm_type: str | None = None
    washroom: str | None = None
    floor: str | None = None
    area_sqft: int | None = None
    description: str | None = None
    zone_uid: uuid.UUID | None = None
    area_uid: uuid.UUID | None = None
    is_active: bool | None = None  # lifecycle flag — NOT operational status
    bed_count: int | None = Field(default=None, ge=0, le=200)


class CheckInRequest(BaseModel):
    # Optional — omitted/empty creates an unnamed occupancy (pure toggle).
    guest_name: str | None = Field(default=None, max_length=255)


class ResourceTransitionRequest(BaseModel):
    """POST /resources/{type}/{id}/transition — Super Admin administrative
    transition. Still validated against the legal transition table."""
    to: str = Field(min_length=1, max_length=32)
    reason: str = Field(min_length=1, max_length=2000)


# ---------------------------------------------------------------------------
# Washrooms
# ---------------------------------------------------------------------------

class WashroomFixtureCounts(BaseModel):
    stall_count: int = Field(default=0, ge=0, le=200)
    urinal_count: int = Field(default=0, ge=0, le=200)
    shower_count: int = Field(default=0, ge=0, le=200)
    sink_count: int = Field(default=0, ge=0, le=200)
    mirror_count: int = Field(default=0, ge=0, le=200)
    bath_tub_count: int = Field(default=0, ge=0, le=200)
    jacuzzi_count: int = Field(default=0, ge=0, le=200)


class WashroomCreateRequest(WashroomFixtureCounts):
    property_uid: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    washroom_type: str = Field(min_length=1, max_length=32)
    zone_uid: uuid.UUID | None = None
    area_uid: uuid.UUID | None = None
    # Set → attached washroom owned by ONE dorm (its own independent
    # configuration); NULL → zone-level/common facility
    dorm_uid: uuid.UUID | None = None
    # Extra named fixture types, e.g. {"Hand Dryer": 2}
    custom_fixtures: dict[str, int] | None = None


class WashroomBulkItem(WashroomFixtureCounts):
    name: str = Field(min_length=1, max_length=255)
    washroom_type: str = Field(min_length=1, max_length=32)
    zone_uid: uuid.UUID | None = None
    area_uid: uuid.UUID | None = None
    dorm_uid: uuid.UUID | None = None
    custom_fixtures: dict[str, int] | None = None


class WashroomBulkCreateRequest(BaseModel):
    property_uid: uuid.UUID
    washrooms: list[WashroomBulkItem] = Field(min_length=1, max_length=50)


class WashroomUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    washroom_type: str | None = Field(default=None, max_length=32)
    # Count fields are resize directives — the service translates them into
    # real washroom_fixtures rows (grow appends, shrink removes from the tail).
    stall_count: int | None = Field(default=None, ge=0, le=200)
    urinal_count: int | None = Field(default=None, ge=0, le=200)
    shower_count: int | None = Field(default=None, ge=0, le=200)
    sink_count: int | None = Field(default=None, ge=0, le=200)
    mirror_count: int | None = Field(default=None, ge=0, le=200)
    bath_tub_count: int | None = Field(default=None, ge=0, le=200)
    jacuzzi_count: int | None = Field(default=None, ge=0, le=200)
    custom_fixtures: dict[str, int] | None = None
    zone_uid: uuid.UUID | None = None
    area_uid: uuid.UUID | None = None
    dorm_uid: uuid.UUID | None = None


class WashroomFixtureUpdateRequest(BaseModel):
    # canonical fixture states: operational | maintenance | inactive
    status: str = Field(min_length=1, max_length=32)


# ---------------------------------------------------------------------------
# Bulk unit status + allocation
# ---------------------------------------------------------------------------

class BulkUnitStatusRequest(BaseModel):
    action: str  # checkout | cleaning | available | cleaned | maintenance
    property_uid: uuid.UUID
    room_uids: list[uuid.UUID] = []
    bed_uids: list[uuid.UUID] = []
    washroom_uids: list[uuid.UUID] = []
    # required for the state-forcing actions (available/cleaned/maintenance)
    reason: str | None = Field(default=None, max_length=2000)


class AllocationRequest(BaseModel):
    """PATCH /rooms/{id}/allocation and /dorms/{id}/allocation."""
    area_uid: uuid.UUID | None = None
    zone_uid: uuid.UUID | None = None


# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------

class EmployeeCreateRequest(BaseModel):
    property_uid: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    email: str
    password: str = Field(min_length=8, max_length=128)
    job_title: str = Field(min_length=1, max_length=255)
    department: str | None = None
    phone: str | None = None
    username: str | None = None
    zone_uid: uuid.UUID | None = None
    salary: str | None = None
    shift: str | None = None
    start_date: str | None = None


class EmployeeUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    job_title: str | None = None
    department: str | None = None
    phone: str | None = None
    email: str | None = None
    zone_uid: uuid.UUID | None = None
    salary: str | None = None
    shift: str | None = None
    status: str | None = None


class EmployeeZoneAssignRequest(BaseModel):
    zone_uid: uuid.UUID | None = None
    # Area-level assignment — mutually exclusive with zone_uid; an
    # area assignee is eligible for work in every zone inside the area
    area_uid: uuid.UUID | None = None


class EmployeeAllocationRequest(BaseModel):
    """PATCH /employees/{id}/allocation — dedicated allocation endpoint."""
    zone_uid: uuid.UUID | None = None
    area_uid: uuid.UUID | None = None


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

class AutomationRuleIn(BaseModel):
    trigger: str  # room_checked_out | bed_marked_cleaning | bed_available_after_checkout
    scope_zone_uid: uuid.UUID | None = None
    template_title: str = Field(min_length=1, max_length=255)
    template_description: str | None = None
    assign_to_uid: uuid.UUID | None = None


class TaskCreateRequest(BaseModel):
    property_uid: uuid.UUID
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    task_type: str = "fixed"  # fixed | repetitive | automated
    # cleaning | maintenance | inspection | housekeeping | other — decides
    # which departments are eligible; inferred from the title when omitted
    work_type: str | None = None
    employee_uid: uuid.UUID | None = None
    supervisor_uid: uuid.UUID | None = None
    room_uid: uuid.UUID | None = None
    washroom_uid: uuid.UUID | None = None
    # Fixture-level task targeting — must belong to washroom_uid
    washroom_fixture_uid: uuid.UUID | None = None
    zone_uid: uuid.UUID | None = None
    priority: str | None = "medium"
    due_date: str | None = None
    due_time: str | None = None
    start_time: str | None = None  # HH:MM — when the recurrence schedule begins
    recurrence_start_date: str | None = None   # first day the schedule runs
    recurrence_end_date: str | None = None     # None = runs forever
    recurrence_window_end: str | None = None   # HH:MM — daily window end
    recurrence: str | None = None
    recurrence_interval_days: int | None = None
    automation_rule: AutomationRuleIn | None = None


class TaskUpdateRequest(BaseModel):  # noqa: D401 - partial update payload
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    task_type: str | None = None
    work_type: str | None = None
    employee_uid: uuid.UUID | None = None
    supervisor_uid: uuid.UUID | None = None
    room_uid: uuid.UUID | None = None
    washroom_uid: uuid.UUID | None = None
    washroom_fixture_uid: uuid.UUID | None = None
    zone_uid: uuid.UUID | None = None
    priority: str | None = None
    status: str | None = None
    due_date: str | None = None
    due_time: str | None = None
    start_time: str | None = None
    recurrence_start_date: str | None = None
    recurrence_end_date: str | None = None
    recurrence_window_end: str | None = None
    recurrence: str | None = None
    recurrence_interval_days: int | None = None
    automation_rule: AutomationRuleIn | None = None


class TaskActionRequest(BaseModel):
    note: str | None = None


class TaskCompleteRequest(BaseModel):
    photo_urls: list[str] = []
    note: str | None = None


class TaskReassignRequest(BaseModel):
    employee_uid: uuid.UUID | None = None


class TaskRejectRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


class TaskSubmitRequest(BaseModel):
    note: str | None = Field(default=None, max_length=4000)
    photo_urls: list[str] = []
    # Optional geo capture — validated server-side (parse_geo); the
    # recorded timestamp is always the server's, never the client's.
    latitude: float | None = None
    longitude: float | None = None
    accuracy_meters: float | None = None


# ---------------------------------------------------------------------------
# Company
# ---------------------------------------------------------------------------

class CompanyUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    legal_name: str | None = None
    brand_name: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    pin_code: str | None = None
    operational_day_start: str | None = Field(
        default=None, pattern=r"^\d{2}:\d{2}$"
    )
