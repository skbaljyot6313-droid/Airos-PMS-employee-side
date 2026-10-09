"""Eligible locations — the raise-ticket picker's coverage inventory.

GET /maintenance/eligible-locations must expose EVERY individual
raiseable unit inside the employee's coverage: rooms, dorms, individual
beds, washrooms (zone-level AND dorm-attached), and individual fixtures.
"""

import pytest
from sqlalchemy import select

from app.dependencies.auth import Forbidden
from app.models.structure import Bed, Dorm, Room, Washroom, WashroomFixture, Zone
from app.services.maintenance import MaintenanceService


def _zone(prop, name) -> Zone:
    return Zone(property_id=prop.id, name=name, code=name,
                zone_type="stay")


async def _coverage_seed(session, seed):
    """Employee gets zone Z1 holding one of each resource kind; Z9 holds
    out-of-scope twins that must never appear."""
    z1, z9 = _zone(seed["prop"], "Z1"), _zone(seed["prop"], "Z9")
    session.add_all([z1, z9])
    await session.flush()
    seed["employee"].zone_id = z1.id
    seed["room"].zone_id = z1.id
    seed["dorm"].zone_id = z1.id
    seed["washroom"].zone_id = z1.id
    dorm2 = Dorm(property_id=seed["prop"].id, name="Dorm B",
                 dorm_type="male", zone_id=z9.id)
    session.add(dorm2)
    await session.flush()
    session.add_all([
        Room(property_id=seed["prop"].id, room_number="999",
             type="Deluxe", zone_id=z9.id),
        Bed(dorm_id=dorm2.id, property_id=seed["prop"].id,
            bed_number="Bed 99"),
        Washroom(property_id=seed["prop"].id, name="W-99",
                 washroom_type="unisex", zone_id=z9.id),
    ])
    await session.commit()
    return z1


async def test_returns_individual_beds_and_fixtures(session, seed):
    await _coverage_seed(session, seed)
    out = await MaintenanceService(session).eligible_locations(
        seed["emp_user"])

    assert [r["room_number"] for r in out["rooms"]] == ["101"]
    assert [d["name"] for d in out["dorms"]] == ["Dorm A"]

    (b,) = out["beds"]
    assert b["bed_uid"] == str(seed["bed"].id)
    assert b["bed_number"] == "Bed 01" and b["dorm_name"] == "Dorm A"
    assert b["zone_name"] == "Z1"

    (w,) = out["washrooms"]
    assert w["washroom_uid"] == str(seed["washroom"].id)
    assert w["dorm_uid"] is None and w["fixture_count"] == 1

    (f,) = out["fixtures"]
    assert f["fixture_uid"] == str(seed["fixture"].id)
    assert f["fixture_type"] == "sink" and f["washroom_name"] == "W-01"

    # Out-of-scope zone contributes nothing.
    flat = str(out)
    assert "999" not in flat and "Dorm B" not in flat
    assert "Bed 99" not in flat and "W-99" not in flat


async def test_dorm_attached_washroom_and_fixtures(session, seed):
    """dorm_id-scoped washroom: coverage comes from the owning dorm."""
    await _coverage_seed(session, seed)
    att = Washroom(
        property_id=seed["prop"].id, name="Attached W",
        washroom_type="male", dorm_id=seed["dorm"].id,  # no zone_id
    )
    session.add(att)
    await session.flush()
    session.add(WashroomFixture(
        property_id=seed["prop"].id, washroom_id=att.id,
        fixture_type="toilet", fixture_number=1,
    ))
    await session.commit()

    out = await MaintenanceService(session).eligible_locations(
        seed["emp_user"])
    w = next(w for w in out["washrooms"] if w["name"] == "Attached W")
    assert w["dorm_name"] == "Dorm A" and w["zone_name"] == "Z1"
    kinds = {f["fixture_type"] for f in out["fixtures"]}
    assert "toilet" in kinds


async def test_no_coverage_returns_empty(session, seed):
    out = await MaintenanceService(session).eligible_locations(
        seed["emp_user"])
    assert out == {
        "rooms": [], "dorms": [], "beds": [],
        "washrooms": [], "fixtures": [],
    }


async def test_area_coverage_includes_zone_children(session, seed):
    """Area assignment covers every zone inside the area."""
    from app.models.structure import Area
    area = Area(property_id=seed["prop"].id, name="Floor 1",
                code="F1", level_number=1)
    session.add(area)
    await session.flush()
    z1 = _zone(seed["prop"], "Z1")
    z1.area_id = area.id
    session.add(z1)
    await session.flush()
    seed["employee"].area_id = area.id
    seed["dorm"].zone_id = z1.id
    seed["washroom"].zone_id = z1.id
    await session.commit()

    out = await MaintenanceService(session).eligible_locations(
        seed["emp_user"])
    assert [d["name"] for d in out["dorms"]] == ["Dorm A"]
    assert len(out["beds"]) == 1 and len(out["washrooms"]) == 1


async def test_dorm_attached_washroom_passes_coverage(session, seed):
    """Regression — a dorm-attached washroom has no zone/area of its
    own; _enforce_employee_coverage must check the owning dorm or the
    ticket submit 403s even though the unit is in-scope."""
    await _coverage_seed(session, seed)
    att = Washroom(
        property_id=seed["prop"].id, name="Attached W",
        washroom_type="male", dorm_id=seed["dorm"].id,
    )
    session.add(att)
    await session.commit()

    svc = MaintenanceService(session)
    await svc._enforce_employee_coverage(  # must NOT raise
        seed["emp_user"], washroom=att)


async def test_out_of_scope_washroom_still_rejected(session, seed):
    z1 = await _coverage_seed(session, seed)
    out_z = _zone(seed["prop"], "Z9-out")
    session.add(out_z)
    await session.flush()
    w = Washroom(property_id=seed["prop"].id, name="Far W",
                 washroom_type="unisex", zone_id=out_z.id)
    session.add(w)
    await session.commit()
    with pytest.raises(Forbidden):
        await MaintenanceService(session)._enforce_employee_coverage(
            seed["emp_user"], washroom=w)
    assert z1 is not None
