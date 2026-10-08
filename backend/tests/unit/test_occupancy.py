"""Occupancy — check-in/check-out, the one-open-occupancy invariant, and
the critical checkout → CLEANING rule (no 'available' gap).
"""
import pytest
from sqlalchemy import select

from app.models.occupancy import Occupancy
from app.services.occupancy import OccupancyService
from app.services.structure import ConflictErr


async def open_occ(session, *, room_id=None, bed_id=None):
    cond = (
        Occupancy.room_id == room_id if room_id else Occupancy.bed_id == bed_id
    )
    res = await session.execute(
        select(Occupancy).where(cond, Occupancy.checked_out_at.is_(None))
    )
    return res.scalars().all()


async def test_room_checkin_creates_occupancy(session, seed, stub_tasks):
    svc = OccupancyService(session)
    room = await svc.check_in_room(seed["admin"], seed["room"].id, "Ada")
    await session.commit()
    assert room.status == "occupied"
    assert room.current_guest == "Ada"
    occs = await open_occ(session, room_id=room.id)
    assert len(occs) == 1 and occs[0].guest_name == "Ada"


async def test_duplicate_checkin_rejected(session, seed, stub_tasks):
    svc = OccupancyService(session)
    await svc.check_in_room(seed["admin"], seed["room"].id, "Ada")
    await session.commit()
    with pytest.raises(ConflictErr):
        await svc.check_in_room(seed["admin"], seed["room"].id, "Bob")


async def test_checkin_non_available_rejected(session, seed, stub_tasks):
    room = seed["room"]
    room.status = "maintenance"
    await session.commit()
    with pytest.raises(ConflictErr):
        await OccupancyService(session).check_in_room(
            seed["admin"], room.id, "Ada"
        )


async def test_checkout_never_passes_through_available(
    session, seed, stub_tasks
):
    """Spec §3: OCCUPIED → CLEANING atomically — occupancy closed and
    cleaning task generated in the same commit."""
    svc = OccupancyService(session)
    room = await svc.check_in_room(seed["admin"], seed["room"].id, "Ada")
    await session.commit()

    res = await svc.check_out_room(seed["admin"], room.id)
    room = res["room"]
    await session.commit()

    # resource went occupied → cleaning with no 'available' window
    assert room.status == "cleaning"
    # occupancy row closed, not deleted — authoritative history
    res = await session.execute(
        select(Occupancy).where(Occupancy.room_id == room.id)
    )
    occs = list(res.scalars())
    assert len(occs) == 1 and occs[0].checked_out_at is not None
    # cleaning work was queued in the same transaction
    assert stub_tasks and stub_tasks[0]["action"] == "checkout"
    assert stub_tasks[0]["rooms"] == [room.room_number]


async def test_checkout_without_occupant_rejected(session, seed, stub_tasks):
    with pytest.raises(ConflictErr):
        await OccupancyService(session).check_out_room(
            seed["admin"], seed["room"].id
        )


async def test_legacy_occupied_room_still_checks_out(
    session, seed, stub_tasks
):
    """A room flagged occupied without an occupancy row (pre-migration
    data) still gets the safe OCCUPIED → CLEANING path."""
    room = seed["room"]
    room.status = "occupied"
    room.current_guest = "Legacy Guest"
    await session.commit()
    res = await OccupancyService(session).check_out_room(
        seed["admin"], room.id
    )
    room = res["room"]
    await session.commit()
    assert room.status == "cleaning" and room.current_guest is None


async def test_bed_checkin_checkout(session, seed, stub_tasks):
    svc = OccupancyService(session)
    dorm = await svc.check_in_bed(seed["admin"], seed["bed"].id, "Ravi")
    await session.commit()
    bed = next(b for b in dorm.beds if b.id == seed["bed"].id)
    assert bed.status == "occupied" and bed.guest_name == "Ravi"
    assert dorm.status == "occupied"  # aggregate derived
    assert len(await open_occ(session, bed_id=bed.id)) == 1

    res = await svc.check_out_bed(seed["admin"], bed.id)
    dorm = res["dorm"]
    await session.commit()
    bed = next(b for b in dorm.beds if b.id == seed["bed"].id)
    assert bed.status == "cleaning" and bed.guest_name is None
    assert dorm.status == "cleaning"


async def test_bed_duplicate_checkin_rejected(session, seed, stub_tasks):
    svc = OccupancyService(session)
    await svc.check_in_bed(seed["admin"], seed["bed"].id, "Ravi")
    await session.commit()
    with pytest.raises(ConflictErr):
        await svc.check_in_bed(seed["admin"], seed["bed"].id, "Other")


async def test_one_open_occupancy_per_room_db_protected(
    session, seed, stub_tasks
):
    """The partial unique index is the DB backstop — even a bypassed
    service-level check cannot produce two open rows."""
    occ = Occupancy(
        property_id=seed["prop"].id, room_id=seed["room"].id,
        guest_name="A",
    )
    session.add(occ)
    await session.flush()
    dup = Occupancy(
        property_id=seed["prop"].id, room_id=seed["room"].id,
        guest_name="B",
    )
    session.add(dup)
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        await session.flush()
