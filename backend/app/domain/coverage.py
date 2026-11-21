"""Canonical employee-coverage SQL predicates — single source of truth.

Employee allocation coverage is a UNION of additive assignment modes
(written via the employee allocation surface):

* ``zone_id``            — primary zone assignment
* ``secondary_zone_id``  — optional second zone (max 2 named zones)
* ``area_id``            — primary area ⇒ every zone inside that area
* ``employee_area_assignments`` — ADDITIONAL whole areas (multi-area
  coverage); each row's zones are all inside the employee's coverage
* ``covers_property``    — property-wide ⇒ every zone in the property
  (the one exclusive mode — setting it clears the rest)

Zones and areas coexist — an employee may cover two named zones AND
several whole areas simultaneously.

Every eligibility query — allocation pools, employee directory filters,
maintenance coverage, live-location scoping — MUST compose these helpers
instead of re-typing ``or_(...)`` fragments. The employee backend keeps a
verbatim mirror of this file; if the semantics change, change BOTH repos
and bump the shared-schema contract tests.
"""
from sqlalchemy import or_, select

from app.models.employee import Employee, EmployeeAreaAssignment
from app.models.structure import Zone


def _extra_area_employees(area_id):
    """Subquery: employees holding ``area_id`` as an ADDITIONAL area."""
    return select(EmployeeAreaAssignment.employee_id).where(
        EmployeeAreaAssignment.area_id == area_id
    )


def covers_zone(zone_id):
    """Predicate: employee is eligible for work inside ``zone_id``.

    Primary zone, secondary zone, or property-wide coverage."""
    return or_(
        Employee.zone_id == zone_id,
        Employee.secondary_zone_id == zone_id,
        Employee.covers_property.is_(True),
    )


def covers_area(area_id):
    """Predicate: employee covers an area-level target.

    Assigned to the area directly, assigned to any zone inside the area
    (primary or secondary), or property-wide."""
    area_zones = select(Zone.id).where(Zone.area_id == area_id)
    return or_(
        Employee.area_id == area_id,
        Employee.id.in_(_extra_area_employees(area_id)),
        Employee.zone_id.in_(area_zones),
        Employee.secondary_zone_id.in_(area_zones),
        Employee.covers_property.is_(True),
    )


def covers_area_direct(area_id):
    """Predicate: direct area coverage only — the area *fallback* tier for
    zone-scoped allocation (area assignees + property-wide staff), without
    pulling in per-zone staff (they already live in the zone pool)."""
    return or_(
        Employee.area_id == area_id,
        Employee.id.in_(_extra_area_employees(area_id)),
        Employee.covers_property.is_(True),
    )
