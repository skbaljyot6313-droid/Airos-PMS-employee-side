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
