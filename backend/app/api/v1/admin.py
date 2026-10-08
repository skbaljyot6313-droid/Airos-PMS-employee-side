"""Admin — server-to-server endpoints for the SA backend.

These routes are NOT employee-facing: they are gated by
require_location_service (shared bearer key, constant-time compare) —
never by get_current_user, so employee/manager JWTs are rejected and no
DB session is opened on this path.
"""

from fastapi import APIRouter, Depends

from app.dependencies.auth import require_location_service
from app.services import location_live

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/live-locations")
async def get_live_locations(
    _service: None = Depends(require_location_service),
):
    return await location_live.get_all_live()
