"""get_current_user user-row cache — 60s Redis sidecar for the
users+company lookup every authenticated request used to pay.

Verifies: cache miss loads+populates, cache hit skips the DB entirely
(including the joined company), merge(load=False) reconstruction updates
like a real row (UPDATE not INSERT), eviction on this service's own
writes, deactivation bounded by the TTL, and sid revocation still
enforced on hits.
"""

import fakeredis.aioredis
import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.core import sessions
from app.core.security import create_access_token
from app.dependencies import auth as auth_deps
from app.dependencies.auth import (
    Unauthenticated,
    _user_ctx_key,
    evict_user_cache,
    get_current_user,
)
from app.repositories.user import UserRepository


@pytest.fixture
async def fake_redis(monkeypatch):
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def _get():
        return client

    monkeypatch.setattr(auth_deps, "get_redis", _get)
    monkeypatch.setattr(sessions, "get_redis", _get)
    yield client
    await client.aclose()


@pytest.fixture
async def no_redis(monkeypatch):
    async def _get():
        return None

    monkeypatch.setattr(auth_deps, "get_redis", _get)
    monkeypatch.setattr(sessions, "get_redis", _get)


async def _me(user, session, sid=None):
    """sid=None → sidless token (session check skipped); tests that care
    about revocation create a real session first and pass it in."""
    token = create_access_token(
        user_id=str(user.id),
        company_id=str(user.company_id),
        role=user.role.value,
        session_id=sid,
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    return await get_current_user(credentials=creds, session=session)


async def test_miss_loads_and_populates(session, seed, fake_redis):
    user = seed["emp_user"]
    out = await _me(user, session)
    assert out.id == user.id
    assert await fake_redis.exists(_user_ctx_key(user.id)) == 1


async def test_hit_skips_db_and_restores_company(
    session, seed, fake_redis, monkeypatch
):
    user = seed["emp_user"]
    await _me(user, session)

    async def _boom(*a, **kw):
        raise AssertionError("users lookup ran on a cache hit")

    monkeypatch.setattr(UserRepository, "get_by_id", _boom)
    session.expunge_all()  # model a fresh request — no in-session state
    out = await _me(user, session)
    assert out.id == user.id
    assert out.role == user.role
    assert out.employee_id == user.employee_id
    # joined company survives the round trip (manual eager-load)
    assert out.company.company_name == seed["company"].company_name


async def test_restored_user_updates_like_a_loaded_row(
    session, seed, fake_redis
):
    """merge(load=False) must produce an UPDATE, not a phantom INSERT —
    the regression risk of detached-object caching."""
    user = seed["emp_user"]
    await _me(user, session)  # cache it
    # expire the request's loaded instance so the next _me comes from cache
    session.expunge_all()
    out = await _me(user, session)
    out.name = "Renamed Worker"
    await session.commit()
    # the DB row got an UPDATE — verify by reloading in a fresh session
    session.expunge_all()
    fresh = await UserRepository(session).get_by_id(user.id)
    assert fresh.name == "Renamed Worker"


async def test_eviction_forces_db_read(session, seed, fake_redis, monkeypatch):
    user = seed["emp_user"]
    await _me(user, session)
    await evict_user_cache(user.id)
    assert await fake_redis.exists(_user_ctx_key(user.id)) == 0
    calls = {"n": 0}
    orig = UserRepository.get_by_id

    async def counting(self, uid):
        calls["n"] += 1
        return await orig(self, uid)

    monkeypatch.setattr(UserRepository, "get_by_id", counting)
    await _me(user, session)
    assert calls["n"] == 1


async def test_sid_revocation_still_enforced_on_hit(session, seed, fake_redis):
    """The sid check is never cached — a revoked session dies even with
    a warm user cache."""
    user = seed["emp_user"]
    sid = await sessions.create_session(user_id=user.id, refresh_hash="h")
    await _me(user, session, sid=sid)
    await sessions.revoke_session(sid)
    with pytest.raises(Unauthenticated):
        await _me(user, session, sid=sid)


async def test_deactivation_bounded_by_ttl(session, seed, fake_redis):
    user = seed["emp_user"]
    sid = await sessions.create_session(user_id=user.id, refresh_hash="h")
    await _me(user, session, sid=sid)

    user.is_active = False
    await session.commit()

    # warm cache still resolves — the approved ≤60s staleness bound
    # (expunge models a fresh request; the shared session's identity map
    # would otherwise return in-session state)
    session.expunge_all()
    out = await _me(user, session, sid=sid)
    assert out.id == user.id

    # after cache expiry the DB path rejects immediately
    await fake_redis.delete(_user_ctx_key(user.id))
    session.expunge_all()
    with pytest.raises(Unauthenticated):
        await _me(user, session, sid=sid)


async def test_no_redis_uses_db_path(session, seed, no_redis):
    user = seed["emp_user"]
    out = await _me(user, session)
    assert out.id == user.id
    assert out.company.company_name == seed["company"].company_name


async def test_role_change_bounded_by_ttl(session, seed, fake_redis):
    """SA-backend role change: the cached role is served within the TTL
    (the approved staleness bound) and the new role after expiry."""
    user = seed["emp_user"]
    sid = await sessions.create_session(user_id=user.id, refresh_hash="h")
    await _me(user, session, sid=sid)  # prime

    from app.models.user import UserRole
    user.role = UserRole.PROPERTY_MANAGER
    await session.commit()

    session.expunge_all()
    out = await _me(user, session, sid=sid)
    assert out.role == UserRole.EMPLOYEE  # stale within TTL

    await fake_redis.delete(_user_ctx_key(user.id))
    session.expunge_all()
    out = await _me(user, session, sid=sid)
    assert out.role == UserRole.PROPERTY_MANAGER  # fresh after expiry


async def test_ttl_zero_disables_cache(
    session, seed, fake_redis, monkeypatch
):
    """USER_CACHE_TTL_S=0 → every request reads Postgres, no keys written."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "USER_CACHE_TTL_S", 0)

    user = seed["emp_user"]
    sid = await sessions.create_session(user_id=user.id, refresh_hash="h")
    await _me(user, session, sid=sid)
    assert await fake_redis.exists(_user_ctx_key(user.id)) == 0

    user.is_active = False
    await session.commit()
    session.expunge_all()
    with pytest.raises(Unauthenticated):
        await _me(user, session, sid=sid)
