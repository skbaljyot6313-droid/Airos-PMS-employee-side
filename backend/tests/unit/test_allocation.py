"""Acceptance tests for the unified work-allocation engine.

Covers the zone + area combined-pool contract:
  - area employees participate even when a zone has its own staff
  - workload is the primary factor; rotation breaks ties
  - department gating is applied to the combined pool
  - dedup of employees appearing at both levels
  - deactivated / on-leave employees are excluded
  - zones with no direct staff allocate to the area pool
"""
import uuid

import pytest

from app.models.employee import Employee
from app.models.structure import Area, Zone
from app.models.task import Task
from app.services.work_allocation import WorkAllocationService


def _emp(session, seed, name, dept, *, zone=None, area=None,
         status="Active", leave=False):
    e = Employee(
        company_id=seed["company"].id, property_id=seed["prop"].id,
        name=name, email=f"{name.lower()}@acme.test",
        department=dept, status=status, leave_status=leave,
        zone_id=zone.id if zone else None,
        area_id=area.id if area else None,
    )
    session.add(e)
    return e


async def _alloc(session, seed, *, zone, work_type="cleaning"):
    """allocate + record — the same pair production callers run."""
    svc = WorkAllocationService(session)
    res = await svc.allocate(
        seed["admin"],
        property_id=seed["prop"].id,
        zone_id=zone.id,
        zone_name=zone.name,
        work_type=work_type,
    )
    await svc.record(
        property_id=seed["prop"].id, zone_id=zone.id, batch=res.batch,
        ticket_kind="task", ticket_id=uuid.uuid4(), ticket_number=None,
        employee_id=res.employee.id if res.employee else None,
        employee_name=res.employee.name if res.employee else None,
        method=res.method, reason=res.reason,
    )
    return res


@pytest.fixture
async def staffed_area(session, seed):
    """Area A with Zone A (3 housekeeping staff) + 2 area-level staff."""
    area = Area(property_id=seed["prop"].id, name="Floor A", code="FA")
    session.add(area)
    await session.flush()  # area.id (uuid default) materializes on flush
    zone = Zone(property_id=seed["prop"].id, area_id=area.id,
                name="Zone A", code="ZA", floor="Floor A")
    session.add(zone)
    await session.flush()
    staff = {
        "e1": _emp(session, seed, "E1", "Housekeeping", zone=zone),
        "e2": _emp(session, seed, "E2", "Housekeeping", zone=zone),
        "e3": _emp(session, seed, "E3", "Housekeeping", zone=zone),
        "e5": _emp(session, seed, "E5", "Housekeeping", area=area),
        "e7": _emp(session, seed, "E7", "Housekeeping", area=area),
    }
    await session.flush()
    return {"area": area, "zone": zone, "staff": staff}


@pytest.mark.asyncio
async def test_area_staff_participate_beside_zone_staff(session, seed, staffed_area):
    """4 allocations across 3 zone + 2 area staff → 4 distinct picks."""
    chosen = set()
    for _ in range(4):
        res = await _alloc(session, seed, zone=staffed_area["zone"])
        chosen.add(res.employee.name)
    assert len(chosen) == 4


@pytest.mark.asyncio
async def test_full_pool_distribution_over_many_tasks(session, seed, staffed_area):
    """10 allocations spread across all 5 eligible employees — nobody
    hoards; each carries exactly 2."""
    counts: dict[str, int] = {}
    for _ in range(10):
        res = await _alloc(session, seed, zone=staffed_area["zone"])
        # bulk allocations inside one txn see in-flight workload via flush
        counts[res.employee.name] = counts.get(res.employee.name, 0) + 1
        t = Task(property_id=seed["prop"].id, employee_id=res.employee.id,
                 title="Cleaning", status="assigned")
        session.add(t)
        await session.flush()
    assert set(counts) == {"E1", "E2", "E3", "E5", "E7"}
    assert all(c == 2 for c in counts.values())


@pytest.mark.asyncio
async def test_zone_without_staff_uses_area_pool(session, seed, staffed_area):
    """Zone C has no direct employees — the area pool covers it."""
    zone_c = Zone(property_id=seed["prop"].id,
                  area_id=staffed_area["area"].id,
                  name="Zone C", code="ZC", floor="Floor A")
    session.add(zone_c)
    await session.flush()
    res = await _alloc(session, seed, zone=zone_c)
    assert res.employee.name in ("E5", "E7")


