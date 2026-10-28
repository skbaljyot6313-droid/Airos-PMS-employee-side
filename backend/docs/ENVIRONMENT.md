# Environment

| Variable | Purpose | Required | Used by | Secret | Default |
|---|---|---:|---|---:|---|
| `DATABASE_URL` | Async PostgreSQL URL | Yes, unless Supabase parts are set | DB/Alembic | Yes | none |
| `SUPABASE_DB_HOST/PORT/NAME/USER/PASSWORD` | Build DB URL from parts | Alternative | DB | password only | documented in `.env.example` |
| `JWT_SECRET_KEY` | Sign access tokens | Yes in production | Auth | Yes | empty |
| `JWT_ALGORITHM` | JWT algorithm | No | Auth | No | HS256 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access lifetime | No | Auth | No | 30 |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh lifetime | No | Auth | No | 30 |
| `CORS_ORIGINS` | Allowed comma-separated origins | No | FastAPI | No | localhost:3000 |
| `REDIS_URL` | Distributed rate limiter | No | Rate limiting | May be | none |
| `RATE_LIMIT_ENABLED` | Enable endpoint limits | No | API | No | true |
| `STORAGE_BACKEND` | Deprecated — storage is always the S3 object store | No | Media | No | s3 |
| `S3_ENDPOINT_URL/REGION/BUCKET/PUBLIC_BASE_URL` | Object-store routing (Supabase Storage S3 endpoint) | Yes | Media | No | varies |
| `S3_ACCESS_KEY/S3_SECRET_KEY` | Object-store credentials | Yes | Media | Yes | none |
| `SUPABASE_URL/SUPABASE_SECRET_KEY/SUPABASE_STORAGE_BUCKET` | Supabase project (DB/auth; stored-URL key extraction) | Yes | DB/Media | key is secret | none/uploads |
| `DB_POOL_SIZE` | Retained connections per API process; minimum 1 | No | DB | No | 2 |
| `DB_MAX_OVERFLOW` | Additional connections per process; minimum 0 | No | DB | No | 1 |
| `DB_POOL_TIMEOUT` | Maximum local pool checkout wait, seconds; minimum 1 | No | DB | No | 10 |
| `DB_POOL_RECYCLE` | Connection recycle age at checkout, seconds; minimum 1 | No | DB | No | 900 |
| `DB_POOL_PRE_PING` | Check reused connections before checkout | No | DB | No | true |
| `APP_NAME/APP_ENV/DEBUG/API_V1_PREFIX` | Application metadata/runtime | No | App | No | see example |

`RUN_EMBEDDED_SCHEDULER` is retained for configuration compatibility but defaults false: this employee API does not own generation jobs. Never commit `.env`.

## Session-pool budget and rollout gate

The session pooler has reported a shared limit of 15. Budget connections, not HTTP
requests: `sum(instances * processes * engines * (pool_size + overflow))`, plus
migration connections, direct clients, and any separately initialized workers.
Every independently running process has its own pool. Push drains share the API's
engine and do not add another ceiling. Redis instances do not themselves consume
PostgreSQL connections.

| Consumer | Proposed maximum connections |
|---|---:|
| One API instance, one Uvicorn process, one engine | 3 |
| Two API instances already using the new cap during overlap | 6 total |
| First rollout: old 5+5 API overlapping new 2+1 API | 13 total; not approved |
| One concurrent Alembic process (`NullPool`) | 1 |
| Other services, workers, local tools, direct clients | Unknown; must inventory |

The known API deployment had one active instance with no worker override. This is
not a complete inventory of the shared database. A conditional rollout budget is
6 overlapping API connections + 1 migration + **at most 5 other connections** = 12,
leaving 3 slots of headroom. The five-slot allowance is a proposed cap, not an
observed count. Do not approve rollout until the owner confirms that every other
consumer fits it; account for their deployment overlap too. Retained idle session
connections count against capacity. Do not increase workers, replicas or overflow
without recalculating this budget.

The initial transition is different: the running old API can still hold 10
connections even after new variables are staged. Old + new ceilings total 13
before other consumers or migrations. That does not satisfy the proposed
three-slot reserve. Require a separately approved no-overlap maintenance rollout
for the first transition (stop the old deployment and confirm its connections
are released before starting the new one), or a separately verified transition
budget. Staging variables alone does not shrink a running engine's pool.

## Staged verification and deployment (requires explicit approval)

No URL, secret, infrastructure or deployment configuration is changed by the code
patch. The existing example env file may still show older tuning values; the
settings table above describes the code defaults. An approved operator should:

1. Record the current deployment ID/image and non-secret pool/worker settings.
   Confirm a retained known-good image can be restored before proceeding. Keep
   database URLs and credentials in the existing secret store, not shell history
   or incident reports.
