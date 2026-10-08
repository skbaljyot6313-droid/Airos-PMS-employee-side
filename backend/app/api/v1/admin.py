"""Admin — server-to-server location endpoints for the SA backend.

These routes are NOT employee-facing: they are gated by
require_location_service (shared bearer key, constant-time compare) —
never by get_current_user, so employee/manager JWTs are rejected.

The service key is global (not tenant-scoped): the SA backend is
trusted infrastructure; scope filters (employee/property/zone) narrow
the result set, they don't grant or revoke access. property_id/zone_id
filters resolve through a single employees-table lookup — the only DB
touch on this path, and it happens only when a scope filter is present.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import AppError
from app.dependencies.auth import require_location_service
from app.models.employee import Employee
from app.services import location_live, location_tracking

router = APIRouter(prefix="/admin", tags=["admin"])


class UnsupportedFilter(AppError):
    status_code = 400
    code = "INVALID_FILTER"
    message = "is_active=false is only supported with employee_id."


@router.get("/live-locations")
async def get_live_locations(
    employee_id: uuid.UUID | None = Query(default=None),
    property_id: uuid.UUID | None = Query(default=None),
    zone_id: uuid.UUID | None = Query(default=None),
    is_active: bool = Query(default=True),
    _service: None = Depends(require_location_service),
    session: AsyncSession = Depends(get_db),
):
    """Snapshot of every employee with a live (non-expired) fix.

    employee_id → that employee only (is_stale entries included when
    is_active=false). property_id/zone_id → employees assigned there —
    resolved via one employees query, then intersected with the live
    index. All optional and composable.
    """
    if not is_active and (employee_id is None):
        raise UnsupportedFilter()
    scoped_ids: set[str] | None = None
    if property_id is not None or zone_id is not None:
        q = select(Employee.id)
        if property_id is not None:
            q = q.where(Employee.property_id == property_id)
        if zone_id is not None:
            q = q.where(Employee.zone_id == zone_id)
        scoped_ids = {
            str(r) for r in (await session.execute(q)).scalars().all()
        }
        if employee_id is not None and str(employee_id) not in scoped_ids:
            return {"locations": []}
    return await location_live.get_all_live(
        employee_id=employee_id,
        include_stale=not is_active,
        scoped_ids=scoped_ids,
    )


@router.get("/location-history/{employee_id}")
async def get_location_history(
    employee_id: uuid.UUID,
    from_dt: datetime = Query(alias="from"),
    to_dt: datetime = Query(alias="to"),
    tracking_session_id: uuid.UUID | None = Query(default=None),
    max_points: int | None = Query(default=None, ge=1, le=100_000),
    _service: None = Depends(require_location_service),
):
    """Time-ranged route history — daily ZSET partitions, bounded,
    stride-downsampled when the range holds more than the point cap."""
    return await location_tracking.get_history(
        employee_id, from_dt, to_dt,
        session_id=tracking_session_id, max_points=max_points,
    )
