"""
Object storage — a single S3-compatible backend.

S3Storage points at Supabase Storage's S3 endpoint (S3_ENDPOINT_URL),
which keeps every upload durable across container redeploys. There is
deliberately NO local-disk backend: container filesystems are ephemeral
and have already lost uploads in production.

Downloads are served through GET /api/v1/media/file/{key} — the API
origin streams the object server-side, so devices never need to reach
the storage host at all.
"""

import asyncio
import uuid
from pathlib import Path
from typing import AsyncIterator, Callable
from urllib.parse import unquote, urlparse

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("app.storage")

MAX_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "image/heif": ".heic",
}

# Stored objects are immutable uuid-keyed blobs — long-cacheable.
MEDIA_CHUNK = 256 * 1024

_EXT_CT = {
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".apk": "application/vnd.android.package-archive",
}

# (stream_factory, content_type, content_length) — the factory is called
# once by the route to produce the body iterator, so connections stay
# open exactly as long as the response streams.
OpenedObject = tuple[
    Callable[[], AsyncIterator[bytes]], str | None, int | None
]


class StorageBackend:
    async def save(self, data: bytes, key: str, content_type: str) -> str:
        """Persist `data` at `key`; return the URL the client should store."""
        raise NotImplementedError

    async def delete(self, key: str) -> None:
        """Delete a previously stored object; missing objects are ignored."""
        raise NotImplementedError

    async def open(self, key: str) -> OpenedObject | None:
        """Open a stored object for streaming — None when absent."""
        raise NotImplementedError


class S3Storage(StorageBackend):
    def __init__(self):
        import boto3  # deferred — only needed when this backend is selected

        if not (
            settings.S3_BUCKET
            and settings.S3_ACCESS_KEY
            and settings.S3_SECRET_KEY
        ):
            raise RuntimeError(
                "object storage requires S3_BUCKET, S3_ACCESS_KEY and "
                "S3_SECRET_KEY (Supabase Storage S3 credentials)"
            )
        self.bucket = settings.S3_BUCKET
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL or None,
            region_name=settings.S3_REGION,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
        )

    async def save(self, data: bytes, key: str, content_type: str) -> str:
        await asyncio.to_thread(
            self.client.put_object,
            Bucket=self.bucket, Key=key, Body=data,
            ContentType=content_type,
        )
        if settings.S3_PUBLIC_BASE_URL:
            return f"{settings.S3_PUBLIC_BASE_URL.rstrip('/')}/{key}"
        if settings.S3_ENDPOINT_URL:
            base = settings.S3_ENDPOINT_URL.rstrip("/")
            return f"{base}/{self.bucket}/{key}"
        return f"https://{self.bucket}.s3.{settings.S3_REGION}.amazonaws.com/{key}"

    async def delete(self, key: str) -> None:
        if key:
            await asyncio.to_thread(
                self.client.delete_object, Bucket=self.bucket, Key=key
            )

    async def open(self, key: str) -> OpenedObject | None:
        def _get():
            try:
                return self.client.get_object(Bucket=self.bucket, Key=key)
            except Exception as exc:
                # Only a genuine object miss maps to None — bucket-level and
                # transport failures are misconfig and must surface as 502,
                # not fake 404s.
                err = (getattr(exc, "response", None) or {}).get("Error", {})
                if err.get("Code") == "NoSuchKey":
                    return None
                raise

        res = await asyncio.to_thread(_get)
        if res is None:
            return None
        body = res["Body"]

        async def stream() -> AsyncIterator[bytes]:
            while True:
                chunk = await asyncio.to_thread(body.read, MEDIA_CHUNK)
                if not chunk:
                    break
                yield chunk

        return (
            stream,
            res.get("ContentType"),
            res.get("ContentLength"),
        )


_backend: StorageBackend | None = None


def get_storage() -> StorageBackend:
    """The single storage backend — Supabase's S3-compatible object store.
    Missing credentials are a hard failure: there is no local-disk
    fallback."""
    global _backend
    if _backend is None:
        _backend = S3Storage()
        logger.info("storage backend: s3 bucket=%s", _backend.bucket)
    return _backend


def new_object_key(filename: str | None, content_type: str) -> str:
    """Collision-free object key — uuid + extension from the VALIDATED
    content type (never trust the client-supplied filename)."""
    ext = ALLOWED_CONTENT_TYPES.get(content_type, ".jpg")
    return f"{uuid.uuid4().hex}{ext}"


def storage_key_from_url(url: str) -> str | None:
    """Recover the flat object key generated by `new_object_key` from a URL
    produced by the storage backend. Unknown/external URLs return None
    so a task-bound image can never request arbitrary storage deletion."""
    if not url:
        return None
    parsed = urlparse(url)
    path = unquote(parsed.path)
    candidates: list[str] = []
    # Proxy/legacy path shapes are host-agnostic — a stored absolute URL on
    # this API's own domain still maps back to the same flat object key.
    for prefix in ("/uploads/", "/api/v1/media/file/", "/media/file/"):
        if path.startswith(prefix):
            candidates.append(path.removeprefix(prefix))
    supabase_host = urlparse(settings.SUPABASE_URL).netloc
    if parsed.netloc == supabase_host:
        for marker in (
            f"/object/public/{settings.SUPABASE_STORAGE_BUCKET}/",
            f"/object/{settings.SUPABASE_STORAGE_BUCKET}/",
        ):
            if marker in path:
                candidates.append(path.split(marker, 1)[1])
    if settings.S3_BUCKET:
        if settings.S3_PUBLIC_BASE_URL and url.startswith(settings.S3_PUBLIC_BASE_URL.rstrip("/") + "/"):
            candidates.append(url.rsplit("/", 1)[-1])
        if settings.S3_ENDPOINT_URL and url.startswith(
            f"{settings.S3_ENDPOINT_URL.rstrip('/')}/{settings.S3_BUCKET}/"
        ):
            candidates.append(url.rsplit("/", 1)[-1])
        if parsed.netloc == f"{settings.S3_BUCKET}.s3.{settings.S3_REGION}.amazonaws.com":
            candidates.append(path.lstrip("/"))

    for candidate in candidates:
        candidate = unquote(candidate).strip("/")
        if candidate and Path(candidate).name == candidate:
            return candidate
    return None


def proxy_media_url(url: str | None) -> str | None:
    """Rewrite a stored storage URL to the same-origin proxy path.

    Devices only ever fetch media from the API origin — the object store
    (supabase.co / S3 endpoints) may be unreachable or DNS-blocked on
    field networks, while the Railway API domain is already proven
    reachable. Unknown/external URLs pass through untouched; relative
    /media/file/ paths stay as-is (already proxied).
    """
    if not url:
        return url
    if "/media/file/" in url:
        return url
    key = storage_key_from_url(url)
    return f"/api/v1/media/file/{key}" if key else url
