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

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.core.rate_limit import rate_limit
from app.core.storage import get_storage, storage_key_from_url
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
        # Devices download through this origin only — the stored URL may
        # point at hosts (expo.dev, supabase.co, CDNs) that field networks
        # can't reach, while the API domain is already proven.
        download_url=f"/api/v1/mobile/apk?platform={release.platform}",
        release_notes=release.release_notes,
        force_update=release.force_update,
    )


@router.get(
    "/apk",
    dependencies=[Depends(rate_limit("apk_fetch", limit=30, window_seconds=60))],
)
async def download_active_apk(
    platform: str = "android",
    session: AsyncSession = Depends(get_db),
):
    """Stream the active release binary through the API origin.

    The stored download_url may reference storage (self-hosted APK) or a
    third-party artifact host (expo.dev) — either way the device only
    ever talks to this domain. The URL comes from the release registry,
    never from the client, so this cannot be turned into an open proxy.
    """
    release = await release_service.get_active_release(session, platform)
    if release is None:
        raise ReleaseNotFound()
    headers = {
        "Content-Disposition": (
            f'attachment; filename="airos-{release.platform}-'
            f'{release.version}.apk"'
        ),
        "X-Content-Type-Options": "nosniff",
        # APKs don't compress — bypass GZipMiddleware so Content-Length
        # reaches the client for download progress.
        "Content-Encoding": "identity",
    }
    key = storage_key_from_url(release.download_url)
    if key:
        try:
            opened = await get_storage().open(key)
        except Exception as exc:
            logger.error("release storage fetch failed key=%s: %s", key, exc)
            raise StorageUnavailable(
                "Release storage is unavailable."
            ) from exc
        if opened is None:
            raise ReleaseNotFound()
        stream, _ct, length = opened
        if length is not None:
            headers["Content-Length"] = str(length)
        return StreamingResponse(
            stream(), media_type=APK_CONTENT_TYPE, headers=headers
        )

    url = release.download_url
    if not url.lower().startswith("https://"):
        raise StorageUnavailable("Stored release URL is invalid.")

    import httpx  # deferred — only needed for externally hosted binaries

    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=30
        ) as client:
            head = await client.head(url)
            if head.status_code != 200:
                raise StorageUnavailable(
                    f"Release artifact unavailable (upstream {head.status_code})."
                )
            length = head.headers.get("Content-Length")
    except StorageUnavailable:
        raise
    except Exception as exc:
        logger.error("release artifact probe failed: %s", exc)
        raise StorageUnavailable(
            "Release artifact is unreachable."
        ) from exc
    if length and length.isdigit():
        headers["Content-Length"] = length

    async def upstream():
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=300
        ) as client:
            async with client.stream("GET", url) as res:
                res.raise_for_status()
                async for chunk in res.aiter_bytes(256 * 1024):
                    yield chunk

    return StreamingResponse(
        upstream(), media_type=APK_CONTENT_TYPE, headers=headers
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
    request: Request,
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
    # Register an absolute same-origin proxy URL — the raw storage URL
    # points at a host devices may not reach, and relative paths fail
    # the download_url validator.
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.url.netloc)
    proxy_url = f"{proto}://{host}/api/v1/media/file/{key}"
    return {"url": proxy_url, "key": key, "size_bytes": len(data)}


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
