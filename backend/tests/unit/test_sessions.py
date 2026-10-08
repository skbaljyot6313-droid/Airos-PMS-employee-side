"""Redis session registry — login writes mt:session:{sid}, the JWT carries
a `sid` claim, get_current_user rejects tokens whose session is gone.

Redis is faked at the app.core.redis.get_redis seam (fakeredis) — the same
seam location_live tests use. AuthService runs against the in-memory
SQLite session fixture; the route-level check calls the dependency
directly.
"""

import uuid

import fakeredis.aioredis
import pytest

from app.core import redis as redis_core
from app.core import sessions
from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_refresh_token,
)
from app.dependencies.auth import Unauthenticated, get_current_user
from app.services.auth import AuthService


@pytest.fixture
async def fake_redis(monkeypatch):
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def _get():
        return client

    monkeypatch.setattr(redis_core, "get_redis", _get)
    monkeypatch.setattr(sessions, "get_redis", _get)
    yield client
    await client.aclose()


@pytest.fixture
async def no_redis(monkeypatch):
    async def _get():
        return None

    monkeypatch.setattr(redis_core, "get_redis", _get)
    monkeypatch.setattr(sessions, "get_redis", _get)


async def _login(service: AuthService, user) -> tuple[str, str]:
    """Issue a token pair through the real AuthService path."""
    user.is_active = True
    return await service._issue_tokens(user)


# ---------------------------------------------------------------------------
# Registry primitives
# ---------------------------------------------------------------------------


async def test_create_session_marks_alive(fake_redis):
    uid = uuid.uuid4()
    rt_hash = hash_refresh_token(generate_refresh_token())
    sid = await sessions.create_session(user_id=uid, refresh_hash=rt_hash)
    assert sid is not None
    assert await sessions.alive(sid)
    assert await sessions.sid_by_refresh(rt_hash) == sid


async def test_revoke_session_kills_access(fake_redis):
    uid = uuid.uuid4()
    rt_hash = hash_refresh_token(generate_refresh_token())
    sid = await sessions.create_session(user_id=uid, refresh_hash=rt_hash)
    await sessions.revoke_by_refresh(rt_hash)
    assert not await sessions.alive(sid)
    assert await sessions.sid_by_refresh(rt_hash) is None


async def test_revoke_all_for_user(fake_redis):
    uid = uuid.uuid4()
    sids = [
        await sessions.create_session(
            user_id=uid, refresh_hash=hash_refresh_token(generate_refresh_token())
        )
        for _ in range(3)
    ]
    assert await sessions.revoke_all_for_user(uid) == 3
    for sid in sids:
        assert not await sessions.alive(sid)


async def test_unknown_sid_is_not_alive(fake_redis):
    assert not await sessions.alive("no-such-session")


async def test_no_redis_fails_open(no_redis):
    """Unconfigured/unreachable Redis → session checks must not lock
    users out (accelerator contract, same as the rate limiter)."""
    assert await sessions.alive("any-sid") is True
    assert await sessions.create_session(
        user_id=uuid.uuid4(), refresh_hash="x"
    ) is None
    assert await sessions.revoke_all_for_user(uuid.uuid4()) == 0


# ---------------------------------------------------------------------------
# AuthService integration
# ---------------------------------------------------------------------------


async def test_login_embeds_sid_and_session_alive(session, seed, fake_redis):
    service = AuthService(session)
    access, refresh = await _login(service, seed["emp_user"])
    claims = decode_access_token(access)
    sid = claims.get("sid")
    assert sid is not None
    assert await sessions.alive(sid)
    assert await sessions.sid_by_refresh(hash_refresh_token(refresh)) == sid


async def test_logout_revokes_session(session, seed, fake_redis):
    service = AuthService(session)
    access, refresh = await _login(service, seed["emp_user"])
    sid = decode_access_token(access)["sid"]
    await service.logout(refresh)
    assert not await sessions.alive(sid)
    # DB refresh token also revoked
    from app.repositories.refresh_token import RefreshTokenRepository
    stored = await RefreshTokenRepository(session).get_valid(
        hash_refresh_token(refresh)
    )
    assert stored is None


async def test_refresh_reissues_same_sid(session, seed, fake_redis):
    service = AuthService(session)
    access, refresh = await _login(service, seed["emp_user"])
    await session.commit()
    old_sid = decode_access_token(access)["sid"]
    new_access = await service.refresh(refresh)
    assert decode_access_token(new_access)["sid"] == old_sid


async def test_refresh_rematerializes_lost_session(session, seed, fake_redis):
    """Postgres is the source of truth: a valid refresh token after a
    Redis flush gets a fresh session instead of an error."""
    service = AuthService(session)
    access, refresh = await _login(service, seed["emp_user"])
    await session.commit()
    await fake_redis.flushall()  # simulate Redis restart
    new_access = await service.refresh(refresh)
    new_sid = decode_access_token(new_access)["sid"]
    assert new_sid is not None
    assert await sessions.alive(new_sid)


async def test_no_redis_issues_sidless_token(session, seed, no_redis):
    service = AuthService(session)
    access, _ = await _login(service, seed["emp_user"])
    assert decode_access_token(access).get("sid") is None


# ---------------------------------------------------------------------------
# get_current_user gate
# ---------------------------------------------------------------------------


async def _call_get_current_user(token: str, session):
    from fastapi.security import HTTPAuthorizationCredentials

    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    return await get_current_user(credentials=creds, session=session)


async def test_revoked_session_rejects_access_token(session, seed, fake_redis):
    user = seed["emp_user"]
    sid = await sessions.create_session(user_id=user.id, refresh_hash="h")
    token = create_access_token(
        user_id=str(user.id), company_id=str(user.company_id),
        role=user.role.value, session_id=sid,
    )
    await sessions.revoke_session(sid)
    with pytest.raises(Unauthenticated):
        await _call_get_current_user(token, session)


async def test_live_session_passes(session, seed, fake_redis):
    user = seed["emp_user"]
    sid = await sessions.create_session(user_id=user.id, refresh_hash="h")
    token = create_access_token(
        user_id=str(user.id), company_id=str(user.company_id),
        role=user.role.value, session_id=sid,
    )
    assert (await _call_get_current_user(token, session)).id == user.id


async def test_sidless_token_unaffected(session, seed, fake_redis):
    """Pre-sessions tokens (and sid-less tokens issued during a Redis
    outage) validate by JWT alone."""
    user = seed["emp_user"]
    token = create_access_token(
        user_id=str(user.id), company_id=str(user.company_id),
        role=user.role.value,
    )
    assert (await _call_get_current_user(token, session)).id == user.id
