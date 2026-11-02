# AiROS Employee — Phase 3 Deployment Readiness

Date: 2026-11-02 · Service `airos-eb-api-dev` · Image
`asia-south1-docker.pkg.dev/final-airos-os/airos-dev/airos-eb-api-dev:<tag>`
(local build `airos-eb-api-dev:local` verified — see §4). **NOT DEPLOYED.**

## 1. Environment-variable matrix (final)

| Var | Value / source | Required |
|---|---|---|
| `APP_ENV` | `production` | yes |
| `DEBUG` | `false` | yes |
| `PORT` | `8080` (Cloud Run injects; app reads `$PORT`) | yes |
| `DATABASE_URL` | `postgresql+asyncpg://airos_eb_app@/airos_dev?host=/cloudsql/final-airos-os:asia-south1:airos-postgres-dev/.s.PGSQL.5432` — password injected via `${SUPABASE_DB_PASSWORD}` placeholder → Secret `airos-dev-eb-db-password` (see below) | **mandatory** |
| `SUPABASE_DB_PASSWORD` | secret ref `airos-dev-eb-db-password` (name kept — it's the password-injection slot, not a Supabase dep) | mandatory |
| `JWT_SECRET_KEY` | secret ref `airos-dev-eb-jwt-secret` (dedicated EB secret — cross-verification not needed; S2S uses service keys) | mandatory |
| `REDIS_URL` | `redis://<redis-host>:6379` — pending instance READY | recommended |
| `GCS_BUCKET` | `final-airos-os-dev-employee-objects-94363806721` | for uploads |
| `LOCATION_SERVICE_API_KEY` | set if SA calls `/admin/*` — needs a shared dev value (mint + store `airos-dev-location-service-key`, share with SA) | optional |
| `RELEASE_MANAGEMENT_API_KEY` | needed for `/mobile/releases*` writes | optional |
| `CORS_ORIGINS` | dev web origin(s) only — mobile doesn't use CORS | yes |
| `USER_CACHE_TTL_S` | `30` | default |
| `BOOTSTRAP_ENABLED` | `true` | default |
| `PERF_HEADERS_ENABLED` | `false` | prod-safe default |
| `PUSH_PROVIDER` | `fcm` once creds confirmed (ADC via runtime SA — code needs `google-auth` path OR SA-JSON secret; `log` until then) | optional |
| `RUN_EMBEDDED_SCHEDULER` | `false` | explicit — no scheduler runs |
| `DB_POOL_SIZE`/`DB_MAX_OVERFLOW`/`DB_POOL_TIMEOUT`/`DB_POOL_RECYCLE`/`DB_POOL_PRE_PING` | `2`/`1`/`10`/`900`/`true` | defaults |
| `CENTRIFUGO_*` | unset → realtime 503s, poll fallback | optional |

## 2. Connection budget (shared Cloud SQL)

SA service (assume ≤4 inst × ~3 conn) + EB (4 inst × 3) + migrate job (2) + admin ≈ **≤20 connections** — comfortably under the `db-custom-1-3840` max (~100+). One uvicorn worker per instance; engine disposed at lifespan shutdown.

## 3. Cloud Run plan (not executed)

`gcloud run deploy airos-eb-api-dev --image=<ar-tag> --region=asia-south1 --service-account=airos-eb-dev-runtime@... --add-cloudsql-instances=final-airos-os:asia-south1:airos-postgres-dev --vpc-egress=private-ranges-only --network=default --subnet=default --cpu=2 --memory=1Gi --min-instances=1 --max-instances=4 --concurrency=20 --allow-unauthenticated` + `--set-env-vars` + `--set-secrets` for the two secret refs. Unauthenticated at infra layer (mobile can't hold ID tokens); app-level JWT enforces auth on every route.

## 4. Verified readiness

- Docker image builds clean (`airos-eb-api-dev:local` — incl. google-cloud-storage 3.17.1); non-root user; `/health` Docker HEALTHCHECK; uvicorn `--proxy-headers`.
- No startup migrations (CMD = uvicorn only); no embedded scheduler.
- Graceful shutdown: lifespan closes Redis then disposes the DB engine.
- Error surface: dual envelopes, no stack traces, `DATABASE_BUSY` 503s.
- Auth surface: Argon2id + HS256 JWT + refresh rotation + sid session check (fail-open w/o Redis) — unchanged.
- CORS: env-driven, mobile unaffected.

## 5. Remaining blockers (deploy-phase)

1. Redis host (CREATING) → fill `REDIS_URL`.
2. SA-JSON vs ADC decision for `PUSH_PROVIDER=fcm` (recommend ADC refactor later; `log` provider works meanwhile).
3. `LOCATION_SERVICE_API_KEY` shared value if SA→EB `/admin/*` calls are needed in dev.
4. Cloud SQL Connector env: `DATABASE_URL` unix-socket form above OR `--add-cloudsql-instances` + socket path — validated at deploy.
5. `GCS` object write smoke-test post-deploy (bucket is ready).
