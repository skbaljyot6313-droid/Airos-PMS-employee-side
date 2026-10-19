"""GET /bootstrap service tests — parity, query budget, partial failure,
feature flag, cache behavior.

Run against the in-memory SQLite session + fakeredis, mirroring the
service-level test style; route mounting is covered by the app tests.
"""

import json

import fakeredis.aioredis
import pytest

from app.core.config import settings
from app.dependencies.auth import Forbidden
from app.models.notifications import Notification
from app.models.structure import Zone
from app.repositories.workspace import WorkspaceRepository
from app.services import bootstrap as boot
from app.services.notifications import NotificationService


@pytest.fixture
async def fake_redis(monkeypatch):
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def _get():
        return client

    monkeypatch.setattr(boot, "get_redis", _get)
    yield client
    await client.aclose()


@pytest.fixture
async def no_redis(monkeypatch):
    async def _get():
        return None

    monkeypatch.setattr(boot, "get_redis", _get)


def _counting_session(session):
    """Wrap session.execute to count DB round trips for the request."""
    calls = {"n": 0}
    orig = session.execute

    async def wrapped(*args, **kwargs):
        calls["n"] += 1
        return await orig(*args, **kwargs)

    session.execute = wrapped
    return calls


async def test_parity_with_individual_endpoints(session, seed, fake_redis):
    """Sections must be byte-identical in SHAPE to the legacy endpoints
    so the client can fall back per-section without a special parser."""
    user = seed["emp_user"]
    zone = Zone(property_id=seed["prop"].id, name="Zone A", code="ZA")
    session.add(zone)
    session.add(Notification(
        property_id=seed["prop"].id, employee_id=user.employee_id,
        type="task_assigned", title="t", body="m", is_read=False,
    ))
    await session.commit()

    out = await boot.get_bootstrap(user, session)

    # user/company — same serializers as GET /auth/me
    assert out["user"]["uid"] == str(user.id)
    assert out["user"]["employee_uid"] == str(user.employee_id)
    assert out["company"]["company_uid"] == str(seed["company"].id)
    # zones — same envelope as GET /zones
    assert set(out["zones"]) == {"items", "total", "page", "limit"}
    assert out["zones"]["items"][0]["zone_uid"] == str(zone.id)
    # shift — same shape as GET /attendance/shift (employee has no shift
    # in the fixture → not_assigned is the parity case)
    assert out["shift"]["status"] == "not_assigned"
    assert "date" in out["shift"] and "timezone" in out["shift"]
    # unread_count — same shape as GET /notifications/unread-count
    assert out["unread_count"] == {"unread": 1}
    assert out["errors"] == {}
    assert out["ref_version"]


async def test_unread_count_never_syncs(session, seed, no_redis, monkeypatch):
    """The bootstrap unread section must not trigger ledger sync."""
    user = seed["emp_user"]
    called = {"n": 0}

    async def _boom(self, u):
        called["n"] += 1
        raise AssertionError("sync invoked from bootstrap")

    monkeypatch.setattr(
        NotificationService, "sync_assignment_notifications", _boom
    )
    out = await boot.get_bootstrap(user, session)
    assert called["n"] == 0
    assert out["unread_count"] == {"unread": 0}


async def test_query_budget_on_warm_cache(session, seed, fake_redis):
    """Cache-warm bootstrap must run <=3 DB queries: user lookup happens
    in the dependency; here we count business-section queries (zones
    cached → shift(1) + unread(1) — and the scope block costs zero)."""
    user = seed["emp_user"]
    await boot.get_bootstrap(user, session)  # warm the scope cache

    calls = _counting_session(session)
    out = await boot.get_bootstrap(user, session)
    assert calls["n"] <= 3, f"expected <=3 db queries, ran {calls['n']}"
    assert calls["n"] == 2  # shift + unread; zones from cache


