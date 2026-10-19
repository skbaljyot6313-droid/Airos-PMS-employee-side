# Phase 1 — Quick Wins Report

Branch: `perf/phase-1-quick-wins` (10 commits, `f4e99a4`..`5833667`, on `main` @ `26467e3`)

## Scope

Phase 0 instrumentation plus the seven-item quick-win batch from the
latency audit, plus timeouts and the app-version drift fix. No schema,
deployment, env, or contract changes. All commits are independently
revertable.

## Commit-by-commit status

| # | Change | Commit | Files | Tests |
|---|---|---|---|---|
| P0a | Per-request stage timing → `X-DB-*`, `X-Redis-*`, `X-Ext-ms`, `X-PoolWait-ms` headers (gated by `PERF_HEADERS_ENABLED`, on outside prod); stages always in access log | `f4e99a4` | `core/metrics.py` (new), `core/middleware.py`, `core/database.py`, `core/redis.py`, `core/config.py`, `.env.example` | exercised in pytest suite (session/exec paths); E2E headers verified in ASGI smoke run |
| P0b | Client cold-start marks `t2`–`t7` + one-shot `[PERF]` logcat summary | `8d3f207` | `utils/perf.ts` (new), `main.tsx`, `api/client.ts`, `TasksScreen.tsx`, `AuthContext.tsx`, `App.tsx` | typecheck; marks are no-op safe |
| 1 | Zones no longer awaited in `applySession` — zone name patches asynchronously | `c8789c2` | `context/AuthContext.tsx` | typecheck; employee object set synchronously before the zone fetch |
| 2 | `pollNotificationsNow` debounced 400 ms | `813c18d` | `services/notificationService.ts`, `services/__tests__/notificationService.test.ts` | `notificationService.test.ts`: burst → 1 poll; no-loop no-op |
| 3 | Status-0/network/5xx restore failure → retryable `connectionError` screen, not Login | `d5cc900` | `context/AuthContext.tsx`, `App.tsx` | typecheck; 401/403 paths unchanged |
| 4 | `get_redis` PING once at startup, never per call | `21caa4e` | `core/redis.py` | pytest suite (session/rate-limit consumers unchanged semantics) |
| 5 | Push dispatch post-commit on a fresh session | `343cabc` | `services/notifications.py`, `core/database.py`, `tests/unit/test_notifications.py` | `test_notify_without_provider_queues_post_commit`, `test_dispatch_snapshot_sends_and_deactivates`; existing injected-provider tests untouched |
| 6 | `get_tracking_principal` — JWT+sid+role gate, employee ctx via `mt:authctx:{uid}` (60 s TTL, DB fallback) on `/location/current` | `2f80826` | `dependencies/auth.py`, `api/v1/location.py`, `services/location_live.py` | pytest (location suites); smoke run: ingest #2 `X-DB-Count=0` |
| 7 | `verify_password`/`hash_password` → `asyncio.to_thread`; asyncpg `command_timeout=30`, connect `timeout=15`; `DB_IDLE_TX_TIMEOUT_MS` opt-in (0=off, skipped on pooler hosts) | `e7a5f87` | `services/auth.py`, `core/database.py`, `core/config.py`, `.env.example` | pytest auth paths |
| 8 | `APP_VERSION` read from `App.getInfo()` (was hardcoded `1.0.12`, app.json `1.0.13`) | `5833667` | `services/pushRegistration.ts` | typecheck |

## Verified behavior (local)

- Backend `pytest`: **299/299**. Frontend `vitest`: **151/151**, `tsc --noEmit` clean, `npm run build` clean.
- In-process ASGI smoke run (SQLite app DB + fakeredis client): 23/23 checks — headers emitted per request, push drain fired post-commit with the registered token, `POST /location/current` did `db_n=1` on cache miss then `db_n=0` on hit, `GET /location/current` `db_n=0`, 401/503 paths intact.
- `GET` timeout/retry/abort semantics unchanged: apiClient keeps the 45 s `AbortController` timeout, single-flight refresh retries the original request once on 401, and mutations are not auto-replayed. **OPEN — Phase 3:** shorter timeout (~15 s), up to 2 retries with exponential backoff + jitter on network/5xx for idempotent GETs only, and `AbortController` cancel on screen unmount.

