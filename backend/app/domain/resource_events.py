"""Transition sources — why a resource changed state.

Every resource_state_events row carries one of these so the answer to
"why is this resource in this state?" is always identifiable (spec §42).
"""

SRC_TASK_START = "task_start"
SRC_TASK_QUEUED = "task_queued"
SRC_TASK_APPROVED = "task_approved"
SRC_TASK_REJECTED = "task_rejected"
SRC_TICKET_CREATED = "ticket_created"
SRC_TICKET_RESOLVED = "ticket_resolved"
SRC_TICKET_CLOSED = "ticket_closed"
SRC_OCCUPANCY_CHECKIN = "occupancy_checkin"
SRC_OCCUPANCY_CHECKOUT = "occupancy_checkout"
SRC_ADMIN_OVERRIDE = "admin_override"
SRC_RECONCILIATION = "reconciliation"
SRC_DERIVE = "derive"           # blocker recompute (task/ticket lifecycle)
SRC_FIXTURE_RESTORED = "fixture_restored"

SOURCES = {
    SRC_TASK_START, SRC_TASK_QUEUED, SRC_TASK_APPROVED, SRC_TASK_REJECTED,
    SRC_TICKET_CREATED,
    SRC_TICKET_RESOLVED, SRC_TICKET_CLOSED, SRC_OCCUPANCY_CHECKIN,
    SRC_OCCUPANCY_CHECKOUT, SRC_ADMIN_OVERRIDE, SRC_RECONCILIATION,
    SRC_DERIVE, SRC_FIXTURE_RESTORED,
}
