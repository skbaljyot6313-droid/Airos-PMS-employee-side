"""ResourceStateService — transition legality, canonical sets, audit,
authorization, and OCCUPIED-without-occupancy rejection.
"""
import pytest

from app.domain.resource_events import SRC_ADMIN_OVERRIDE
from app.domain.resource_states import (
    BED_STATUSES,
    DORM_STATUSES,
    FIXTURE_STATUSES,
    ROOM_STATUSES,
    WASHROOM_STATUSES,
)
from app.models.resource_state_event import ResourceStateEvent
from app.services.occupancy import OccupancyService
from app.services.resource_state import ResourceStateService
from app.services.structure import ConflictErr, ValidationErr
from app.dependencies.auth import Forbidden


def svc(session):
    return ResourceStateService(session)


async def events(session, resource_type, rid):
    from sqlalchemy import select
    res = await session.execute(
        select(ResourceStateEvent).where(
            ResourceStateEvent.resource_type == resource_type,
            ResourceStateEvent.resource_id == rid,
        )
    )
    return list(res.scalars())


async def test_canonical_sets(session, seed):
    assert ROOM_STATUSES == {"available", "occupied", "cleaning", "maintenance"}
    assert DORM_STATUSES == ROOM_STATUSES
    assert BED_STATUSES == ROOM_STATUSES | {"inactive"}
    assert WASHROOM_STATUSES == {"available", "cleaning", "maintenance", "inactive"}
    assert FIXTURE_STATUSES == {"operational", "maintenance", "inactive"}
    for banned in ("needs_cleaning", "out_of_service", "clean", "dirty", "active"):
        for states in (ROOM_STATUSES, DORM_STATUSES, BED_STATUSES,
                       WASHROOM_STATUSES, FIXTURE_STATUSES):
            assert banned not in states


async def test_room_legal_transition_and_audit(session, seed):
    admin, room = seed["admin"], seed["room"]
    row, prev, new = await svc(session).transition(
        "room", room.id, "maintenance", user=admin,
        source=SRC_ADMIN_OVERRIDE, reason="leak",
    )
    assert (prev, new, row.status) == ("available", "maintenance", "maintenance")
    ev = await events(session, "room", room.id)
    assert len(ev) == 1
    assert ev[0].source == "admin_override" and ev[0].reason == "leak"
    assert ev[0].previous_state == "available" and ev[0].new_state == "maintenance"


async def test_illegal_transition_rejected(session, seed):
    admin, washroom = seed["admin"], seed["washroom"]
    # washroom cannot be 'occupied' — not in the canonical set
    with pytest.raises(ValidationErr):
        await svc(session).transition(
            "washroom", washroom.id, "occupied", user=admin,
            source=SRC_ADMIN_OVERRIDE, reason="x",
        )
    # room: maintenance → occupied is not a legal edge
    room = seed["room"]
    room.status = "maintenance"
    await session.flush()
    with pytest.raises(ConflictErr):
        await svc(session).transition(
            "room", room.id, "occupied", user=admin,
            source=SRC_ADMIN_OVERRIDE, reason="x",
        )
    # fixture: operational → occupied nonsense
    with pytest.raises(ValidationErr):
        await svc(session).transition(
            "fixture", seed["fixture"].id, "occupied", user=admin,
            source=SRC_ADMIN_OVERRIDE, reason="x",
        )


async def test_admin_override_requires_staff(session, seed):
    """admin_override is staff authority — super_admin and the property's
    own manager; employees and HR are denied."""
    room = seed["room"]
    for role_key in ("emp_user", "hr"):
        with pytest.raises(Forbidden):
            await svc(session).transition(
                "room", room.id, "maintenance", user=seed[role_key],
                source=SRC_ADMIN_OVERRIDE, reason="denied",
            )
    # the property's own manager may drive the same audited transition
    row, prev, new = await svc(session).transition(
        "room", room.id, "maintenance", user=seed["pm"],
        source=SRC_ADMIN_OVERRIDE, reason="leak",
    )
    assert (prev, new, row.status) == ("available", "maintenance",
                                      "maintenance")


async def test_admin_override_requires_reason(session, seed):
    admin = seed["admin"]
    with pytest.raises(ValidationErr):
        await svc(session).transition(
            "room", seed["room"].id, "maintenance", user=admin,
            source=SRC_ADMIN_OVERRIDE, reason="",
        )


async def test_occupied_requires_open_occupancy(session, seed):
    admin, room = seed["admin"], seed["room"]
    with pytest.raises(ConflictErr) as exc:
        await svc(session).transition(
            "room", room.id, "occupied", user=admin,
            source="occupancy_checkin",
        )
    assert "occupancy" in str(exc.value).lower()


async def test_occupied_with_occupancy_succeeds(session, seed):
    occ_svc = OccupancyService(session)
    admin, room = seed["admin"], seed["room"]
    await occ_svc.check_in_room(admin, room.id, "Guest A")
    await session.commit()
    assert room.status == "occupied"
    ev = await events(session, "room", room.id)
    assert ev[0].source == "occupancy_checkin"
    assert ev[0].occupancy_id is not None


async def test_sequential_transition_validates_current_state(session, seed):
    """Concurrency guard: a second transition sees the committed state —
    available → maintenance then maintenance → occupied is rejected."""
    admin, room = seed["admin"], seed["room"]
    s = svc(session)
    await s.transition("room", room.id, "maintenance", user=admin,
                       source=SRC_ADMIN_OVERRIDE, reason="r")
    await session.commit()
    with pytest.raises(ConflictErr):
        await svc(session).transition(
            "room", room.id, "occupied", user=admin,
            source=SRC_ADMIN_OVERRIDE, reason="x",
        )


async def test_derive_releases_when_unblocked(session, seed):
    admin, room = seed["admin"], seed["room"]
    room.status = "cleaning"
    await session.flush()
    new = await svc(session).derive("room", room.id, release_to="available",
                                    user=admin)
    assert new == "available"
    await session.commit()
    ev = await events(session, "room", room.id)
    assert ev[0].previous_state == "cleaning" and ev[0].new_state == "available"


async def test_derive_never_releases_occupied(session, seed):
    admin, room = seed["admin"], seed["room"]
    room.status = "occupied"
    await session.flush()
    new = await svc(session).derive("room", room.id, release_to="available",
                                    user=admin)
    assert new is None  # occupied is never released by derive
    assert room.status == "occupied"


async def test_explain_lists_blockers(session, seed):
    room = seed["room"]
    room.status = "cleaning"
    await session.flush()
    ex = await svc(session).explain("room", room.id)
    assert ex["status"] == "cleaning" and ex["blocking_tasks"] == []
