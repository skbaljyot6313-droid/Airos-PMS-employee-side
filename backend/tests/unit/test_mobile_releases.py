"""Mobile release registry — public version check + release management.

GET /mobile/version is unauthenticated (an outdated app must still learn it
needs an update). POST /mobile/releases* is gated by the
RELEASE_MANAGEMENT_API_KEY service bearer — employee JWTs are rejected.

Safety under test:
  * version_code must strictly increase (409 otherwise)
  * publishing flips is_active atomically; old rows survive for rollback
  * /activate re-points the active release (rollback path)
  * unconfigured service key fails closed with 503
"""

import httpx
import pytest

from app.core.config import settings
from app.core.database import get_db
from app.main import app

VERSION_URL = "/api/v1/mobile/version"
RELEASES_URL = "/api/v1/mobile/releases"
KEY = "test-release-key"


@pytest.fixture
def service_key(monkeypatch):
    monkeypatch.setattr(settings, "RELEASE_MANAGEMENT_API_KEY", KEY)


@pytest.fixture
async def api(session):
    async def _db():
        yield session

    app.dependency_overrides[get_db] = _db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        yield client
    app.dependency_overrides.pop(get_db, None)


def _auth(key: str = KEY) -> dict:
    return {"Authorization": f"Bearer {key}"}


def _release(version="1.0.1", code=2, url="https://expo.dev/artifacts/eas/x.apk", **over):
    body = {
        "platform": "android",
        "version": version,
        "version_code": code,
        "minimum_version": "1.0.0",
        "minimum_version_code": 1,
        "download_url": url,
        "release_notes": "Bug fixes.",
        "force_update": False,
    }
    body.update(over)
    return body


async def test_version_is_public_and_404s_when_empty(api):
    res = await api.get(VERSION_URL)
    assert res.status_code == 404


async def test_publish_then_public_version(api, service_key):
    res = await api.post(RELEASES_URL, json=_release(), headers=_auth())
    assert res.status_code == 201
    assert res.json()["is_active"] is True

    pub = await api.get(VERSION_URL)
    assert pub.status_code == 200
    body = pub.json()
    assert body["latest_version"] == "1.0.1"
    assert body["latest_version_code"] == 2
    # Devices download through the API origin — never the stored host URL.
    assert body["download_url"].startswith("/api/v1/mobile/apk")
    assert body["force_update"] is False
    # Public payload carries release metadata only.
    assert set(body) == {
        "platform", "latest_version", "latest_version_code",
        "minimum_version", "minimum_version_code", "download_url",
        "release_notes", "force_update",
    }


async def test_version_code_must_increase(api, service_key):
    assert (await api.post(RELEASES_URL, json=_release(), headers=_auth())).status_code == 201
    same = await api.post(RELEASES_URL, json=_release(version="1.0.2", code=2), headers=_auth())
    assert same.status_code == 409
    lower = await api.post(RELEASES_URL, json=_release(version="1.0.0", code=1), headers=_auth())
    assert lower.status_code == 409


async def test_new_release_replaces_active(api, service_key):
    await api.post(RELEASES_URL, json=_release(), headers=_auth())
    res = await api.post(
        RELEASES_URL, json=_release(version="1.0.2", code=3), headers=_auth()
    )
    assert res.status_code == 201
    pub = await api.get(VERSION_URL)
    assert pub.json()["latest_version"] == "1.0.2"
    assert pub.json()["latest_version_code"] == 3


async def test_rollback_reactivates_previous_release(api, service_key):
    first = (await api.post(RELEASES_URL, json=_release(), headers=_auth())).json()
    await api.post(RELEASES_URL, json=_release(version="1.0.2", code=3), headers=_auth())

    res = await api.post(
        f"{RELEASES_URL}/{first['id']}/activate?platform=android", headers=_auth()
    )
    assert res.status_code == 200
    pub = await api.get(VERSION_URL)
    assert pub.json()["latest_version"] == "1.0.1"
    assert pub.json()["latest_version_code"] == 2


async def test_publish_requires_service_key(api, service_key):
    assert (await api.post(RELEASES_URL, json=_release())).status_code == 401
    wrong = await api.post(RELEASES_URL, json=_release(), headers=_auth("nope"))
    assert wrong.status_code == 401


async def test_publish_fails_closed_without_key(api, monkeypatch):
    monkeypatch.setattr(settings, "RELEASE_MANAGEMENT_API_KEY", None)
    res = await api.post(RELEASES_URL, json=_release(), headers=_auth())
    assert res.status_code == 503


async def test_non_https_url_rejected(api, service_key):
    res = await api.post(
        RELEASES_URL,
        json=_release(url="http://insecure.example/app.apk"),
        headers=_auth(),
    )
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# PATCH /mobile/releases/{id} — repoint download_url / notes in place
# ---------------------------------------------------------------------------


async def test_patch_repoints_download_url(api, service_key):
    rel = (
        await api.post(RELEASES_URL, json=_release(), headers=_auth())
    ).json()
    res = await api.patch(
        f"{RELEASES_URL}/{rel['id']}",
        json={"download_url": "https://storage.test/release.apk"},
        headers=_auth(),
    )
    assert res.status_code == 200
    pub = await api.get(VERSION_URL)
    assert pub.json()["download_url"].startswith("/api/v1/mobile/apk")


