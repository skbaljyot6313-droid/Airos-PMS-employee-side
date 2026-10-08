"""Location — tracking sessions + position ingest + self read.

POST /location/start mints a tracking session (Postgres lifecycle row +
Redis marker the ingest path validates against). The native tracker then
POSTs /location/current on its own cadence — ingest is DB-free: Redis
holds the live hash (TTL), the daily history ZSETs and the GEO index,
all in one pipeline. POST /location/stop ends the session; history is
never deleted. employee_id always comes from the bearer token.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import require_attendance_participant
from app.models.user import User
from app.schemas.location import (
    LocationStartResponse,
    LocationStopRequest,
    LocationStopResponse,
    LocationUpdate,
)
from app.services import location_live, location_tracking
from app.services.location_live import _require_employee

router = APIRouter(prefix="/location", tags=["location"])


@router.post(
    "/start",
    response_model=LocationStartResponse,
    summary="Start a location tracking session",
)
async def start_tracking(
    user: User = Depends(require_attendance_participant),
    session: AsyncSession = Depends(get_db),
):
    """Mint a tracking session — the server owns the session identity.
    Employees may hold several sessions per day (shift gaps, app
    restarts); sessions are decoupled from attendance."""
    row = await location_tracking.start_session(
        user, _require_employee(user), session
    )
    return LocationStartResponse(
        tracking_session_id=row.id,
        started_at=row.started_at,
        tracking_interval_seconds=location_tracking.TRACKING_INTERVAL_SECONDS,
    )


@router.post("/current")
async def post_current_location(
    payload: LocationUpdate,
    user: User = Depends(require_attendance_participant),
):
    """Ingest one position fix — Redis only, pipelined, idempotent on
    (employee, session, sequence)."""
    return await location_live.post_current(user, payload)


@router.get("/current")
async def get_current_location(
    user: User = Depends(require_attendance_participant),
):
    return await location_live.get_current(user)


@router.post(
    "/stop",
    response_model=LocationStopResponse,
    summary="Stop a tracking session",
)
async def stop_tracking(
    payload: LocationStopRequest,
    user: User = Depends(require_attendance_participant),
    session: AsyncSession = Depends(get_db),
):
    """End the session — historical points are never deleted, and a
    stopped session rejects further ingestion."""
    stopped_at = await location_tracking.stop_session(
        user,
        _require_employee(user),
        payload.tracking_session_id,
        session,
    )
    return LocationStopResponse(stopped=True, stopped_at=stopped_at)
