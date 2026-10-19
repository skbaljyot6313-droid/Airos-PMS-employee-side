# Phase 5 proposal — infrastructure & queueing (PROPOSE ONLY)

Nothing in this document is applied. `railway.toml`, worker counts, pool
defaults and production env vars are unchanged. Everything below needs a
human decision + staging verification first.

## 1. Worker / pool sizing

**Constraint**: total connections = `workers × (pool_size + max_overflow)`
must stay under **50–60% of the Postgres `max_connections` limit** — the
SA backend shares the same database and already holds its own pool.

Current state: 1 uvicorn worker, pool 10 (+ default overflow). A single
worker head-of-line-blocks on every slow external call; a large pool on
one worker does nothing for CPU/queueing.

| Option | Workers | pool_size | max_overflow | Max conns | Notes |
|---|---|---|---|---|---|
| A (start) | 2 | 5 | 5 | 20 | ~2× headroom vs today on the same ceiling |
| B | 2 | 10 | 5 | 30 | only if A's `X-PoolWait-ms` shows headroom |
| C | 3 | 5 | 5 | 30 | needs per-process-state audit (below) to pass |

Start with **A**. Measure `X-PoolWait-ms` (upper bound — includes
event-loop delay) before and after on staging; raise only if the
p95 pool-wait stays meaningfully above ~5 ms under load.

**Transaction pooler (Supavisor/PgBouncer)**: if `DATABASE_URL` points
at a transaction-mode pooler, asyncpg **must** be created with
`statement_cache_size=0` — prepared statements don't survive
transaction-level pooling. The codebase already detects pooler hosts
(`_is_pooler_host` in `database.py`) and skips the per-connection
idle-transaction SET there; add `statement_cache_size=0` to that same
connect-args path when adopting a pooler.

`DB_IDLE_TX_TIMEOUT_MS` is OFF by default and skipped on pooler hosts —
only evaluate enabling it **after** the pooler decision, and via
pooler-native `idle_transaction_timeout` if using Supavisor.

## 2. Per-process state audit — what breaks with >1 worker

| State | Where | Risk at 2+ workers | Mitigation |
|---|---|---|---|
| `get_redis` health flag | `core/redis.py` | Low — each worker probes independently; ops still fail-open | none needed |
| `TimedRedis` metrics | per-request contextvar | none | n/a |
| `_last_pub` location-publish throttle | `core/centrifugo.py` | Redis path is atomic (`SET NX`); in-memory fallback splits throttle across workers → up to N publishes/interval | acceptable (throttle, not correctness); document |
| `refreshInFlight`, single-flight GET dedupe, `dataCache`/`staticCache` | frontend | client-side — unaffected | n/a |
| `_PUSH_DRAIN_SEMAPHORE` | `services/notifications.py` | per-worker bound; N workers → N×4 concurrent drains | acceptable; document |
| User-row cache `mt:user:*` | Redis | cross-worker by construction | n/a |
| Bootstrap scope cache `mt:boot:*` | Redis | cross-worker | n/a |
| `_last_pub`… any in-memory registries | — | none found beyond throttle + semaphore | — |
| Schedulers / background loops | none in this service | n/a | if an arq worker is added, run it as a SEPARATE process |
| Alembic `migrate` on deploy | Railway preDeploy | concurrent workers don't migrate; preDeploy runs once | none needed |

**No correctness-breaking shared in-memory state found** — the audit
supports 2 workers without code changes.

## 3. arq worker entrypoint (NOT enabled by default)

Move latency-insensitive, retryable work off the request path:

```python
# backend/app/workers/jobs.py  (new — not created yet; proposal only)
from arq.connections import RedisSettings

async def send_push(ctx, snapshot: dict) -> None:
    # reuse dispatch_queued_pushes — same snapshot shape as PUSH_QUEUE
    await dispatch_queued_pushes([snapshot])

async def reconcile_assignment_notifications(ctx, *, lookback_min: int = 30) -> None:
    # periodic safety net: replay the allocation-ledger sync for the
    # last N minutes — covers notify-allocation calls that never arrived
    ...

class WorkerSettings:
    functions = [send_push]
    cron_jobs = [cron(reconcile_assignment_notifications, minute=set(range(0, 60, 5)))]
    redis_settings = RedisSettings.from_dsn(os.environ["ARQ_REDIS_URL"])
```

- `send_push` replaces the in-process post-commit drain ONLY when
  `PUSH_VIA_QUEUE=true` (new env, default false) — the current
  `dispatch_queued_pushes` drain remains the default path.
- Rollout: provision the worker on staging → flip `PUSH_VIA_QUEUE` →
  observe FCM delivery + pool behavior → then production.
- arq needs its own Redis (or a dedicated DB index) — do NOT share the
  `mt:` hot-path keys' DB.

## 4. `NOTIF_SYNC_ON_READ` rollout plan

Today `GET /notifications` merges ledger-derived rows on read
(`sync_assignment_notifications`). Once **every** allocation path in the
SA backend calls `POST /admin/notify-allocation`, the read-path sync is
redundant:

1. **Verify coverage**: audit SA backend — task assignment,
   reassignment, maintenance assignment must ALL call
   `/admin/notify-allocation`. Add logging on the EB side counting
   synthesized-vs-persisted rows for one week on staging.
2. `NOTIF_SYNC_ON_READ=true` (default today) → set `false` on staging →
   assert zero synthesized rows appear in the count log.
3. Keep the flag permanently — it is the rollback switch if a new SA
   allocation path is added that forgets to call.

## 5. Region / RTT re-measurement

Historical measurements (Singapore↔Postgres `SELECT 1`): **301–696 ms**.
That was the dominant startup cost driver (serial `/auth/me` → `/zones`
→ `/tasks` → `/attendance/today`).

- Re-measure from the actual client regions: `SELECT 1` RTT from the
  Railway region to the Supabase Postgres region, TCP+TLS handshake
  included (use `X-DB-Exec-ms`/`X-DB-Query-ms` headers on staging as
  ground truth — `exec − query` isolates connection acquisition).
- If pooled-Supabase in the SAME region as Railway shows <50 ms RTT,
  the multi-worker + cache work alone may suffice; cross-region would
  still favor the `/bootstrap` consolidation.
- Record the numbers in the final report's "measured" section —
  **do not** move regions without a second data point.

## 6. Staging load test (scripts/loadtest/)

k6 script covering the three hot paths — **staging only, never run
against production**:

- `scripts/loadtest/staging.js` — cold start (auth/me → bootstrap →
  tasks), notification burst, location ingest.
- Needs a staging base URL + test credentials env vars; refuses to run
  when the URL isn't flagged `STAGING=1`.
