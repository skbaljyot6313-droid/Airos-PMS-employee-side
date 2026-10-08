"""Mobile release endpoints.

GET /mobile/version is PUBLIC — an app that is too old to log in must
still be able to learn that an update exists. It returns only release
metadata; no credentials or infrastructure details.

POST /mobile/releases and POST /mobile/releases/{id}/activate are
server-to-server (CI release pipeline / ops) — gated by
require_release_service (RELEASE_MANAGEMENT_API_KEY bearer, constant-time),
never by employee JWTs.
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import require_release_service
from app.schemas.mobile import (
    MobileReleaseCreate,
    MobileReleaseOut,
    MobileVersionResponse,
)
from app.services import mobile_release as release_service
from app.services.mobile_release import ReleaseNotFound

router = APIRouter(prefix="/mobile", tags=["mobile"])


@router.get("/version", response_model=MobileVersionResponse)
async def get_version(
    platform: str = "android",
    session: AsyncSession = Depends(get_db),
):
    release = await release_service.get_active_release(session, platform)
    if release is None:
        raise ReleaseNotFound()
    return MobileVersionResponse(
        platform=release.platform,
        latest_version=release.version,
        latest_version_code=release.version_code,
        minimum_version=release.minimum_version,
        minimum_version_code=release.minimum_version_code,
        download_url=release.download_url,
        release_notes=release.release_notes,
        force_update=release.force_update,
    )


@router.get("/releases", response_model=list[MobileReleaseOut])
async def list_releases(
    platform: str = "android",
    session: AsyncSession = Depends(get_db),
    _service: None = Depends(require_release_service),
):
    return await release_service.list_releases(session, platform)


@router.post("/releases", response_model=MobileReleaseOut, status_code=201)
async def publish_release(
    data: MobileReleaseCreate,
    session: AsyncSession = Depends(get_db),
    _service: None = Depends(require_release_service),
):
    return await release_service.publish_release(session, data)


@router.post("/releases/{release_id}/activate", response_model=MobileReleaseOut)
async def activate_release(
    release_id: uuid.UUID,
    platform: str = "android",
    session: AsyncSession = Depends(get_db),
    _service: None = Depends(require_release_service),
):
    return await release_service.activate_release(session, release_id, platform)
