"""get_tracking_principal — the lightweight /location/current auth path.

Guarantees under test:
- the Redis sid/session revocation check runs on EVERY ingest call, not
  only on an authctx cache miss (logout still kills ingest instantly)
- a warm mt:authctx:{uid} cache entry serves the employee context without
  a users-row lookup
- a deactivated employee is rejected within the cache TTL (rejection
  verified right after cache expiry)
- the same warm cache tolerates deactivation for up to the TTL — the
  approved bounded-staleness trade-off (60s)
- no invalidation hook exists for the cached fields because this service
  never writes them (user.is_active / employee links are SA-backend
  writes on the shared DB; PATCH /auth/me only touches name/phone/email)
"""

import fakeredis.aioredis
import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.core import sessions
from app.core.security import create_access_token
from app.dependencies import auth as auth_deps
from app.dependencies.auth import (
    Forbidden,
    Unauthenticated,
    _auth_ctx_key,
    get_tracking_principal,
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


async def _principal(user, session, sid="sid-x", role=None):
    token = create_access_token(
        user_id=str(user.id),
        company_id=str(user.company_id),
        role=role if role is not None else user.role.value,
        session_id=sid,
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    return await get_tracking_principal(credentials=creds, session=session)


async def test_sid_check_runs_on_every_call(session, seed, fake_redis):
    """Revocation must not hide behind a warm authctx cache — the sid
    check runs before any cached context is used."""
    user = seed["emp_user"]
    sid = await sessions.create_session(user_id=user.id, refresh_hash="h")

    p1 = await _principal(user, session, sid=sid)
    assert p1.employee_id == user.employee_id
    assert await fake_redis.exists(_auth_ctx_key(user.id)) == 1  # warm

    await sessions.revoke_session(sid)
    with pytest.raises(Unauthenticated):
        await _principal(user, session, sid=sid)


async def test_warm_cache_serves_context_without_db(
    session, seed, fake_redis, monkeypatch
):
    user = seed["emp_user"]
    sid = await sessions.create_session(user_id=user.id, refresh_hash="h")

    p1 = await _principal(user, session, sid=sid)
    assert p1.employee_id == user.employee_id

    # Second call must not touch the users table at all.
    async def _boom(*args, **kwargs):
        raise AssertionError("users lookup happened on a warm authctx")

    monkeypatch.setattr(UserRepository, "get_by_id", _boom)
    p2 = await _principal(user, session, sid=sid)
    assert p2.employee_id == p1.employee_id
    assert p2.property_id == p1.property_id
    assert p2.role == user.role.value


async def test_deactivated_rejected_after_cache_expiry(session, seed, fake_redis):
    """The only staleness bound is the 60s TTL — after expiry the DB
    path must reject a deactivated user."""
    user = seed["emp_user"]
    sid = await sessions.create_session(user_id=user.id, refresh_hash="h")

    await _principal(user, session, sid=sid)  # prime the cache
    user.is_active = False
    await session.commit()

    await fake_redis.delete(_auth_ctx_key(user.id))  # simulate TTL expiry
    with pytest.raises(Unauthenticated):
        await _principal(user, session, sid=sid)


async def test_warm_cache_tolerates_deactivation_within_ttl(session, seed, fake_redis):
    """APPROVED trade-off: while the cached ctx is fresh (≤60s), a
    deactivated employee keeps resolving. This test guards the bound —
    it must never silently become permanent."""
    user = seed["emp_user"]
    sid = await sessions.create_session(user_id=user.id, refresh_hash="h")

    await _principal(user, session, sid=sid)
    user.is_active = False
    await session.commit()

    p = await _principal(user, session, sid=sid)
    assert p.employee_id == user.employee_id


async def test_no_redis_falls_back_to_db_path(session, seed, no_redis):
    user = seed["emp_user"]
    sid = await sessions.create_session(user_id=user.id, refresh_hash="h")
    p = await _principal(user, session, sid=sid)
    assert p.employee_id == user.employee_id

    user.is_active = False
    await session.commit()
    with pytest.raises(Unauthenticated):
        await _principal(user, session, sid=sid)


async def test_non_tracking_roles_rejected(session, seed, fake_redis):
    sid = await sessions.create_session(
        user_id=seed["pm"].id, refresh_hash="h"
    )
    with pytest.raises(Forbidden):
        await _principal(seed["pm"], session, sid=sid)


async def test_missing_and_bad_tokens_rejected(session, seed, fake_redis):
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="garbage")
    with pytest.raises(Unauthenticated):
        await get_tracking_principal(credentials=creds, session=session)
    with pytest.raises(Unauthenticated):
        await get_tracking_principal(credentials=None, session=session)