async def test_partial_failure_isolated(session, seed, fake_redis, monkeypatch):
    user = seed["emp_user"]

    async def _boom(self, u, **kw):
        raise RuntimeError("zones exploded")

    monkeypatch.setattr(WorkspaceRepository, "list_zones", _boom)
    out = await boot.get_bootstrap(user, session)

    assert out["zones"] is None
    assert out["company"] is None
    assert out["errors"]["zones"] == "INTERNAL_ERROR"
    # Other sections must still resolve.
    assert out["user"]["uid"] == str(user.id)
    assert out["shift"]["status"] == "not_assigned"
    assert out["unread_count"] == {"unread": 0}


async def test_no_employee_link_errors_sections(session, seed, no_redis):
    """emp_user2 has no employee record — employee sections error out,
    company-scoped sections still resolve."""
    out = await boot.get_bootstrap(seed["emp_user2"], session)
    assert out["zones"] is not None
    assert out["shift"] is None
    assert out["errors"]["shift"] == "FORBIDDEN"
    assert out["unread_count"] is None
    assert out["errors"]["unread_count"] == "FORBIDDEN"


async def test_flag_off_raises_not_found(session, seed, no_redis, monkeypatch):
    monkeypatch.setattr(settings, "BOOTSTRAP_ENABLED", False)
    with pytest.raises(boot.BootstrapDisabled) as ei:
        await boot.get_bootstrap(seed["emp_user"], session)
    assert ei.value.status_code == 404


async def test_zones_served_from_cache_without_db(session, seed, fake_redis, monkeypatch):
    user = seed["emp_user"]
    await boot.get_bootstrap(user, session)

    async def _boom(*args, **kwargs):
        raise AssertionError("zones hit the DB on a warm cache")

    monkeypatch.setattr(WorkspaceRepository, "list_zones", _boom)
    out = await boot.get_bootstrap(user, session)
    assert out["zones"] is not None


async def test_ref_version_changes_with_content(session, seed, fake_redis):
    user = seed["emp_user"]
    ref1 = (await boot.get_bootstrap(user, session))["ref_version"]
    session.add(Notification(
        property_id=seed["prop"].id, employee_id=user.employee_id,
        type="task_assigned", title="t", body="m", is_read=False,
    ))
    await session.commit()
    ref2 = (await boot.get_bootstrap(user, session))["ref_version"]
    assert ref1 != ref2


async def test_zone_mutation_evicts_scope_cache(session, seed, fake_redis):
    """create_zone must drop the cached scope block (best-effort; TTL
    is the bound for SA-backend writes)."""
    from app.services.structure import StructureService
    from app.schemas.structure import ZoneCreateRequest

    admin = seed["admin"]
    user = seed["emp_user"]

    await boot.get_bootstrap(user, session)  # prime cache
    keys = [k async for k in fake_redis.scan_iter("mt:boot:scope:*")]
    assert len(keys) == 1

    svc = StructureService(session)
    await svc.create_zone(
        admin, ZoneCreateRequest(property_uid=seed["prop"].id, name="New Zone")
    )
    keys = [k async for k in fake_redis.scan_iter("mt:boot:scope:*")]
    assert len(keys) == 0


