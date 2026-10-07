"""Live smoke: POST a fix -> GET /admin/live-locations -> expiry exclusion.

REDIS_URL is unset in dev .env, so Redis is faked in-process at the
app.core.redis.get_redis seam (same trick as the unit tests); Postgres
and JWT auth are REAL — the employee POST uses a minted token for an
actual employee-linked user row.

Run: .venv/Scripts/python.exe scripts/smoke_admin_locations.py
"""

import asyncio
import time

import fakeredis.aioredis
import httpx
import uvicorn
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# --- seam patches BEFORE the app touches them -------------------------------
from app.core.config import settings

settings.LOCATION_SERVICE_API_KEY = "smoke-service-key"

import fakeredis.aioredis as _f
from app.core import redis as redis_core

_fake = fakeredis.aioredis.FakeRedis(decode_responses=True)


async def _get_redis():
    return _fake


redis_core.get_redis = _get_redis

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app

# Supabase transaction pooler keeps named prepared statements on shared
# server connections — asyncpg needs statement_cache_size=0 (the real
# asyncpg kwarg) to use the unnamed statement and avoid collisions.
_engine = create_async_engine(
    settings.database_url,
    connect_args={"statement_cache_size": 0},
)
_Session = async_sessionmaker(bind=_engine, expire_on_commit=False)


async def _db():
    async with _Session() as s:
        yield s


app.dependency_overrides[get_db] = _db

BASE = "http://127.0.0.1:8931"
PORT = 8931


async def _find_employee_user():
    async with _Session() as s:
        row = (
            await s.execute(
                text(
                    "SELECT id, company_id, role, employee_id FROM users "
                    "WHERE employee_id IS NOT NULL AND is_active IS TRUE "
                    "AND role IN ('EMPLOYEE','SUPER_ADMIN','employee','super_admin') LIMIT 1"
                )
            )
        ).first()
    return row


async def main() -> int:
    row = await _find_employee_user()
    if row is None:
        print("FAIL: no active employee-linked user in DB to mint a JWT for")
        return 1
    user_id, company_id, role, employee_id = row
    jwt = create_access_token(
        user_id=str(user_id), company_id=str(company_id), role=str(role)
    )
    print(f"employee user {user_id} -> employee_id {employee_id}")

    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    )
    task = asyncio.create_task(server.serve())
    for _ in range(50):
        await asyncio.sleep(0.1)
        if server.started:
            break
    if not server.started:
        print("FAIL: server did not start")
        return 1

    ok = True

    def check(name, cond, extra=""):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'}: {name} {extra}")

    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        r = await c.get("/api/v1/admin/live-locations")
        check("admin GET no auth -> 401", r.status_code == 401)

        r = await c.get(
            "/api/v1/admin/live-locations",
            headers={"Authorization": "Bearer wrong"},
        )
        check("admin GET wrong key -> 401", r.status_code == 401)

        r = await c.get(
            "/api/v1/admin/live-locations",
            headers={"Authorization": f"Bearer {jwt}"},
        )
        check("admin GET employee JWT -> 401", r.status_code == 401)

        r = await c.post(
            "/api/v1/location/current",
            json={
                "latitude": 12.9716,
                "longitude": 77.5946,
                "accuracy": 8.0,
                "speed": 1.5,
                "timestamp": time.time(),
            },
            headers={"Authorization": f"Bearer {jwt}"},
        )
        check("employee POST fix -> 200", r.status_code == 200, r.text[:200])

        r = await c.get(
            "/api/v1/admin/live-locations",
            headers={"Authorization": "Bearer smoke-service-key"},
        )
        body = r.json()
        check("admin GET valid key -> 200", r.status_code == 200)
        emps = body.get("employees", [])
        check(
            "posted employee appears live",
            any(e["employee_id"] == str(employee_id) and e["is_live"] is True
                for e in emps),
            f"got {emps}",
        )

        # Simulate TTL expiry by back-dating the index score
        await _fake.zadd("mt:location", {str(employee_id): time.time() - 1})
        r = await c.get(
            "/api/v1/admin/live-locations",
            headers={"Authorization": "Bearer smoke-service-key"},
        )
        check(
            "expired member excluded after purge",
            r.json() == {"employees": []},
            r.text[:200],
        )

    server.should_exit = True
    await task
    await _fake.aclose()
    await _engine.dispose()
    print("SMOKE", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