@pytest.mark.asyncio
async def test_workload_beats_zone_membership(session, seed, staffed_area):
    """E1 loaded with open tasks → next pick goes to the least-loaded
    area employee, not a zone member."""
    e1 = staffed_area["staff"]["e1"]
    for _ in range(5):
        session.add(Task(property_id=seed["prop"].id, employee_id=e1.id,
                         title="Cleaning", status="assigned"))
    await session.flush()
    # Force E2/E3 to carry work too so the least-loaded pick is an area one
    e2, e3 = staffed_area["staff"]["e2"], staffed_area["staff"]["e3"]
    for emp, n in ((e2, 2), (e3, 3)):
        for _ in range(n):
            session.add(Task(property_id=seed["prop"].id, employee_id=emp.id,
                             title="Cleaning", status="assigned"))
    await session.flush()
    res = await _alloc(session, seed, zone=staffed_area["zone"])
    assert res.employee.name in ("E5", "E7")  # load 0 area staff win


@pytest.mark.asyncio
async def test_department_gating_on_combined_pool(session, seed):
    """Maintenance work never lands on housekeeping staff, zone or area."""
    area = Area(property_id=seed["prop"].id, name="Floor B", code="FB")
    session.add(area)
    await session.flush()  # area.id (uuid default) materializes on flush
    zone = Zone(property_id=seed["prop"].id, area_id=area.id,
                name="Zone B", code="ZB", floor="Floor B")
    session.add(zone)
    await session.flush()
    _emp(session, seed, "HK1", "Housekeeping", zone=zone)
    m = _emp(session, seed, "MN1", "Maintenance & Engineering", zone=zone)
    ma = _emp(session, seed, "MN2", "Maintenance & Engineering", area=area)
    _emp(session, seed, "HK2", "Housekeeping", area=area)
    await session.flush()
    for _ in range(4):
        res = await _alloc(session, seed, zone=zone, work_type="maintenance")
        assert res.employee.id in (m.id, ma.id)
        # mark done so rotation continues through the pool
        res.batch  # noqa
        session.add(Task(property_id=seed["prop"].id,
                         employee_id=res.employee.id,
                         title="Maintenance", status="assigned"))
        await session.flush()


@pytest.mark.asyncio
async def test_employee_in_both_pools_deduplicated(session, seed, staffed_area):
    """An employee carrying zone_id AND area_id is counted once."""
    staff = staffed_area["staff"]
    staff["e1"].area_id = staffed_area["area"].id  # dual assignment
    await session.flush()
    pool, _ = await WorkAllocationService(session).eligible_employees(
        seed["prop"].id, staffed_area["zone"].id,
        area_id=staffed_area["area"].id,
        departments=("housekeeping",),
    )
    ids = [e.id for e in pool]
    assert ids.count(staff["e1"].id) == 1


@pytest.mark.asyncio
async def test_deactivated_and_on_leave_excluded(session, seed, staffed_area):
    _emp(session, seed, "INACTIVE", "Housekeeping",
         zone=staffed_area["zone"], status="Deactivated")
    _emp(session, seed, "ONLEAVE", "Housekeeping",
         zone=staffed_area["zone"], leave=True)
    await session.flush()
    pool, _ = await WorkAllocationService(session).eligible_employees(
        seed["prop"].id, staffed_area["zone"].id,
        area_id=staffed_area["area"].id,
        departments=("housekeeping",),
    )
    names = {e.name for e in pool}
    assert "INACTIVE" not in names and "ONLEAVE" not in names


@pytest.mark.asyncio
async def test_no_eligible_reports_reason(session, seed):
    """Empty pool → UNASSIGNED with reason, not a scattered pick."""
    zone = Zone(property_id=seed["prop"].id, name="Empty", code="ZE",
                floor="Nowhere")
    session.add(zone)
    await session.flush()
    res = await _alloc(session, seed, zone=zone, work_type="maintenance")
    assert res.employee is None
    assert res.reason == "no_eligible_employee"
    assert res.batch.allocation_status == "unassigned"


@pytest.mark.asyncio
async def test_unified_pool_order_is_scope_agnostic(session, seed, staffed_area):
    """Coverage determines eligibility, never priority — the merged pool
    is ordered by created_at, not zone-first. An area employee created
    BEFORE the zone staff must head the tie order."""
    import datetime as _dt
    area_emp = _emp(session, seed, "E0", "Housekeeping",
                    area=staffed_area["area"])
    await session.flush()
    # force a strictly earlier timestamp than the zone staff
    area_emp.created_at = _dt.datetime(2024, 1, 1)
    zone_emp = staffed_area["staff"]["e1"]
    zone_emp.created_at = _dt.datetime(2024, 1, 2)
    for e in staffed_area["staff"].values():
        if e is not area_emp and e.created_at is None:
            e.created_at = _dt.datetime(2024, 1, 2)
    await session.flush()

    svc = WorkAllocationService(session)
    _, _, pool, level = await svc._eligible_pools(
        seed["prop"].id, staffed_area["zone"].id,
        manager_employee_id=None,
        departments=("housekeeping",),
    )
    names = [e.name for e in pool]
    assert level == "zone+area"
    assert len(names) == len(set(names))          # deduped
    assert names[0] == "E0"                        # earliest-created leads
    # zone and area staff interleave by created_at, not by coverage scope
    assert set(names) == {"E0", "E1", "E2", "E3", "E5", "E7"}


