"""Media upload + download proxy over the S3-compatible object store
(Supabase Storage's S3 endpoint — the only backend; nothing is written
to the container filesystem).

Upload returns a same-origin /media/file/<key> path; GET on that path
streams the object server-side, so devices only ever talk to the API
origin regardless of where the bytes actually live.
"""

import re

from fastapi import APIRouter, Depends, Request, UploadFile, status
from fastapi import File
from fastapi.responses import StreamingResponse

from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.core.rate_limit import rate_limit
from app.core.storage import (
    ALLOWED_CONTENT_TYPES,
    MAX_BYTES,
    get_storage,
    new_object_key,
    proxy_media_url,
)
from app.dependencies.auth import get_current_user
from app.models.user import User

router = APIRouter(tags=["media"])

logger = get_logger("app.media")


class InvalidUpload(AppError):
    status_code = 422
    code = "INVALID_UPLOAD"


class StorageUnavailable(AppError):
    status_code = 502
    code = "STORAGE_UNAVAILABLE"


class MediaNotFound(AppError):
    status_code = 404
    code = "MEDIA_NOT_FOUND"
    message = "Media not found."


# new_object_key output shape, plus self-hosted release binaries
# (release-<platform>-<code>-<hex8>.apk) — a strict whitelist so
# traversal and enumeration can't reach the storage layer at all.
_OBJECT_KEY_RE = re.compile(
    r"^([0-9a-f]{32}\.[a-z0-9]{2,5}|release-[a-z0-9]+-[0-9]+-[0-9a-f]{8}\.apk)$"
)


def _matches_image_signature(data: bytes, content_type: str) -> bool:
    if content_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


async def _read_bounded(file: UploadFile) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > MAX_BYTES:
            raise InvalidUpload("File exceeds the 10 MB limit.", field="photos")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post(
    "/media/uploads",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("upload", limit=30, window_seconds=60))],
)
async def upload_media(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise InvalidUpload("Only JPEG/PNG/WebP images are allowed.", field="photos")
    data = await _read_bounded(file)
    if not data:
        raise InvalidUpload("Empty file.", field="photos")
    if not _matches_image_signature(data, file.content_type):
        raise InvalidUpload("File content does not match its image type.", field="photos")

    key = new_object_key(file.filename, file.content_type)
    try:
        url = await get_storage().save(data, key, file.content_type)
    except AppError:
        raise
    except Exception as exc:
        # Misconfigured/unreachable object store (bad credentials, missing
        # bucket, offline disk) must surface as a clean 502 — not an
        # unhandled 500 that strips CORS headers off the response.
        logger.error("storage save failed for key %s: %s", key, exc)
        raise StorageUnavailable(
            "Image storage is unavailable — check the storage backend configuration."
        ) from exc
    # Return the same-origin proxy path, not the raw storage URL — the
    # object-store host may be unreachable on the device's network, while
    # the API origin is already proven. Serializers re-emit it verbatim.
    return {"url": proxy_media_url(url), "key": key}


@router.get(
    "/media/file/{key}",
    dependencies=[Depends(rate_limit("media_fetch", limit=240, window_seconds=60))],
)
async def get_media_file(key: str):
    """Stream a stored object through the API origin.

    Devices fetch every download from this host only — the object-store
    public host (supabase.co / CDN) is unreachable on some field
    networks while the API domain is already proven. Public by design,
    same as the public URLs it replaces: keys are unguessable uuid4
    names and <img> tags can't attach a JWT. Traversal can't pass the
    key whitelist, so only our own objects are ever served.
    """
    if not _OBJECT_KEY_RE.fullmatch(key):
        raise MediaNotFound()
    try:
        opened = await get_storage().open(key)
    except Exception as exc:
        logger.error(
            "media fetch failed",
            extra={"storage_key": key, "error": str(exc)},
        )
        raise StorageUnavailable("Media storage is unavailable.") from exc
    if opened is None:
        raise MediaNotFound()
    stream, content_type, length = opened
    headers = {
        # objects are immutable uuid-keyed blobs
        "Cache-Control": "public, max-age=31536000, immutable",
        "X-Content-Type-Options": "nosniff",
        # already-compressed formats — bypass GZipMiddleware so
        # Content-Length survives for client progress display
        "Content-Encoding": "identity",
    }
    if length is not None:
        headers["Content-Length"] = str(length)
    return StreamingResponse(
        stream(),
        media_type=content_type or "application/octet-stream",
        headers=headers,
    )