async def test_patch_rejects_non_https(api, service_key):
    rel = (
        await api.post(RELEASES_URL, json=_release(), headers=_auth())
    ).json()
    res = await api.patch(
        f"{RELEASES_URL}/{rel['id']}",
        json={"download_url": "http://insecure/x.apk"},
        headers=_auth(),
    )
    assert res.status_code == 422


async def test_patch_requires_service_key(api, service_key):
    rel = (
        await api.post(RELEASES_URL, json=_release(), headers=_auth())
    ).json()
    res = await api.patch(
        f"{RELEASES_URL}/{rel['id']}",
        json={"download_url": "https://storage.test/x.apk"},
    )
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# POST /mobile/releases/apk — self-hosted release binaries
# ---------------------------------------------------------------------------


class _FakeStorage:
    def __init__(self):
        self.saved: dict[str, bytes] = {}

    async def save(self, data: bytes, key: str, content_type: str) -> str:
        self.saved[key] = data
        return f"https://storage.test/{key}"

    async def delete(self, key: str) -> None:
        self.saved.pop(key, None)

    async def open(self, key: str):
        data = self.saved.get(key)
        if data is None:
            return None

        async def stream():
            yield data

        return stream, "application/vnd.android.package-archive", len(data)


async def test_apk_upload_stores_binary(api, service_key, monkeypatch):
    fake = _FakeStorage()
    monkeypatch.setattr("app.api.v1.mobile.get_storage", lambda: fake)
    res = await api.post(
        f"{RELEASES_URL}/apk?platform=android&version_code=3",
        files={
            "file": (
                "app.apk",
                b"PK\x03\x04fake-apk-bytes",
                "application/vnd.android.package-archive",
            )
        },
        headers=_auth(),
    )
    assert res.status_code == 201
    body = res.json()
    assert body["url"].endswith(".apk")
    assert "release-android-3-" in body["key"]
    assert fake.saved[body["key"]].startswith(b"PK")


async def test_apk_upload_rejects_non_apk(api, service_key):
    res = await api.post(
        f"{RELEASES_URL}/apk",
        files={"file": ("x.apk", b"not-an-apk", "application/octet-stream")},
        headers=_auth(),
    )
    assert res.status_code == 422


async def test_apk_upload_requires_service_key(api, service_key):
    res = await api.post(
        f"{RELEASES_URL}/apk?version_code=3",
        files={"file": ("x.apk", b"PK\x03\x04x", "application/octet-stream")},
    )
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# GET /mobile/apk — device-facing binary proxy through the API origin
# ---------------------------------------------------------------------------


async def test_apk_proxy_404s_without_release(api):
    res = await api.get("/api/v1/mobile/apk")
    assert res.status_code == 404


async def test_apk_proxy_streams_stored_binary(api, service_key, monkeypatch):
    fake = _FakeStorage()
    monkeypatch.setattr("app.api.v1.mobile.get_storage", lambda: fake)
    monkeypatch.setattr(settings, "S3_BUCKET", "b")
    monkeypatch.setattr(
        settings, "S3_PUBLIC_BASE_URL", "https://storage.test"
    )
    await api.post(
        RELEASES_URL,
        json=_release(url="https://storage.test/release-android-2-deadbeef.apk"),
        headers=_auth(),
    )
    fake.saved["release-android-2-deadbeef.apk"] = b"PK\x03\x04apk-bytes"

    res = await api.get("/api/v1/mobile/apk")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith(
        "application/vnd.android.package-archive"
    )
    assert res.headers["content-length"] == str(len(b"PK\x03\x04apk-bytes"))
    assert "airos-android-1.0.1.apk" in res.headers["content-disposition"]
    assert res.content == b"PK\x03\x04apk-bytes"


async def test_apk_proxy_404s_when_binary_missing(api, service_key, monkeypatch):
    fake = _FakeStorage()
    monkeypatch.setattr("app.api.v1.mobile.get_storage", lambda: fake)
    monkeypatch.setattr(settings, "S3_BUCKET", "b")
    monkeypatch.setattr(
        settings, "S3_PUBLIC_BASE_URL", "https://storage.test"
    )
    await api.post(
        RELEASES_URL,
        json=_release(url="https://storage.test/release-android-2-deadbeef.apk"),
        headers=_auth(),
    )
    res = await api.get("/api/v1/mobile/apk")
    assert res.status_code == 404


async def test_apk_proxy_fetches_external_url(api, service_key, monkeypatch):
    """Externally hosted artifacts (expo.dev) are fetched server-side —
    the device still only talks to this origin."""
    await api.post(RELEASES_URL, json=_release(), headers=_auth())
    apk = b"PK\x03\x04external-apk"

    class _Resp:
        def __init__(self, status=200, headers=None):
            self.status_code = status
            self.headers = headers or {}

        async def aiter_bytes(self, n):
            yield apk

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("upstream")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _Client:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def head(self, url):
            return _Resp(200, {"Content-Length": str(len(apk))})

        def stream(self, method, url):
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    res = await api.get("/api/v1/mobile/apk")
    assert res.status_code == 200
    assert res.content == apk


async def test_apk_proxy_502s_when_external_unreachable(
    api, service_key, monkeypatch
):
    await api.post(RELEASES_URL, json=_release(), headers=_auth())

    class _Client:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def head(self, url):
            raise httpx.ConnectError("no route")

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    res = await api.get("/api/v1/mobile/apk")
    assert res.status_code == 502
    assert res.json()["error"]["code"] == "STORAGE_UNAVAILABLE"
