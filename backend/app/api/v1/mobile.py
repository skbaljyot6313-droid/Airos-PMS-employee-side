import hashlib
import time

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

from app.core.apk_signing import signer_sha256
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


class SignerMismatch(AppError):
    status_code = 409
    code = "SIGNER_MISMATCH"


async def _stored_signer(download_url: str | None) -> str | None:
    """Signer fingerprint of a self-hosted release binary — read from the
    upload-time metadata stamp, else computed from the stored bytes.
    None for external/missing binaries (nothing to compare against)."""
    key = storage_key_from_url(download_url) if download_url else None
    if not key:
        return None
    storage = get_storage()
    meta = await storage.head(key)
    if meta and meta.get("signer_sha256"):
        return meta["signer_sha256"]
    opened = await storage.open(key)
    if opened is None:
        return None
    stream, _ct, _len = opened
    return signer_sha256(b"".join([chunk async for chunk in stream()]))


# Signer resolution may mean pulling the whole release binary (legacy
# objects predate the upload-time metadata stamp) — cache per URL.
_SIGNER_CACHE_TTL_S = 900
_signer_cache: dict[str, tuple[float, str | None]] = {}


async def _cached_signer(download_url: str | None) -> str | None:
    if not download_url:
        return None
    hit = _signer_cache.get(download_url)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    try:
        signer = await _stored_signer(download_url)
    except Exception as exc:
        logger.error("release signer lookup failed url=%s: %s",
                     download_url, exc)
        signer = None
    _signer_cache[download_url] = (
        time.monotonic() + _SIGNER_CACHE_TTL_S, signer,
    )
    return signer


@router.get("/version", response_model=MobileVersionResponse)
async def get_version(
    platform: str = "android",
    installed_version_code: int | None = None,
    session: AsyncSession = Depends(get_db),
):
    release = await release_service.get_active_release(session, platform)
    if release is None:
        raise ReleaseNotFound()
    # Integrity metadata lives on the stored object (stamped at upload) —
    # no schema column needed. Externally-hosted releases report None and
    # the device falls back to its signature/versionCode gates.
    sha256 = size = None
    key = storage_key_from_url(release.download_url) if release.download_url else None
    if key:
        try:
            meta = await get_storage().head(key)
            if meta:
                sha256 = meta.get("sha256")
                raw = meta.get("file_size_bytes") or meta.get("size")
                size = int(raw) if raw else None
        except Exception:
            pass  # storage hiccup must never break the version check
    update_available = mandatory = update_compatible = None
    incompatible_reason = installed_signer = latest_signer = None
    if installed_version_code is not None:
        update_available = release.version_code > installed_version_code
        if update_available:
            # Android refuses an update signed by a different certificate
            # (WRONG_SIGNATURE) — never advertise such a release as an
            # installable update. Signers resolve from stored object
            # metadata (or the binary itself for legacy objects); None on
            # either side means "unknown" and the device's native signer
            # check remains the gate.
            latest_signer = await _cached_signer(release.download_url)
            installed_rel = await release_service.get_release_by_code(
                session, platform, installed_version_code
            )
            if installed_rel is not None:
                installed_signer = await _cached_signer(
                    installed_rel.download_url
                )
            if latest_signer and installed_signer:
                update_compatible = latest_signer == installed_signer
                if not update_compatible:
                    incompatible_reason = "SIGNER_MISMATCH"
                    update_available = False
                    logger.warning(
                        "withholding incompatible update: installed "
                        "code=%s signer=%s latest code=%s signer=%s",
                        installed_version_code, installed_signer,
                        release.version_code, latest_signer,
                    )
        # Never force a gate the device cannot pass — mandatory is only
        # meaningful while an installable update exists.
        mandatory = bool(
            update_available
            and (release.force_update
                 or installed_version_code < release.minimum_version_code)
        )
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
        sha256=sha256,
        file_size_bytes=size,
        installed_version_code=installed_version_code,
        update_available=update_available,
        mandatory_update=mandatory,
        update_compatible=update_compatible,
        incompatibility_reason=incompatible_reason,
        signer_sha256=latest_signer,
        installed_signer_sha256=installed_signer,
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
    url = release.download_url
    await session.close()
    key = storage_key_from_url(url)
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
    allow_signer_change: bool = Query(default=False),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db),
    _service: None = Depends(require_release_service),
):
    """Self-host a release binary — the CI pipeline uploads the EAS-built
    APK here and registers the returned URL as download_url, so devices
    fetch the update from our storage in one hop instead of chasing
    expiring/redirecting third-party artifact URLs.

    Signer gate: installed devices reject any update signed by a different
    certificate (WRONG_SIGNATURE on device), so a binary whose signer
    differs from the active release is refused with 409 unless the
    operator explicitly passes allow_signer_change=true (deliberate key
    rotation — every device must then reinstall manually)."""
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
    digest = hashlib.sha256(data).hexdigest()
    signer = signer_sha256(data)
    if signer is None:
        raise InvalidUpload("APK carries no v2/v3 signature — sign the build first.")
    active = await release_service.get_active_release(session, platform)
    active_url = active.download_url if active else None
    await session.close()
    try:
        previous_signer = await _stored_signer(active_url)
    except Exception as exc:
        logger.error("active release signer lookup failed: %s", exc)
        raise StorageUnavailable(
            "Could not read the active release to verify its signer."
        ) from exc
    if previous_signer and previous_signer != signer:
        if not allow_signer_change:
            raise SignerMismatch(
                f"APK signer {signer[:16]}… differs from the active release "
                f"signer {previous_signer[:16]}… — installed devices would "
                "reject this update (WRONG_SIGNATURE). Rebuild with the pinned "
                "signing key, or pass allow_signer_change=true for a deliberate "
                "key rotation."
            )
        logger.warning("release signer change accepted platform=%s code=%s %s -> %s",
                       platform, version_code, previous_signer, signer)
    # Flat key — object stores treat '/' fine but the local backend and
    # key-from-URL recovery both assume flat names.
    key = f"release-{platform}-{version_code}-{uuid.uuid4().hex[:8]}.apk"
    try:
        url = await get_storage().save(
            data, key, APK_CONTENT_TYPE,
            metadata={"sha256": digest, "file_size_bytes": str(len(data)),
                      "signer_sha256": signer},
        )
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
    return {"url": proxy_url, "key": key, "size_bytes": len(data),
            "signer_sha256": signer}


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