2. Inventory other connection consumers and approve a budget below 15 with
   deployment headroom. Keep one API process and one instance initially.
3. Use an approved, isolated staging environment and database on the existing
   **session-mode** path. Set these non-secret variables there:

   ```text
   DB_POOL_SIZE=2
   DB_MAX_OVERFLOW=1
   DB_POOL_TIMEOUT=10
   DB_POOL_RECYCLE=900
   DB_POOL_PRE_PING=true
   ```

4. Run backend `python -m pytest -q` and frontend `npm run test`, `npm run lint`,
   `npm run build`. For backend tests, explicitly set process-local
   `DATABASE_URL=postgresql+asyncpg://test:test@127.0.0.1:1/test`, `APP_ENV=test`,
   `JWT_SECRET_KEY=unit-test-secret-not-production`, `REDIS_URL=` and
   `PUSH_PROVIDER=log`; leave pool overrides unset to test defaults. Tests use
   SQLite fixtures and that deliberately unreachable dummy application DSN,
   never production credentials. The local pool regression
   exercises 10 waves of 8 independent sessions, including cleanup and capacity
   assertions; it is not a Supabase or full mobile load test.
5. Agree a representative staging load before acceptance: repeat real employee
   post-login bursts (tasks, zones, maintenance, notifications, device/location
   startup), include retries and expiry, and observe concurrent push delivery and
   APK/media I/O. Validate authorization, task submit/review, allocation-ledger
   deduplication, attendance and location. Require no `EMAXCONNSESSION`, no pool
   timeouts, bounded active/idle connections, and acceptable p95 latency. Recheck
   after warmup and connection recycling. Do not run write/load tests in production.
6. After staging passes and separate production approval, set the five variables
   above on `employee-api` in Railway with deployment triggering skipped. Do not
   change `DATABASE_URL`, credentials, Redis, worker count, or replica count.
   For the initial transition, obtain explicit approval for downtime, stop the
   old deployment via Railway's deployment controls, and verify its database
   sessions have closed before uploading. Do not assume Railway's default
   deployment overlap is safe. If no-overlap downtime is not approved, block the
   rollout until a safe transition budget is verified.
   From the repository root, only after those gates, the CLI upload path is:

   ```sh
   railway up backend --path-as-root --service employee-api --environment production --project <approved-project-id> --detach
   ```

   No migration is required for this patch. Watch deployment completion rather
   than treating the detached command's exit as proof of health.
7. Require `/health`, `/health/db`, and `/ready` to return 200, then perform an
   approved employee smoke test. Verify the startup log reports `ceiling=3`.
   Observe `DATABASE_BUSY`, `db_busy`, pool wait (`pw`), HTTP 503 rates, connection
   counts, p95 latency, notification delivery and tracking failures through a
   representative peak and a recycle interval. Health probes alone can reuse
   existing connections and do not establish pool headroom.
8. Ship the frontend separately after the backend: rebuild with the approved
   public API URL and follow the existing signed Android release process.
   Existing mobile clients benefit from the backend fix but require an app update
   for GET retry and task-refresh coalescing. Do not change mobile release gates
   or force an update as part of this patch.

Rollback: restore the recorded known-good Railway deployment/image using the
service's deployment history, retaining the approved 2/1 connection cap and the
unchanged database URL/secrets. The CLI's plain `redeploy` redeploys the *latest*
image, so it is not a rollback to a previous artifact. If the retained image is no
longer redeployable, upload a separately verified clean checkout of the recorded
known-good source revision, not the current working tree. Repeat health and smoke
checks. Restore a previous tuning value only after a separate capacity review;
blindly returning to 5+5 can recreate the incident. A mobile rollback follows the
existing release-management process and needs separate approval. No database
schema rollback is needed.

## Transaction pooling: separate evaluation, not enabled

Do not automatically replace port 5432 with 6543. Runtime code currently disables
SQLAlchemy's `prepared_statement_cache_size` and uses unique prepared-statement
names for pooler hosts. That is not the same as asyncpg's separate
`statement_cache_size`; a transaction-pool candidate must explicitly set both
caches to zero and be tested with the installed driver/pooler versions. No such
candidate is enabled by this patch.

The source audit found transaction-scoped row locks, no application advisory
locks, temporary tables, server cursors or LISTEN/NOTIFY, and an optional
session-level idle-transaction timeout that is already skipped for pooler hosts.
These are source findings, not a certification of every external database client.
Validate auth/refresh, allocations/resource-state locks, attendance concurrency,
notifications, device registration, location sessions, rollback/cancellation and
prepared-statement behavior on PostgreSQL staging before considering a switch.
Keep Alembic on a separately approved session/direct connection path; its current
NullPool engine still uses the settings DSN, so changing the runtime DSN without
separating migration configuration is not approved.
