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
    assert body["download_url"].endswith(".apk")
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
