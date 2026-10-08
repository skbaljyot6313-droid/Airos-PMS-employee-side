"""Audit smoke: uvicorn + fakeredis, 2 minted-JWT employees, admin read.

Unlike scripts/smoke_admin_locations.py (which hits the real Supabase DB),
this variant keeps Postgres-equivalent auth on in-memory SQLite so the
scenario is fully deterministic and requires no network:

  * fakeredis is patched in at the app.core.redis.get_redis seam
  * get_db is overridden with a SQLite session seeded with TWO
    employee-linked users; JWTs are minted with the real JWT_SECRET_KEY
  * every SQL statement is counted — the POST/admin paths must issue
    ZERO write statements (auth's user-load SELECT is expected)

Checks: both employees POST -> admin GET lists both -> overwriting one
leaves the other untouched -> backdating one zset score excludes it on
the next read -> no SQL writes anywhere in the location paths.

Run: .venv/Scripts/python.exe scripts/smoke_live_location_audit.py
"""

import asyncio
import time

import fakeredis.aioredis
import httpx
import uvicorn
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# --- seam patches BEFORE the app is imported --------------------------------
from app.core.config import settings

SERVICE_KEY = "smoke-service-key"
settings.LOCATION_SERVICE_API_KEY = SERVICE_KEY

from app.core import redis as redis_core

_fake = fakeredis.aioredis.FakeRedis(decode_responses=True)


async def _get_redis():
    return _fake


redis_core.get_redis = _get_redis

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models import Base
from app.models.company import Company
from app.models.employee import Employee
from app.models.property import Property
from app.models.user import User, UserRole

# In-memory DB stands in for Postgres — enough to satisfy JWT user load.
_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
_Session = async_sessionmaker(bind=_engine, expire_on_commit=False)

_write_count = 0


@event.listens_for(_engine.sync_engine, "before_cursor_execute")
def _count_writes(conn, cursor, statement, parameters, context, executemany):
    global _write_count
    if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
        _write_count += 1


async def _db():
    async with _Session() as s:
        yield s


app.dependency_overrides[get_db] = _db

BASE = "http://127.0.0.1:8932"
PORT = 8932


async def _seed():
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with _Session() as s:
        company = Company(
            company_name="Acme", brand_name="Acme", address="1 Main St",
            pin_code="10001", email="ops@acme.test", phone_number="555-0000",
        )
        s.add(company)
        await s.flush()
        prop = Property(
            company_id=company.id, name="HQ", code="HQ1", location="Loc",
            city="City", state="ST", manager_name="M",
            manager_email="m@x.test",
        )
        s.add(prop)
        await s.flush()
        users = []
        for tag in ("emp1", "emp2"):
            emp = Employee(
                company_id=company.id, property_id=prop.id,
                name=f"Worker {tag}", email=f"{tag}@acme.test",
                status="active",
            )
            s.add(emp)
            await s.flush()
            u = User(
                company_id=company.id, property_id=prop.id,
                name=f"{tag} User", email=f"u_{tag}@acme.test",
                username=tag, password_hash="x",
                role=UserRole.EMPLOYEE, employee_id=emp.id,
            )
            s.add(u)
            users.append((u, emp))
        await s.commit()
        return [
            (u.id, emp.id, create_access_token(
                user_id=str(u.id), company_id=str(u.company_id),
                role=u.role.value,
            ))
            for u, emp in users
        ]


def _payload(lat, lon, **over):
    body = {
        "latitude": lat, "longitude": lon, "accuracy": 8.0,
        "timestamp": time.time(),
    }
    body.update(over)
    return body


async def main() -> int:
    global _write_count
    [(u1, e1, jwt1), (u2, e2, jwt2)] = await _seed()
    print(f"employee1={e1} employee2={e2}")

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

    _write_count = 0  # seeding done — anything written now is on the API path

    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        admin = {"Authorization": f"Bearer {SERVICE_KEY}"}

        r = await c.post("/api/v1/location/current", json=_payload(12.0, 77.0),
                         headers={"Authorization": f"Bearer {jwt1}"})
        check("emp1 POST -> 200", r.status_code == 200, r.text[:150])
        r = await c.post("/api/v1/location/current", json=_payload(13.0, 78.0),
                         headers={"Authorization": f"Bearer {jwt2}"})
        check("emp2 POST -> 200", r.status_code == 200, r.text[:150])

        r = await c.get("/api/v1/admin/live-locations", headers=admin)
        check("admin GET -> 200", r.status_code == 200, r.text[:150])
        emps = {e["employee_id"]: e for e in r.json().get("employees", [])}
        check("both employees listed",
              set(emps) == {str(e1), str(e2)}, f"got {sorted(emps)}")

        # Overwrite emp1 — emp2 must be untouched.
        r = await c.post("/api/v1/location/current",
                         json=_payload(12.5, 77.5, speed=2.0),
                         headers={"Authorization": f"Bearer {jwt1}"})
        check("emp1 overwrite POST -> 200", r.status_code == 200)
        r = await c.get("/api/v1/admin/live-locations", headers=admin)
        emps = {e["employee_id"]: e for e in r.json()["employees"]}
        check("emp1 overwritten",
              emps[str(e1)]["latitude"] == 12.5
              and emps[str(e1)]["speed"] == 2.0,
              str(emps.get(str(e1))))
        check("emp2 unchanged",
              emps[str(e2)]["latitude"] == 13.0
              and emps[str(e2)]["longitude"] == 78.0
              and emps[str(e2)]["speed"] is None,
              str(emps.get(str(e2))))

        # Backdate emp1's index score — next read must drop only emp1.
        await _fake.zadd("mt:location", {str(e1): time.time() - 1})
        r = await c.get("/api/v1/admin/live-locations", headers=admin)
        emps = {e["employee_id"]: e for e in r.json()["employees"]}
        check("backdated emp1 excluded, emp2 live",
              set(emps) == {str(e2)}, f"got {sorted(emps)}")

        # Malformed hash must be skipped, not crash nor emit.
        bad_key = "mt:location:emp:bad-member"
        await _fake.hset(bad_key, mapping={"latitude": "garbage", "x": "y"})
        await _fake.zadd("mt:location", {"bad-member": time.time() + 60})
        r = await c.get("/api/v1/admin/live-locations", headers=admin)
        check("malformed hash skipped",
              r.status_code == 200
              and {e["employee_id"] for e in r.json()["employees"]}
              == {str(e2)},
              r.text[:200])

        check("zero SQL writes on location paths", _write_count == 0,
              f"writes={_write_count}")

    server.should_exit = True
    await task
    await _fake.aclose()
    await _engine.dispose()
    print("SMOKE", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
