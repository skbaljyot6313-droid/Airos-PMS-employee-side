"""Media uploads — storage backend selected via STORAGE_BACKEND (local dir
or S3-compatible object store). Local objects are served from the
`/uploads` static mount; S3 objects get their public/CDN URL back.

Returns the stored URL so the frontend can render/store it directly.
"""

from fastapi import APIRouter, Depends, Request, UploadFile, status
from fastapi import File

from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.core.rate_limit import rate_limit
from app.core.storage import (
    ALLOWED_CONTENT_TYPES,
    MAX_BYTES,
    get_storage,
    new_object_key,
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
    # Local backend returns a relative /uploads/<key> path — the frontend's
    # mediaUrl() resolves it against the API origin. Works identically
    # direct, or behind nginx (absolute proxy-derived URLs lose the port).
    return {"url": url, "key": key}
