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

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.core.storage import get_storage
from app.dependencies.auth import require_release_service
from app.schemas.mobile import (
    MobileReleaseCreate,
    MobileReleaseOut,
    MobileReleasePatch,
    MobileVersionResponse,
)
from app.services import mobile_release as release_service
from app.services.mobile_release import ReleaseNotFound

router = APIRouter(prefix="/mobile", tags=["mobile"])

logger = get_logger("app.mobile")

# Release binaries dwarf the 10 MB image cap — own bound.
APK_MAX_BYTES = 512 * 1024 * 1024
APK_CONTENT_TYPE = "application/vnd.android.package-archive"


class InvalidUpload(AppError):
    status_code = 422
    code = "INVALID_UPLOAD"


class StorageUnavailable(AppError):
    status_code = 502
    code = "STORAGE_UNAVAILABLE"


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


@router.post("/releases/apk", status_code=201)
async def upload_release_apk(
    platform: str = Query(default="android", pattern=r"^[a-z]+$"),
    version_code: int = Query(ge=1),
    file: UploadFile = File(...),
    _service: None = Depends(require_release_service),
):
    """Self-host a release binary — the CI pipeline uploads the EAS-built
    APK here and registers the returned URL as download_url, so devices
    fetch the update from our storage in one hop instead of chasing
    expiring/redirecting third-party artifact URLs."""
    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > APK_MAX_BYTES:
            raise InvalidUpload("APK exceeds the 512 MB limit.")
        chunks.append(chunk)
    data = b"".join(chunks)
    if len(data) < 4 or data[:2] != b"PK":
        raise InvalidUpload("Not an APK — ZIP signature missing.")
    # Flat key — object stores treat '/' fine but the local backend and
    # key-from-URL recovery both assume flat names.
    key = f"release-{platform}-{version_code}-{uuid.uuid4().hex[:8]}.apk"
    try:
        url = await get_storage().save(data, key, APK_CONTENT_TYPE)
    except AppError:
        raise
    except Exception as exc:
        logger.error("APK storage save failed for key %s: %s", key, exc)
        raise StorageUnavailable(
            "Release storage is unavailable — check the storage backend "
            "configuration."
        ) from exc
    logger.info("release APK stored platform=%s code=%s key=%s",
                platform, version_code, key)
    return {"url": url, "key": key, "size_bytes": len(data)}


@router.patch("/releases/{release_id}", response_model=MobileReleaseOut)
async def update_release(
    release_id: uuid.UUID,
    data: MobileReleasePatch,
    platform: str = "android",
    session: AsyncSession = Depends(get_db),
    _service: None = Depends(require_release_service),
):
    """Repoint download_url / edit notes on a published release — the
    escape hatch when a hosted artifact link rots or moves."""
    return await release_service.update_release(
        session, release_id, platform, data
    )


@router.post("/releases/{release_id}/activate", response_model=MobileReleaseOut)
async def activate_release(
    release_id: uuid.UUID,
    platform: str = "android",
    session: AsyncSession = Depends(get_db),
    _service: None = Depends(require_release_service),
):
    return await release_service.activate_release(session, release_id, platform)
