"""get_redis lifecycle — probe once, op-outcome-driven health, re-probe
after failure, recovery on success, and caller-level fail-open preserved
for sessions and rate limiting.

get_redis() is exercised for real; only Redis.from_url is faked with a
backend whose connectivity can be toggled mid-run.
"""

import pytest

from app.core import rate_limit, redis as redis_mod, sessions


class _FlakyBackend:
    """Stands in for redis.asyncio.Redis — connectivity is toggled with
    `down`. Pings/ops raise ConnectionError while down."""

    def __init__(self):
        self.down = False
        self.pings = 0

    async def ping(self):
        self.pings += 1
        if self.down:
            raise ConnectionError("redis down")
        return True

    async def get(self, _key):
        if self.down:
            raise ConnectionError("redis down")
        return None

    async def exists(self, _key):
        if self.down:
            raise ConnectionError("redis down")
        return 1

    async def incr(self, _key):
        if self.down:
            raise ConnectionError("redis down")
        return 1


@pytest.fixture
def flaky(monkeypatch):
    backend = _FlakyBackend()
    monkeypatch.setattr(redis_mod.settings, "REDIS_URL", "redis://fake:6379/0")
    monkeypatch.setattr(
        redis_mod.Redis, "from_url", classmethod(lambda cls, url, **kw: backend)
    )
    monkeypatch.setattr(redis_mod, "_client", None)
    monkeypatch.setattr(redis_mod, "_available", None)
    yield backend
    monkeypatch.setattr(redis_mod, "_client", None)
    monkeypatch.setattr(redis_mod, "_available", None)


async def test_probes_once_then_no_per_call_ping(flaky):
    c1 = await redis_mod.get_redis()
    c2 = await redis_mod.get_redis()
    assert c1 is c2
    assert flaky.pings == 1


async def test_mid_run_failure_reprobes_and_recovers(flaky):
    client = await redis_mod.get_redis()
    assert flaky.pings == 1

    # Redis dies mid-run — ops still execute and raise (callers degrade).
    flaky.down = True
    with pytest.raises(ConnectionError):
        await client.get("k")
    # The op failure flipped health to unknown → next get_redis re-probes.
    await redis_mod.get_redis()
    assert flaky.pings == 2
    assert redis_mod._available is False

    # While down, ops still get the client and fail fast individually;
    # each failed op schedules the next call to re-probe once.
    with pytest.raises(ConnectionError):
        await client.get("k")
    await redis_mod.get_redis()
    assert flaky.pings == 3

    # Redis recovers — the next successful op marks the client live with
    # no extra probe needed.
    flaky.down = False
    assert await client.get("k") is None
    assert redis_mod._available is True
    await redis_mod.get_redis()
    assert flaky.pings == 3


async def test_unconfigured_returns_none(monkeypatch):
    monkeypatch.setattr(redis_mod.settings, "REDIS_URL", "")
    monkeypatch.setattr(redis_mod, "_client", None)
    monkeypatch.setattr(redis_mod, "_available", None)
    assert await redis_mod.get_redis() is None


async def test_sessions_alive_fails_open_on_op_failure(monkeypatch):
    """Session checks keep failing open when Redis ops raise — the
    fail-open contract is upstream of get_redis health tracking."""
    broken = _FlakyBackend()
    broken.down = True

    async def _get():
        return broken

    monkeypatch.setattr(sessions, "get_redis", _get)
    assert await sessions.alive("sid-gone-or-not") is True


async def test_rate_limit_fails_open_on_op_failure(monkeypatch):
    broken = _FlakyBackend()
    broken.down = True

    async def _get():
        return broken

    monkeypatch.setattr(rate_limit, "get_redis", _get)
    assert await rate_limit.check_rate_limit("login", "k", 1, 60) is True
