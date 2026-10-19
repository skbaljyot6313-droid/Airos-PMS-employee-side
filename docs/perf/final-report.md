# AiROS Staff performance overhaul — final report

Branch chain (stacked, each deploys independently):

```
main ← perf/phase-1-quick-wins ← perf/phase-2-query-reduction
     ← perf/phase-3-client-data-layer ← perf/phase-4-realtime
```

Scope guardrails honored: auth/session model, ResourceStateService,
allocation ledger, Capacitor plugin boundary, and the Redis location
schema are untouched. No production config, env vars, or deploys.

## Per-phase summary

### Phase 1 — quick wins (branch tip `a028707` + merge `da6528e`)

- Stage-timing middleware: `X-DB-Exec-ms`, `X-DB-Query-ms`, `X-DB-Count`,
  `X-Redis-ms`, `X-Redis-Ops`, `X-Ext-ms`, `X-PoolWait-ms` (upper bound —
  includes event-loop delay). Gated by `PERF_HEADERS_ENABLED`; the access
  log keeps the numbers regardless.
- Startup chain: `/zones` no longer awaited inside `applySession` —
  zone names patch in asynchronously.
- Notification poll debounced 400 ms on realtime events.
- status-0/timeout on session restore → retryable `connectionError`
  screen (tokens kept); 401/403 → sign-out/gate unchanged.
- `get_redis` probes once at startup; op outcomes drive health (fail /
  re-probe / recover — tested).
- Push dispatch drains post-commit on a fresh session (semaphore-bounded,
  failures logged with notification_id; request-scoped session never
  used).
- `get_tracking_principal` for `/location/current` — authctx Redis
  60 s + DB fallback; sid check on EVERY ingest (never cached).
- argon2 on `asyncio.to_thread`; asyncpg `command_timeout=30`,
  connect `timeout=15`; `DB_IDLE_TX_TIMEOUT_MS` opt-in OFF (skipped on
  pooler hosts).
- `APP_VERSION` from `App.getInfo()`.

### Phase 2 — query reduction (tip `de1b075`)

| Endpoint | Before | After | Note |
|---|---|---|---|
| `GET /bootstrap` (new) | — | 3 cold / 2 warm | independent sections + `errors` map + `ref_version` + `mt:boot:scope` 45 s cache; flag `BOOTSTRAP_ENABLED` |
| every authed endpoint | user row each request | −1 on cache hit | `mt:user:*` `USER_CACHE_TTL_S` (default 30, `0` off); sid check never cached |
| `/maintenance/eligible-locations` | ~8 sequential | ~5 | coverage join + joinedload — target ≤3 NOT met, see open items |
| `/notifications` ledger sync | 2 ledger queries | 1 | `UNION ALL` merge |
| `/zones` | full body every poll | 304 on unchanged | weak ETag, auth runs before 304, per-tenant tag |
| `/maintenance` list | 3 queries + eager events/attachments | 1 query + `photo_count` | detail routes unchanged; photo chip preserved via `LEFT JOIN` count |

### Phase 3 — client data layer (tip `1ed9ee8`)

- Single-flight GET dedupe keyed user + method + URL+query.
- SWR in-memory cache (`VITE_DATA_CACHE`, `0` kills): tasks 45 s,
  maintenance 45 s, attendance 45–60 s, eligible-locations 60 s; stale
  hits revalidate via `onUpdate`; mutations + logout + account switch
  invalidate.
- `@capacitor/preferences` static cache — whitelisted `zones/company/
  shift/profile`, versioned (`airos:static:v1:{uid}:{key}`), non-
  whitelisted keys throw; purge on logout/switch. No tokens/credentials/
  GPS.
- `/bootstrap` client behind `VITE_BOOTSTRAP` (OFF) — per-section legacy
  fallback on null/`errors` entries.
- GET policy: 15 s timeout, ≤2 retries (exp backoff + jitter) on
  network/5xx only, idempotent GETs only; mutations never replayed;
  `useUnmountSignal` aborts detail fetches on unmount.
- Android: native 30 s poll gated to background only
  (`webViewLikelyPolling`) — **requires an app release**, untested on
  device.

### Phase 4 — realtime (tip `cdf0d81`)

- Emitters converted from publish-after-commit convention to
  `queue_event` → `after_commit` dispatch — a rollback can never emit.
  Envelope `data.uid` added; payloads stay minimal.
- New events: `notification.created`, `task.assigned`,
  `task.completed`, `maintenance.updated` on assignment.
- Client event→invalidation map + 400 ms debounced re-pull; 45 s poll
  stays the floor.
- `wasRecovering && !recovered` → `cacheInvalidateAll` + poll +
  `realtime.unrecovered` — all screens reconcile.
- Optional `company:{uid}` ref_version channel behind
  `REALTIME_COMPANY_CHANNEL_ENABLED` + `VITE_COMPANY_CHANNEL` (both OFF).

### Phase 5/6 — artifacts only

`phase-5-proposal.md` (sizing, per-process audit, arq entrypoint,
NOTIF_SYNC_ON_READ rollout, region re-measure), `phase-6-offline-queue-
design.md` (op ids, Idempotency-Key, server dedupe; attendance excluded),
`scripts/loadtest/staging.js` (k6, `STAGING=1` guard). Nothing applied.

## Every commit

