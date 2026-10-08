"""Canonical resource states — ONE definition, imported everywhere.

Physical resource status is authoritative and entity-specific. Work status
(tasks, maintenance tickets) and review status (submissions) are separate
domains and must never be stored in these columns.
"""

# --- canonical operational states -------------------------------------------

ROOM_STATUSES = {"available", "occupied", "cleaning", "maintenance"}

DORM_STATUSES = {"available", "occupied", "cleaning", "maintenance"}

BED_STATUSES = {"available", "occupied", "cleaning", "maintenance", "inactive"}

WASHROOM_STATUSES = {"available", "cleaning", "maintenance", "inactive"}

FIXTURE_STATUSES = {"operational", "maintenance", "inactive"}

RESOURCE_TYPES = ("room", "dorm", "bed", "washroom", "fixture")

STATUS_SETS = {
    "room": ROOM_STATUSES,
    "dorm": DORM_STATUSES,
    "bed": BED_STATUSES,
    "washroom": WASHROOM_STATUSES,
    "fixture": FIXTURE_STATUSES,
}

# --- blocking work (the ONE definition used by derive() and the frontend) ----

# A ticket still holds the resource until a supervisor closes it — the
# employee "resolved" state is completion, not acknowledgement.
BLOCKING_MAINTENANCE = {"open", "assigned", "in_progress", "on_hold", "resolved"}

# completed/cancelled are the only non-blocking task states.
BLOCKING_TASK = {
    "pending", "assigned", "in_progress", "submitted",
    "reopened", "scheduled", "overdue",
}

# Terminal work states — the inverse of BLOCKING_TASK. `abandoned` is set
# only by the daily rollover when an unfinished task's operational day ends.
TERMINAL_TASK = {"completed", "cancelled", "abandoned"}
TERMINAL_TICKET = {"closed", "cancelled"}

# States derive() is allowed to release from. "occupied" and "available" are
# occupancy/eligibility truth — work completion must never override them.
# "inactive" is an administrative lifecycle state, not work-driven.
RELEASE_ELIGIBLE = {"cleaning", "maintenance"}