## Design confirmations

- **Push drain**: bounded by `_PUSH_DRAIN_SEMAPHORE(4)`; each failure logs the notification id; always opens a fresh `AsyncSessionLocal` — never the request-scoped session; the queue is dropped on rollback.
- **Pool wait signal**: `X-PoolWait-ms` = first `execute()` entry → first `before_cursor_execute` gap (acquisition + first-statement setup). It **includes event-loop scheduling delay** — on a contended loop the gap overstates real pool wait — so read it as an **upper bound**, not a measurement. Use it, not intuition, for pool sizing.
- **`idle_in_transaction_session_timeout`**: NOT sent as an asyncpg `server_settings` startup parameter. Opt-in via `DB_IDLE_TX_TIMEOUT_MS`, applied as a per-connection `SET` at engine connect, default 0 (off), and **skipped entirely on pooler hosts** (Supavisor/PgBouncer) until verified on staging — session state can carry between checkouts on a shared server connection.
- **`PERF_HEADERS_ENABLED`**: `None` → headers on when `APP_ENV != production`; explicit `true`/`false` overrides. Log-line stage data is unconditional.

## Expected production effect (to be confirmed by Phase 0 data)

- Startup spinner no longer waits for `/zones`; worst-case spinner drops by up to one 45 s timeout.
- Every authenticated request sheds 2–3 Redis RTTs (ping removal) and, on the ingest path, 1 Postgres RTT (authctx cache).
- Notification reads no longer hold pool connections across FCM HTTPS calls.
- Realtime publication bursts collapse to ≤1 notification poll per 400 ms.

## Staging verification checklist

Before enabling `PUSH_PROVIDER=fcm` parity checks or shipping to devices:

- [ ] **Real FCM delivery**: register a device (`POST /devices/register`), trigger an allocation (`POST /admin/notify-allocation` or SA assignment), confirm the OS notification arrives and `push:stub` is replaced by a real send — verify the post-commit drain logs no `Push dispatch failed`.
- [ ] **Dead-token cleanup**: send to a stale/uninstalled device, confirm FCM's `UNREGISTERED` deactivates the row (`device_registrations.is_active=false` on the drain session's commit).
- [ ] **Background location on device**: start tracking, background the app 10 min, confirm fixes continue and `POST /location/current` requests show `X-DB-Count=0` in staging logs (authctx hit).
- [ ] **Token refresh while backgrounded**: force an expired access token in the native service, confirm a single-flight refresh and continued ingest (no 401 storm, no duplicate session mints).
- [ ] **Pooler URL connect**: point `DATABASE_URL` at the Supabase pooler host, confirm engine starts, prepared-statement cache disabled args apply, and `DB_IDLE_TX_TIMEOUT_MS` logs the pooler-skip warning if set.
- [ ] **Headers gate**: with `APP_ENV=production`, confirm `X-DB-*` headers are absent but stage data still appears in access logs; with staging env, headers present.
- [ ] **Deactivated employee**: deactivate an employee, confirm ingest 401s within ≤60 s (authctx TTL) and immediately on Redis eviction.
- [ ] **Notification storm**: trigger ~20 allocations in seconds, confirm ≤4 concurrent drain batches and no pool pressure spike in logs.
- [ ] **Rollback drill**: revert one commit (e.g. `21caa4e`) on staging, confirm no behavior regression.

## Rollback

Each commit reverts independently. Order matters only for
`f4e99a4`→`343cabc` (hooks import PUSH_QUEUE/drain functions added in
`343cabc`) — revert them together or in reverse order.

## Follow-ups not in this batch

- `/bootstrap` consolidated endpoint, query reduction, ETag, Redis user
  cache → Phase 2 (`perf/phase-2-query-reduction`).
- **GET timeout/retry/abort hardening** (OPEN, scheduled Phase 3):
  ~15 s timeout for list reads, up to 2 retries with exponential backoff
  + jitter on network/5xx responses for idempotent GETs only, and
  `AbortController` cancel on screen unmount.
- Workers/pool sizing, arq worker, region review → Phase 5, gated on
  Phase-0 header data.