| Phase | Commits |
|---|---|
| 1 | `f4e99a4` `8d3f207` `c8789c2` `813c18d` `d5cc900` `21caa4e` `343cabc` `2f80826` `e7a5f87` `5833667` `bbf1075` `0525748` `14fd948` `a028707` |
| 2 | `53682f4` `da6528e` `ee0394f` `9c0c4b7` `6614734` `1edd348` `4e6dd4a` `bc70fc3` `a110d49` `36be830` `bd3785f` `67eb96b` `de1b075` |
| 3 | `88d2be2` `1ed9ee8` |
| 4 | `1ae3af6` `cdf0d81` |

## Test results

- Backend `pytest`: **349/349 pass** at phase-4 tip (SQLite; +7 realtime
  emit, +3 company-channel, +3 etag, +2 bootstrap isolation, +TTL suite)
- Frontend: `tsc --noEmit` clean; **182/182 vitest**; `npm run build`
  493.55 kB (gzip 136.37 kB)
- In-process E2E smoke (ASGI + SQLite + fakeredis): **19/19 checks** —
  bootstrap cold/warm (fewer DB queries warm), partial-failure errors
  map, per-tenant zone+ref_version isolation, zones ETag 304 / 401-first,
  user cache stale-within-TTL (`X-DB-Count=0` on hit)
- Secret scan over `main..phase-4` diff: clean (no keys/tokens/.env
  values; `.env.example` additions are empty placeholders + flags)

## Flags table

| Flag | Layer | Default | Effect | Rollback |
|---|---|---|---|---|
| `PERF_HEADERS_ENABLED` | backend | on outside prod | stage-timing headers | set `false` |
| `DB_IDLE_TX_TIMEOUT_MS` | backend | 0 | idle-tx timeout per conn | set `0` |
| `BOOTSTRAP_ENABLED` | backend | on | mounts `/bootstrap` | set `false` (404) |
| `USER_CACHE_TTL_S` | backend | 30 | user-row Redis cache | set `0` |
| `REALTIME_COMPANY_CHANNEL_ENABLED` | backend | off | company channel tokens/emits | set `false` |
| `VITE_BOOTSTRAP` | frontend | off | static-cache warm via `/bootstrap` | unset |
| `VITE_DATA_CACHE` | frontend | on | SWR list cache | set `0` |
| `VITE_COMPANY_CHANNEL` | frontend | off | company-channel subscribe | unset |

## Needs an app release

- **Native poll gating** (`LocationTrackingService` 30 s poll →
  background-only). Java change in the APK — a web-deploy does nothing.
- **Secure token storage** — tokens remain in `localStorage`
  (`airos_staff_*`); migrating to `SecureStoragePlugin`/Keystore-backed
  storage is a deliberate, separately scoped change (token storage was
  never touched in this work).

## Human decisions needed

1. `USER_CACHE_TTL_S` window — 30 s chosen; deactivation/role change by
   SA takes up to TTL (no eviction hook exists — shared DB).
2. Centrifugo namespace config (history_size/ttl, force_recovery) —
   proposed, NOT applied; shared with SA backend.
3. Worker/pool sizing — proposed 2×(5+5)=20 conns vs today 1×(10+def);
   keep total <50–60% of Postgres limit.
4. Region/database placement — re-measure RTT before deciding.
5. SA-backend emitters: `shift.changed`, `coverage.changed`,
   `task.completed` for SA approvals — documented, not implemented.
6. `NOTIF_SYNC_ON_READ` flip — requires verifying every SA allocation
   path calls `/admin/notify-allocation` first.
7. Optional company channel flag — enable after namespace rollout.

## Open items

- `eligible_locations` at ~5 queries vs ≤3 target — remaining ~2
  sequential queries are the zone-name map + ticket fan-out; further
  reduction needs parallel sessions (pool-dependent — Phase 5).
- Postgres/Redis verification: Docker unavailable locally — all
  backend tests ran on SQLite+fakeredis. **Staging must verify** the
  joinedload/`UNION ALL` query plans and real-Redis paths.
- Android poll gating untested on device.
- `X-PoolWait-ms` reads as an upper bound (includes scheduling delay).

## Staging verification checklist

- [ ] Real FCM delivery: allocation → push arrives on a device
- [ ] Background location on a device: ingest continues with app
      backgrounded; native poll gates correctly when foreground
- [ ] Token refresh while backgrounded: expired access token +
      cold resume → single-flight refresh → requests succeed
- [ ] Pooler connect: `statement_cache_size=0` + idle-transaction
      setting on Supavisor if a transaction pooler is used
- [ ] Postgres plans for the new joins/`UNION ALL`
      (`EXPLAIN ANALYZE` on staging data)
- [ ] `/bootstrap` on a real property graph (zones/shift parity vs
      legacy calls)
- [ ] Header numbers before vs after deploy: `X-DB-Count`,
      `X-DB-Exec-ms`, `X-PoolWait-ms` on `/tasks`, `/notifications`,
      `/maintenance`, `/bootstrap`
- [ ] Centrifugo reconnect: `wasRecovering`/`recovered` semantics after
      the namespace diff; unrecovered → client refetch observed
- [ ] Rollback drill: revert each branch independently; verify flags
      off behavior matches pre-change
- [ ] k6 staging run: `STAGING=1` cold start / notif burst / location
      ingest — record baselines
