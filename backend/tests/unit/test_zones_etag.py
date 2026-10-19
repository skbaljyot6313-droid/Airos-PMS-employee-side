"""GET /zones ETag — conditional-GET 304 short-circuit."""

from fastapi import Request, Response

from app.api.v1.resources import list_zones


def _req(etag=None):
    headers = (
        [(b"if-none-match", etag.encode())] if etag else []
    )
    return Request({"type": "http", "headers": headers})


async def test_zones_emits_stable_weak_etag(session, seed):
    out = await list_zones(_req(), Response(), seed["emp_user"], session)
    etag = Response()
    out = await list_zones(_req(), etag, seed["emp_user"], session)
    first = etag.headers["etag"]
    assert first.startswith('W/"')

    etag2 = Response()
    await list_zones(_req(), etag2, seed["emp_user"], session)
    assert etag2.headers["etag"] == first  # same content → same tag


async def test_if_none_match_returns_304(session, seed):
    resp = Response()
    await list_zones(_req(), resp, seed["emp_user"], session)
    out = await list_zones(
        _req(resp.headers["etag"]), Response(), seed["emp_user"], session
    )
    assert out.status_code == 304


async def test_content_change_bumps_etag(session, seed):
    resp = Response()
    await list_zones(_req(), resp, seed["emp_user"], session)
    tag_before = resp.headers["etag"]

    from app.models.structure import Zone
    session.add(Zone(
        property_id=seed["prop"].id, name="New", code="N",
        zone_type="stay",
    ))
    await session.commit()

    resp2 = Response()
    await list_zones(_req(), resp2, seed["emp_user"], session)
    assert resp2.headers["etag"] != tag_before


async def test_etag_differs_per_tenant(session, seed, make_tenant):
    """Tenant-scoped payloads must produce distinct tags — a shared tag
    would leak 'unchanged' across company boundaries."""
    from app.models.structure import Zone
    t2 = await make_tenant("B")
    session.add(Zone(property_id=t2["prop"].id, name="Only-B", code="OB",
                     zone_type="stay"))
    await session.commit()

    r1, r2 = Response(), Response()
    await list_zones(_req(), r1, seed["emp_user"], session)
    await list_zones(_req(), r2, t2["user"], session)
    assert r1.headers["etag"] != r2.headers["etag"]


async def test_cache_headers_private_and_vary(session, seed):
    resp = Response()
    await list_zones(_req(), resp, seed["emp_user"], session)
    assert resp.headers["cache-control"] == "private, no-cache"
    assert resp.headers["vary"] == "Authorization"

    # 304 must also carry the validator headers
    out = await list_zones(
        _req(resp.headers["etag"]), Response(), seed["emp_user"], session
    )
    assert out.status_code == 304
    assert out.headers["etag"] == resp.headers["etag"]
    assert out.headers["cache-control"] == "private, no-cache"


async def test_auth_runs_before_304():
    """Route level: an unauthenticated conditional GET must be 401 —
    never 304, even with a forged If-None-Match."""
    from httpx import ASGITransport, AsyncClient
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t"
    ) as c:
        r = await c.get(
            "/api/v1/zones", headers={"If-None-Match": 'W/"forged"'}
        )
    assert r.status_code == 401