async def _make_tenant(session, tag: str):
    """A second tenant (company/property/user/employee) for isolation
    tests."""
    from app.models.company import Company
    from app.models.employee import Employee
    from app.models.property import Property
    from app.models.user import User, UserRole

    company = Company(
        company_name=f"Co-{tag}", brand_name=f"Co-{tag}",
        email=f"c-{tag}@x.test",
        phone_number="1", address="a", pin_code="1",
    )
    session.add(company)
    await session.flush()
    prop = Property(
        company_id=company.id, name=f"Prop-{tag}", code=tag[:4],
        location="l", city="c", state="s",
        manager_name="m", manager_email="m@x.test",
    )
    session.add(prop)
    await session.flush()
    emp = Employee(
        company_id=company.id, property_id=prop.id,
        name=f"W-{tag}", email=f"e-{tag}@x.test", status="active",
    )
    session.add(emp)
    await session.flush()
    user = User(
        company_id=company.id, property_id=prop.id, name=f"U-{tag}",
        email=f"u-{tag}@x.test", username=f"u{tag}", password_hash="x",
        role=UserRole.EMPLOYEE, employee_id=emp.id,
    )
    admin = User(
        company_id=company.id, property_id=prop.id, name=f"A-{tag}",
        email=f"a-{tag}@x.test", username=f"a{tag}", password_hash="x",
        role=UserRole.SUPER_ADMIN,
    )
    session.add_all([user, admin])
    await session.commit()
    return {"company": company, "prop": prop, "user": user, "admin": admin,
            "employee": emp}


async def test_cross_tenant_isolation(session, seed, fake_redis):
    """Company-scoped cache entries must never leak between tenants:
    the key embeds company_id + employee property scope."""
    from app.models.structure import Zone
    t1, t2 = seed, await _make_tenant(session, "B")
    session.add(Zone(property_id=t1["prop"].id, name="Zone-A", code="ZA",
                     zone_type="stay"))
    session.add(Zone(property_id=t2["prop"].id, name="Zone-B", code="ZB",
                     zone_type="stay"))
    await session.commit()

    out_a = await boot.get_bootstrap(t1["emp_user"], session)
    out_b = await boot.get_bootstrap(t2["user"], session)

    names_a = {z["name"] for z in out_a["zones"]["items"]}
    names_b = {z["name"] for z in out_b["zones"]["items"]}
    assert "Zone-A" in names_a and "Zone-B" in names_b
    assert "Zone-B" not in names_a and "Zone-A" not in names_b
    assert out_a["company"]["company_uid"] != out_b["company"]["company_uid"]

    # distinct cache keys — one per (company, scope)
    keys = {k async for k in fake_redis.scan_iter("mt:boot:scope:*")}
    expected = {
        f"mt:boot:scope:{t1['company'].id}:{t1['emp_user'].property_id}",
        f"mt:boot:scope:{t2['company'].id}:{t2['user'].property_id}",
    }
    assert keys == expected


async def test_zone_eviction_only_own_scope(session, seed, fake_redis):
    """A zone mutation in tenant 1 evicts tenant-1 keys only — tenant 2's
    cached block survives untouched."""
    from app.services.structure import StructureService
    from app.schemas.structure import ZoneCreateRequest

    t2 = await _make_tenant(session, "B")
    await boot.get_bootstrap(seed["emp_user"], session)
    await boot.get_bootstrap(t2["user"], session)
    b_key = f"mt:boot:scope:{t2['company'].id}:{t2['user'].property_id}"
    assert await fake_redis.exists(b_key) == 1

    await StructureService(session).create_zone(
        seed["admin"],
        ZoneCreateRequest(property_uid=seed["prop"].id, name="New Zone"),
    )
    # tenant 1's scope entries evicted; tenant 2's still warm
    assert await fake_redis.exists(b_key) == 1
    t1_keys = [
        k async for k in fake_redis.scan_iter(
            f"mt:boot:scope:{seed['company'].id}:*"
        )
    ]
    assert t1_keys == []


async def test_get_by_id_runs_once_per_request_contract(session, seed, no_redis):
    """The auth lookup happens exactly once — in get_current_user; the
    service itself must not re-fetch the users row."""
    from app.repositories.user import UserRepository

    user = seed["emp_user"]
    calls = {"n": 0}
    orig = UserRepository.get_by_id

    async def counting(self, uid):
        calls["n"] += 1
        return await orig(self, uid)

    import pytest as _p
    mp = _p.MonkeyPatch()
    mp.setattr(UserRepository, "get_by_id", counting)
    await boot.get_bootstrap(user, session)
    assert calls["n"] == 0
    mp.undo()
