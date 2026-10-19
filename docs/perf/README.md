# AiROS Staff — performance overhaul notes

Context: employee app experienced 30–40 s cold starts and 2–4 min
degradations on remote infrastructure (Railway API + Supabase Postgres,
historically ~300–700 ms `SELECT 1` RTT from Singapore). Work is split
into stacked branches, each independently deployable.

| Doc | Contents |
|---|---|
| `phase-1-report.md` | Instrumentation + quick wins: stage-timing headers, startup serialization fix, push-out-of-transaction, lightweight location auth, per-request metrics, retryable connection-error screen |
| `query-audit.md` | Code-traced sequential-query audit for the hot endpoints; the Phase-2 work order |
| `phase-2-report.md` | `/bootstrap`, user-row cache, eligible-locations batching, ledger `UNION ALL`, zones ETag, slim maintenance list — all behind flags |
| `centrifugo-proposal.md` | Proposed (NOT applied) namespace config diff for history/recovery; optional company channel design; SA-backend emitter deps |
| `phase-5-proposal.md` | Worker/pool sizing, per-process-state audit, arq entrypoint, `NOTIF_SYNC_ON_READ` rollout, region re-measurement |
| `phase-6-offline-queue-design.md` | Offline mutation queue design — operation ids, `Idempotency-Key`, server dedupe; attendance excluded |
| `final-report.md` | Full results: commits, query counts, test totals, flags, decisions needed, staging checklist |

## Flags quick reference

| Flag | Layer | Default | Effect |
|---|---|---|---|
| `PERF_HEADERS_ENABLED` | backend env | on outside prod | X-DB-*/X-Redis-*/X-Ext/X-PoolWait headers (log line always keeps them) |
| `DB_IDLE_TX_TIMEOUT_MS` | backend env | 0 (off) | per-connection idle-transaction timeout; skipped on pooler hosts |
| `BOOTSTRAP_ENABLED` | backend env | on | mounts `GET /bootstrap` |
| `USER_CACHE_TTL_S` | backend env | 30 | Redis user-row cache for `get_current_user`; `0` disables |
| `REALTIME_COMPANY_CHANNEL_ENABLED` | backend env | off | `company:{uid}` channel tokens + ref_version emits |
| `VITE_BOOTSTRAP` | frontend env | off | `/bootstrap`-driven static-cache warm |
| `VITE_DATA_CACHE` | frontend env | on (`0` kills) | SWR list cache |
| `VITE_COMPANY_CHANNEL` | frontend env | off | subscribes the company channel |
