"""Media download proxy — GET /api/v1/media/file/{key} + proxy URL emission.

Devices only ever fetch media from the API origin; the object-store host
may be unreachable on field networks. Under test:
  * stored objects stream back with their content type + length
  * non-object keys (traversal/enumeration) 404 without touching storage
  * missing objects 404, backend failure 502s with a clean error body
  * serializers rewrite stored URLs to the same-origin proxy path
"""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.core.config import settings
from app.dependencies.auth import get_current_user
from app.main import app
from app.schemas.maintenance import attachment_out
from app.schemas.workspace import completion_image_out

FILE_URL = "/api/v1/media/file"
UPLOAD_URL = "/api/v1/media/uploads"


class _FakeStorage:
    def __init__(self):
        self.saved: dict[str, bytes] = {}
        self.open_fails = False

    async def save(self, data: bytes, key: str, content_type: str) -> str:
        self.saved[key] = data
        return f"https://storage.test/{key}"

    async def delete(self, key: str) -> None:
        self.saved.pop(key, None)

    async def open(self, key: str):
        if self.open_fails:
            raise RuntimeError("storage backend down")
        data = self.saved.get(key)
        if data is None:
            return None

        async def stream():
            yield data

        return stream, "image/jpeg", len(data)


@pytest.fixture
async def api(monkeypatch):
    fake = _FakeStorage()
    monkeypatch.setattr("app.api.v1.media.get_storage", lambda: fake)
    monkeypatch.setattr(settings, "S3_BUCKET", "b")
    monkeypatch.setattr(settings, "S3_PUBLIC_BASE_URL", "https://storage.test")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=uuid.uuid4(), employee_id=None
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        client.fake_storage = fake
        yield client
    app.dependency_overrides.pop(get_current_user, None)


async def test_file_streams_stored_object(api):
    key = uuid.uuid4().hex + ".jpg"
    api.fake_storage.saved[key] = b"\xff\xd8\xffimg"
    res = await api.get(f"{FILE_URL}/{key}")
    assert res.status_code == 200
    assert res.content == b"\xff\xd8\xffimg"
    assert res.headers["content-type"].startswith("image/jpeg")
    assert res.headers["content-length"] == "6"
    assert "immutable" in res.headers["cache-control"]
    assert res.headers["x-content-type-options"] == "nosniff"


async def test_file_is_public_no_auth(api):
    """<img> tags can't attach a JWT — the endpoint is intentionally open."""
    key = uuid.uuid4().hex + ".png"
    api.fake_storage.saved[key] = b"\x89PNG"
    res = await api.get(f"{FILE_URL}/{key}")
    assert res.status_code == 200


async def test_file_404s_missing_object(api):
    res = await api.get(f"{FILE_URL}/{uuid.uuid4().hex}.webp")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "MEDIA_NOT_FOUND"


async def test_file_rejects_non_object_keys(api):
    """Traversal/enumeration attempts 404 before reaching storage."""
    for key in (
        "..%2F..%2Fetc%2Fpasswd",
        "not-a-uuid.jpg",
        "deadbeef.jpg",
        uuid.uuid4().hex + ".exe",
    ):
        res = await api.get(f"{FILE_URL}/{key}")
        assert res.status_code == 404, key


async def test_file_502s_on_storage_failure(api):
    api.fake_storage.open_fails = True
    res = await api.get(f"{FILE_URL}/{uuid.uuid4().hex}.jpg")
    assert res.status_code == 502
    assert res.json()["error"]["code"] == "STORAGE_UNAVAILABLE"


async def test_upload_returns_proxy_path(api):
    res = await api.post(
        UPLOAD_URL,
        files={"file": ("p.jpg", b"\xff\xd8\xffjpeg-bytes", "image/jpeg")},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["url"].startswith("/api/v1/media/file/")
    assert body["url"].endswith(".jpg")
    assert body["key"] in api.fake_storage.saved


def test_attachment_out_rewrites_storage_url(monkeypatch):
    monkeypatch.setattr(settings, "S3_BUCKET", "b")
    monkeypatch.setattr(settings, "S3_PUBLIC_BASE_URL", "https://storage.test")
    key = uuid.uuid4().hex + ".jpg"
    a = SimpleNamespace(
        id=uuid.uuid4(), url=f"https://storage.test/{key}",
        file_name="x.jpg", mime_type="image/jpeg", size_bytes=10,
        kind="issue", attempt=1, uploaded_by_name="W",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert attachment_out(a)["url"] == f"/api/v1/media/file/{key}"


def test_attachment_out_passes_external_url_through():
    a = SimpleNamespace(
        id=uuid.uuid4(), url="https://cdn.example.com/img.jpg",
        file_name="x.jpg", mime_type="image/jpeg", size_bytes=10,
        kind="issue", attempt=1, uploaded_by_name="W",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert attachment_out(a)["url"] == "https://cdn.example.com/img.jpg"


def test_completion_image_out_rewrites_legacy_relative_path():
    key = uuid.uuid4().hex + ".jpg"
    i = SimpleNamespace(
        id=uuid.uuid4(), task_id=uuid.uuid4(), history_event_id=None,
        submission_id=uuid.uuid4(), url=f"/uploads/{key}",
        file_name="x.jpg", created_by_name="W", created_at=None,
    )
    assert completion_image_out(i)["url"] == f"/api/v1/media/file/{key}"
