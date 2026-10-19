"""pw= (pool wait) in the access-log line — emitted at the END of the
line after company= so existing stage-field parsers keep working."""
import logging

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


async def test_access_log_line_contains_pw(caplog):
    """A request through AccessLogMiddleware logs ... company=<id>
    pw=<int>; every request carries a metrics context (db=0 rows too)."""
    with caplog.at_level(logging.INFO, logger="app.access"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as c:
            r = await c.get("/api/v1/zones")  # 401 — still logged
    assert r.status_code == 401
    lines = [rec.getMessage() for rec in caplog.records
             if "method=GET" in rec.getMessage()]
    assert lines, "no access-log line captured"
    line = lines[0]
    # pw= is present AND last — appended after company= so parsers that
    # stopped at the stage tuple keep working.
    assert " pw=" in line
    assert line.rstrip().split()[-1].startswith("pw=")
    assert line.index("pw=") > line.index("company=")


async def test_access_log_line_skips_health(caplog):
    """/health stays out of the access log — the change must not
    resurrect it."""
    with caplog.at_level(logging.INFO, logger="app.access"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as c:
            r = await c.get("/health")
    assert r.status_code == 200
    assert not any(
        "/health" in rec.getMessage()
        for rec in caplog.records if rec.name == "app.access"
    )