async def _alloc_scoped(session, seed, *, zone=None, area=None,
                        work_type="cleaning"):
    """allocate at any level — zone / area / property (all None)."""
    svc = WorkAllocationService(session)
    res = await svc.allocate(
        seed["admin"],
        property_id=seed["prop"].id,
        zone_id=zone.id if zone else None,
        zone_name=zone.name if zone else None,
        area_id=area.id if area else None,
        area_name=area.name if area else None,
        work_type=work_type,
    )
    await svc.record(
        property_id=seed["prop"].id,
        zone_id=zone.id if zone else None,
        batch=res.batch,
        ticket_kind="task", ticket_id=uuid.uuid4(), ticket_number=None,
        employee_id=res.employee.id if res.employee else None,
        employee_name=res.employee.name if res.employee else None,
        method=res.method, reason=res.reason,
    )
    return res


@pytest.mark.asyncio
async def test_property_level_task_uses_property_pool(session, seed,
                                                      staffed_area):
    """No zone, no area → the ENTIRE property's eligible staff form the
    pool (dept-gated) and rotate fairly — not 'no_zone' unassigned."""
    chosen = []
    for _ in range(5):
        res = await _alloc_scoped(session, seed, work_type="cleaning")
        assert res.level == "property"
        assert res.employee is not None
        chosen.append(res.employee.name)
        session.add(Task(property_id=seed["prop"].id,
                         employee_id=res.employee.id,
                         title="Ops", status="assigned"))
        await session.flush()
    # all 5 housekeeping staff in the property participate
    assert set(chosen) == {"E1", "E2", "E3", "E5", "E7"}


@pytest.mark.asyncio
async def test_area_task_includes_zone_staff(session, seed, staffed_area):
    """Area-level task pool = area-wide staff UNION staff of zones
    inside the area — a zone-only employee is eligible for area work."""
    res = await _alloc_scoped(session, seed, area=staffed_area["area"],
                              work_type="cleaning")
    assert res.employee is not None
    assert res.level == "area"
    # the unified area pool holds all 5 housekeeping employees
    assert {e.name for e in res.pool_employees} == \
        {"E1", "E2", "E3", "E5", "E7"}

    # rotate over all 5
    chosen = set()
    for _ in range(5):
        res = await _alloc_scoped(session, seed, area=staffed_area["area"])
        chosen.add(res.employee.name)
        session.add(Task(property_id=seed["prop"].id,
                         employee_id=res.employee.id,
                         title="Ops", status="assigned"))
        await session.flush()
    assert len(chosen) == 5


@pytest.mark.asyncio
async def test_property_task_no_eligible_still_unassigned(session, seed):
    """A property-level maintenance task with no maintenance staff stays
    UNASSIGNED — eligibility is never bypassed."""
    res = await _alloc_scoped(session, seed, work_type="maintenance")
    assert res.employee is None
    assert res.reason == "no_eligible_employee"
    assert res.level == "property"


@pytest.mark.asyncio
async def test_allocate_people_named_employees(session, seed, staffed_area):
    """Operations → specific employees: the named list IS the pool.
    An ineligible (wrong-department) name is silently excluded."""
    staff = staffed_area["staff"]
    pool = [staff["e1"], staff["e5"]]  # housekeeping pair, mixed coverage
    chosen = set()
    for _ in range(4):
        res = await WorkAllocationService(session).allocate_people(
            seed["admin"], property_id=seed["prop"].id,
            employees=pool, work_type="cleaning",
            pool_label="2 named employees",
        )
        chosen.add(res.employee.name)
        session.add(Task(property_id=seed["prop"].id,
                         employee_id=res.employee.id,
                         title="Ops", status="assigned"))
        await session.flush()
    assert chosen == {"E1", "E5"}
    assert res.level == "people"


@pytest.mark.asyncio
async def test_allocate_people_department_gating(session, seed,
                                                 staffed_area):
    """A 'maintenance' people-pool task: housekeeping members are
    filtered out even though the caller passed them."""
    maint = _emp(session, seed, "M1", "Maintenance",
                 area=staffed_area["area"])
    await session.flush()
    staff = staffed_area["staff"]
    res = await WorkAllocationService(session).allocate_people(
        seed["admin"], property_id=seed["prop"].id,
        employees=[staff["e1"], staff["e5"], maint],
        work_type="maintenance", pool_label="dept:Maintenance",
    )
    assert res.employee.name == "M1"


@pytest.mark.asyncio
async def test_allocate_people_empty_pool_unassigned(session, seed):
    res = await WorkAllocationService(session).allocate_people(
        seed["admin"], property_id=seed["prop"].id,
        employees=[], work_type="cleaning",
    )
    assert res.employee is None
    assert res.reason == "no_eligible_employee"
