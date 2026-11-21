"""Extended employee coverage — secondary zone + property-wide flag.

Regression tests for the shared-boundary semantics the Super Admin backend
writes via `employees.secondary_zone_id` / `employees.covers_property`:
EB coverage queries must union primary zone, secondary zone, area zones,
and property-wide scope — in maintenance enforcement, eligible-location
picklists, and the work-allocation pools.
"""
import uuid

from app.models.employee import Employee
from app.models.structure import Area, Zone
from app.models.user import UserRole
from app.services.maintenance import MaintenanceService
from app.services.work_allocation import WorkAllocationService
from duty import clock_in


def _zone(prop, name, area=None):
    z = Zone(
        property_id=prop.id, area_id=area.id if area else None,
        name=name, code=f"Z-{name}", zone_type="stay",
    )
    return z


async def _flush_zones(session, *zones):
    """Zone ids are column defaults — must flush before referencing."""
    session.add_all(zones)
    await session.flush()


def _emp_user(seed, employee):
    """A User row of role EMPLOYEE pointing at the given Employee row."""
    from app.models.user import User
    u = User(
        company_id=seed["company"].id, property_id=seed["prop"].id,
        name=employee.name, email=f"{uuid.uuid4().hex[:8]}@t.test",
        username=uuid.uuid4().hex[:8], password_hash="x",
        role=UserRole.EMPLOYEE, employee_id=employee.id,
    )
    return u


async def _make_employee(session, seed, **coverage):
    emp = Employee(
        company_id=seed["company"].id, property_id=seed["prop"].id,
        name=coverage.pop("name", "Cov Worker"), email=f"{uuid.uuid4().hex[:8]}@e.test",
        status="active", **coverage,
    )
    session.add(emp)
    await session.flush()
    return emp


async def test_secondary_zone_is_covered(session, seed):
    zone_a, zone_b = _zone(seed["prop"], "A"), _zone(seed["prop"], "B")
    await _flush_zones(session, zone_a, zone_b)
    emp = await _make_employee(
        session, seed, zone_id=zone_a.id, secondary_zone_id=zone_b.id)
    await session.commit()

    svc = MaintenanceService(session)
    zone_ids, area_ids, covers = await svc._employee_coverage(
        _emp_user(seed, emp))
    assert zone_ids == {zone_a.id, zone_b.id}
    assert area_ids == set()
    assert covers is False


async def test_covers_property_spans_every_zone(session, seed):
    zones = [_zone(seed["prop"], n) for n in "XYZ"]
    await _flush_zones(session, *zones)
    emp = await _make_employee(session, seed, covers_property=True)
    await session.commit()

    svc = MaintenanceService(session)
    zone_ids, _, covers = await svc._employee_coverage(_emp_user(seed, emp))
    assert covers is True
    assert {z.id for z in zones} <= zone_ids


async def test_area_coverage_still_unions_area_zones(session, seed):
    area = Area(property_id=seed["prop"].id, name="Floor 1", code="F1")
    session.add(area)
    await session.flush()
    zones = [_zone(seed["prop"], n, area=area) for n in ("P", "Q")]
    await _flush_zones(session, *zones)
    emp = await _make_employee(session, seed, area_id=area.id)
    await session.commit()

    svc = MaintenanceService(session)
    zone_ids, area_ids, covers = await svc._employee_coverage(
        _emp_user(seed, emp))
    assert covers is False
    assert area_ids == {area.id}
    assert {z.id for z in zones} <= zone_ids


async def test_zone_pool_includes_secondary_and_property_wide(session, seed):
    zone_a, zone_b = _zone(seed["prop"], "RA"), _zone(seed["prop"], "RB")
    await _flush_zones(session, zone_a, zone_b)
    primary = await _make_employee(session, seed, name="P", zone_id=zone_a.id)
    secondary = await _make_employee(
        session, seed, name="S", zone_id=zone_b.id,
        secondary_zone_id=zone_a.id)
    wide = await _make_employee(session, seed, name="W", covers_property=True)
    outsider = await _make_employee(session, seed, name="O", zone_id=zone_b.id)
    await session.commit()
    await clock_in(session)

    svc = WorkAllocationService(session)
    zone_pool, _, pool, _ = await svc._eligible_pools(
        seed["prop"].id, zone_a.id)
    ids = {e.id for e in zone_pool}
    assert {primary.id, secondary.id, wide.id} <= ids
    assert outsider.id not in ids  # zone_b primary with no secondary into A
    assert len(pool) == len({e.id for e in pool})  # deduplicated union


async def test_area_level_pool_includes_secondary_zones(session, seed):
    area = Area(property_id=seed["prop"].id, name="Floor 9", code="F9")
    session.add(area)
    await session.flush()
    in_area = _zone(seed["prop"], "IA", area=area)
    await _flush_zones(session, in_area)
    via_secondary = await _make_employee(
        session, seed, name="VS", secondary_zone_id=in_area.id)
    wide = await _make_employee(session, seed, name="PW", covers_property=True)
    await session.commit()
    await clock_in(session)

    svc = WorkAllocationService(session)
    _, area_pool, pool, _ = await svc._eligible_pools(
        seed["prop"].id, None, area_id=area.id)
    ids = {e.id for e in area_pool}
    assert {via_secondary.id, wide.id} <= ids
