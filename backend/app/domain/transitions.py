"""Legal resource-state transitions + source gates.

LEGAL_TRANSITIONS defines the base graph per resource type. SOURCE_GATES
additionally restrict WHICH workflow source may commit specific edges —
e.g. only an occupancy check-in may produce ``occupied``, and only a
checkout or admin override may release ``occupied``.

ADMIN_OVERRIDE (staff — super admin / property manager — mandatory
reason) still uses this table — it is not "ignore all validation", it is
an authorized explicit transition.
"""

# Base graph — what may become what.
LEGAL_TRANSITIONS: dict[str, dict[str, set[str]]] = {
    "room": {
        "available": {"occupied", "cleaning", "maintenance"},
        "occupied": {"available", "cleaning", "maintenance"},
        "cleaning": {"available", "maintenance"},
        "maintenance": {"available"},
    },
    "dorm": {
        "available": {"occupied", "cleaning", "maintenance"},
        "occupied": {"available", "cleaning", "maintenance"},
        "cleaning": {"available", "maintenance"},
        "maintenance": {"available"},
    },
    "bed": {
        "available": {"occupied", "cleaning", "maintenance", "inactive"},
        "occupied": {"available", "cleaning", "maintenance"},
        "cleaning": {"available", "maintenance"},
        "maintenance": {"available"},
        "inactive": {"available"},
    },
    "washroom": {
        "available": {"cleaning", "maintenance", "inactive"},
        "cleaning": {"available", "maintenance"},
        "maintenance": {"available"},
        "inactive": {"available"},
    },
    "fixture": {
        "operational": {"maintenance", "inactive"},
        "maintenance": {"operational", "inactive"},
        "inactive": {"operational"},
    },
}

# (from_state, to_state) -> allowed sources. from_state=None means "any
# source state". Edges not listed here are open to every defined source.
SOURCE_GATES: dict[tuple[str | None, str], set[str]] = {
    # Occupancy is a business state — only a real check-in may produce it.
    (None, "occupied"): {"occupancy_checkin"},
    # Releasing an occupied resource is a checkout (or admin override).
    ("occupied", "available"): {"occupancy_checkout", "admin_override"},
    # Checkout cleaning is the normal occupied→cleaning path; a cleaning
    # task that starts while a resource is still occupied may also flag it.
    ("occupied", "cleaning"): {
        "occupancy_checkout", "admin_override", "task_start", "task_queued",
    },
    # Maintenance on an occupied unit requires a real ticket or an override.
    ("occupied", "maintenance"): {"ticket_created", "admin_override"},
    # Cleaning units escalate to maintenance via a ticket, not arbitrarily.
    ("cleaning", "maintenance"): {"ticket_created", "admin_override"},
}


def is_legal(resource_type: str, from_state: str, to_state: str,
             source: str) -> bool:
    """Base-graph + source-gate check. Returns True when the transition is
    legal for this workflow source."""
    allowed = LEGAL_TRANSITIONS.get(resource_type, {}).get(from_state)
    if allowed is None or to_state not in allowed:
        return False
    for key in ((from_state, to_state), (None, to_state)):
        gate = SOURCE_GATES.get(key)
        if gate is not None:
            return source in gate
    return True
