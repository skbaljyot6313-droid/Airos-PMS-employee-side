"""Live location — current-position-only updates + self read.

Foreground tracker on the employee app POSTs a fix every ~10 s; Redis
holds the latest per employee under a 60 s TTL (latest-only — no
history, no Postgres in this path). Both endpoints are
employee-linked only (require_attendance_participant); the service
enforces the link and derives identity from the token, never the body.
"""

from fastapi import APIRouter, Depends

from app.dependencies.auth import require_attendance_participant
from app.models.user import User
from app.schemas.location import LocationUpdate
from app.services import location_live

router = APIRouter(prefix="/location", tags=["location"])


@router.post("/current")
async def post_current_location(
    payload: LocationUpdate,
    user: User = Depends(require_attendance_participant),
):
    return await location_live.post_current(user, payload)


@router.get("/current")
async def get_current_location(
    user: User = Depends(require_attendance_participant),
):
    return await location_live.get_current(user)
