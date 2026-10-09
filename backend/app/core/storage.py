"""
Object storage for media uploads.

Two backends, one interface:

    LocalStorage — writes under UPLOAD_DIR (bind-mount a volume in Docker).
                   Dev/staging default; fine behind the /uploads mount.
    S3Storage    — S3-compatible object store (AWS S3, Supabase Storage,
                   MinIO). Production target: uploads survive container
                   replacement and are served from the bucket/CDN URL.

Selection is env-driven (STORAGE_BACKEND). The public URL for a stored
object comes back from save() — the caller never builds paths itself.
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


class LocalStorage(StorageBackend):
    def __init__(self, base_dir: str | Path | None = None):
        self.dir = Path(base_dir or settings.UPLOAD_DIR)
        if not self.dir.is_absolute():
            self.dir = Path(__file__).resolve().parents[2] / self.dir

    async def save(self, data: bytes, key: str, content_type: str) -> str:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / key
        # write off the event loop — uploads can be several MB
        await asyncio.to_thread(path.write_bytes, data)
        return f"/uploads/{key}"  # relative — frontend resolves via mediaUrl()

    async def delete(self, key: str) -> None:
        if not key or Path(key).name != key:
            return
        await asyncio.to_thread((self.dir / key).unlink, missing_ok=True)

    async def open(self, key: str) -> OpenedObject | None:
        path = self.dir / key
        if not await asyncio.to_thread(path.is_file):
            return None
        size = (await asyncio.to_thread(path.stat)).st_size

        async def stream() -> AsyncIterator[bytes]:
            def _read(fh):
                return fh.read(MEDIA_CHUNK)

            with open(path, "rb") as fh:
                while True:
                    chunk = await asyncio.to_thread(_read, fh)
                    if not chunk:
                        break
                    yield chunk

        return stream, _EXT_CT.get(path.suffix.lower()), size


class S3Storage(StorageBackend):
    def __init__(self):
        import boto3  # deferred — only needed when this backend is selected

        if not settings.S3_BUCKET:
            raise RuntimeError("STORAGE_BACKEND=s3 requires S3_BUCKET")
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


class SupabaseStorage(StorageBackend):
    """Supabase Storage via its REST API — needs only SUPABASE_SECRET_KEY,
    which deployments already carry for the database. Objects land in a
    public bucket so the returned URL renders without signing."""

    def __init__(self):
        if not settings.SUPABASE_SECRET_KEY:
            raise RuntimeError("supabase storage requires SUPABASE_SECRET_KEY")
        self.base = f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1"
        self.bucket = settings.SUPABASE_STORAGE_BUCKET
        self._bucket_ready = False

    @property
    def _auth(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.SUPABASE_SECRET_KEY}",
            "apikey": settings.SUPABASE_SECRET_KEY,
        }

    async def _ensure_bucket(self, client) -> None:
        """Create the public bucket once — a missing bucket otherwise turns
        every upload into an opaque storage error."""
        if self._bucket_ready:
            return
        res = await client.post(
            f"{self.base}/bucket",
            json={
                "id": self.bucket,
                "name": self.bucket,
                "public": True,
            },
            headers=self._auth,
        )
        # 400/409 with "already exists"/Duplicate = bucket present — fine
        if res.status_code not in (200, 201) and res.status_code not in (400, 409):
            res.raise_for_status()
        self._bucket_ready = True

    async def save(self, data: bytes, key: str, content_type: str) -> str:
        import httpx  # deferred — only needed when this backend is selected

        async with httpx.AsyncClient(timeout=30) as client:
            await self._ensure_bucket(client)
            res = await client.post(
                f"{self.base}/object/{self.bucket}/{key}",
                content=data,
                headers={**self._auth, "Content-Type": content_type},
            )
            res.raise_for_status()
        return f"{self.base}/object/public/{self.bucket}/{key}"

    async def delete(self, key: str) -> None:
        if not key:
            return
        import httpx  # deferred — only needed when this backend is selected

        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.delete(
                f"{self.base}/object/{self.bucket}/{key}",
                headers=self._auth,
            )
            if res.status_code != 404:
                res.raise_for_status()

    async def open(self, key: str) -> OpenedObject | None:
        """HEAD for existence/metadata, then a streaming GET owned by the
        returned factory — the private object endpoint serves the bytes,
        so the device never talks to supabase.co directly."""
        import httpx  # deferred — only needed when this backend is selected

        url = f"{self.base}/object/{self.bucket}/{key}"
        auth: dict[str, str] | None = self._auth
        async with httpx.AsyncClient(timeout=30) as client:
            head = await client.head(url, headers=self._auth)
            if head.status_code == 404:
                # Bucket is public — fall back to the unauthenticated URL
                # in case the private object endpoint differs (e.g. the
                # deployment's service key scopes oddly).
                public = (
                    f"{self.base}/object/public/{self.bucket}/{key}"
                )
                head = await client.head(public)
                if head.status_code == 404:
                    logger.info(
                        "media object absent in bucket %s: %s",
                        self.bucket, key,
                    )
                    return None
                url, auth = public, {}
            head.raise_for_status()
            content_type = head.headers.get("Content-Type")
            length = head.headers.get("Content-Length")

        async def stream() -> AsyncIterator[bytes]:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream(
                    "GET", url, headers=auth or {}
                ) as res:
                    res.raise_for_status()
                    async for chunk in res.aiter_bytes(MEDIA_CHUNK):
                        yield chunk

        return (
            stream,
            content_type,
            int(length) if length and length.isdigit() else None,
        )


def _s3_ready() -> bool:
    return bool(
        settings.S3_BUCKET and settings.S3_ACCESS_KEY and settings.S3_SECRET_KEY
    )


_backend: StorageBackend | None = None


def get_storage() -> StorageBackend:
    """Resolve the effective backend. `auto` prefers durable object storage
    (S3 creds, then the Supabase service key) and only falls back to the
    local filesystem when nothing persistent is configured — writing to a
    container's disk silently loses every upload on the next deploy."""
    global _backend
    if _backend is None:
        mode = settings.STORAGE_BACKEND.lower()
        if mode == "s3" or (mode == "auto" and _s3_ready()):
            _backend = S3Storage()
        elif mode == "supabase" or (
            mode == "auto" and settings.SUPABASE_SECRET_KEY
        ):
            _backend = SupabaseStorage()
        else:
            _backend = LocalStorage()
        logger.info("storage backend: %s", type(_backend).__name__)
    return _backend


def new_object_key(filename: str | None, content_type: str) -> str:
    """Collision-free object key — uuid + extension from the VALIDATED
    content type (never trust the client-supplied filename)."""
    ext = ALLOWED_CONTENT_TYPES.get(content_type, ".jpg")
    return f"{uuid.uuid4().hex}{ext}"


def storage_key_from_url(url: str) -> str | None:
    """Recover the flat object key generated by `new_object_key` from a URL
    produced by the active storage backend. Unknown/external URLs return None
    so a task-bound image can never request arbitrary storage deletion."""
    if not url:
        return None
    parsed = urlparse(url)
    path = unquote(parsed.path)
    candidates: list[str] = []
    # Proxy/local path shapes are host-agnostic — a stored absolute URL on
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
