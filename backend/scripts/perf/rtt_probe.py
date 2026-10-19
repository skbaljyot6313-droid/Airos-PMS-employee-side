#!/usr/bin/env python3
"""RTT probe — measures Postgres and Redis round-trip latency from the
runtime environment the API actually runs in (run this inside
`railway shell`, not from your laptop over a VPN).

What it measures:
  - Postgres SELECT 1 on ONE reused connection, 50 times — warm RTT.
  - Postgres SELECT 1 on a FRESH connection, 10 times — setup cost
    (TCP + TLS + auth). The fresh-minus-warm gap is what every new pool
    checkout actually pays on a cold/contended pool.
  - Redis PING, same pattern.

Usage (from backend/, inside `railway shell` or a venv with the backend
deps installed — asyncpg + redis only):
    python scripts/perf/rtt_probe.py
    python scripts/perf/rtt_probe.py --dsn "$DATABASE_URL" \
        --pooler-dsn "$POOLER_URL" --redis-url "$REDIS_URL"

Env fallbacks: DATABASE_URL / DIRECT_DATABASE_URL / POOLER_DATABASE_URL /
REDIS_URL. When both a direct and a pooler DSN are provided, both are
measured side by side. Read-only — sends SELECT 1 / PING only.
"""
import argparse
import asyncio
import os
import sys


def _pct(vals, q):
    s = sorted(vals)
    if not s:
        return 0.0
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


def _report(name, vals):
    if not vals:
        print(f"  {name:<34} no samples")
        return
    print(
        f"  {name:<34} n={len(vals):>3}  "
        f"min={min(vals):>7.1f}  p50={_pct(vals, .5):>7.1f}  "
        f"p95={_pct(vals, .95):>7.1f}  max={max(vals):>7.1f} ms"
    )


def _normalize(dsn: str) -> str:
    """Accept postgres://, postgresql:// or SQLAlchemy-style URLs —
    asyncpg.connect wants postgres(s)://."""
    for prefix in ("postgresql+asyncpg://", "postgres+asyncpg://"):
        if dsn.startswith(prefix):
            return "postgresql://" + dsn[len(prefix):]
    return dsn


async def probe_pg(dsn: str, label: str, warm: int, fresh: int) -> None:
    import asyncpg

    print(f"Postgres ({label}):")
    conn = await asyncpg.connect(_normalize(dsn))
    try:
        w = []
        for _ in range(warm):
            t0 = asyncio.get_event_loop().time()
            await conn.fetchval("SELECT 1")
            w.append((asyncio.get_event_loop().time() - t0) * 1000)
        _report(f"SELECT 1 reused conn x{warm}", w)
    finally:
        await conn.close()

    f = []
    for _ in range(fresh):
        t0 = asyncio.get_event_loop().time()
        c = await asyncpg.connect(_normalize(dsn))
        try:
            await c.fetchval("SELECT 1")
        finally:
            await c.close()
        f.append((asyncio.get_event_loop().time() - t0) * 1000)
    _report(f"SELECT 1 fresh conn  x{fresh} (incl. connect)", f)


async def probe_redis(url: str, warm: int, fresh: int) -> None:
    from redis.asyncio import Redis

    print("Redis:")
    client = Redis.from_url(url, socket_connect_timeout=5,
                            socket_timeout=5)
    try:
        w = []
        for _ in range(warm):
            t0 = asyncio.get_event_loop().time()
            await client.ping()
            w.append((asyncio.get_event_loop().time() - t0) * 1000)
        _report(f"PING reused client   x{warm}", w)
    finally:
        await client.aclose()

    f = []
    for _ in range(fresh):
        t0 = asyncio.get_event_loop().time()
        c = Redis.from_url(url, socket_connect_timeout=5,
                           socket_timeout=5)
        try:
            await c.ping()
        finally:
            await c.aclose()
        f.append((asyncio.get_event_loop().time() - t0) * 1000)
    _report(f"PING fresh client    x{fresh} (incl. connect)", f)


async def run(args) -> int:
    dsns = []
    if args.dsn:
        dsns.append((args.dsn, "DATABASE_URL (direct)"))
    pooler = args.pooler_dsn or os.environ.get("POOLER_DATABASE_URL")
    if pooler:
        dsns.append((pooler, "POOLER_DATABASE_URL (pooler)"))
    if not dsns:
        env = os.environ.get("DATABASE_URL") or \
            os.environ.get("DIRECT_DATABASE_URL")
        if env:
            dsns.append((env, "DATABASE_URL"))
    if not dsns:
        print("No Postgres DSN — set DATABASE_URL or pass --dsn.",
              file=sys.stderr)

    for dsn, label in dsns:
        try:
            await probe_pg(dsn, label, args.warm, args.fresh)
        except Exception as exc:
            print(f"  {label}: FAILED — {type(exc).__name__}: {exc}")

    redis_url = args.redis_url or os.environ.get("REDIS_URL")
    if redis_url:
        try:
            await probe_redis(redis_url, args.warm, args.fresh)
        except Exception as exc:
            print(f"  Redis: FAILED — {type(exc).__name__}: {exc}")
    else:
        print("Redis: skipped (no --redis-url / REDIS_URL)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dsn", help="direct Postgres DSN (default: DATABASE_URL)")
    ap.add_argument("--pooler-dsn", help="pooler DSN to compare side-by-side")
    ap.add_argument("--redis-url", help="Redis URL (default: REDIS_URL)")
    ap.add_argument("--warm", type=int, default=50,
                    help="reused-connection samples (default 50)")
    ap.add_argument("--fresh", type=int, default=10,
                    help="fresh-connection samples (default 10)")
    args = ap.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
