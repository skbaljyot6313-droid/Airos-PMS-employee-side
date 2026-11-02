# AiROS Employee — Final Pre-Deployment Readiness

Date: 2026-11-02 · Branch `development-branch` · Project `final-airos-os` / asia-south1. **NOT DEPLOYED.** No secret values appear here.

## Dependency classification

| # | Dependency | Status |
|---|---|---|
| 1 | Redis `airos-redis-dev` | **BLOCKED (provisioning)** |
| 2 | FCM push | READY WITH LIMITATIONS |
| 3 | `LOCATION_SERVICE_API_KEY` | BLOCKED (by design — non-core) |
| 4 | GCS storage | READY |
| 5 | DB role + schema | READY |
| 6 | Env config | READY |
| 7 | Docker image | READY |

## T1 — Redis: BLOCKED (provisioning)

`airos-redis-dev`: BASIC 1GB, redis_7_2, `default` VPC, `connectMode=DIRECT_PEERING`, port 6379 — **state: `CREATING` at last check; host IP not yet assigned** (Memorystore first-create on a fresh VPC can take 20-40 min). No public exposure. `REDIS_URL=redis://<host>:6379` fills once issued — the exact `gcloud redis describe` command is in the Phase-3 doc. Cloud Run reaches it via **direct VPC egress** (approved path; no connector). App tolerates absence: sessions/rate-limit/user-cache fail open; only `/location/*`+`/admin/*` 503. **Do not deploy-time-gate on Redis** — set `REDIS_URL` post-deploy or wait for READY.

## T2 — FCM: READY WITH LIMITATIONS

`FCMProvider` refactored to `google-auth` ADC: `google.auth.default(scopes=[firebase.messaging])` on Cloud Run uses `airos-eb-dev-runtime` (has `firebasecloudmessaging.admin` → `messages.create`); optional `FCM_SERVICE_ACCOUNT_JSON` fallback retained for non-GCP envs. Token caching/refresh via `creds.refresh()`. Payload format + dead-token handling (`UNREGISTERED`/`INVALID_ARGUMENT`/`NOT_FOUND` → `invalid_tokens`) unchanged; data-only messages preserved. Requires `PUSH_PROVIDER=fcm` + `FCM_PROJECT_ID=final-airos-os`. **Not verified end-to-end** — no device/token test run (spec: no test notifications); init path validated by code inspection only. `log` provider remains the safe default until a real device test passes.

## T3 — Location service: BLOCKED (non-core)

No `LOCATION_SERVICE_API_KEY` exists in Secret Manager and none was minted (would require coordinating the shared value with the SA backend — out of scope). Effect: `/admin/live-locations`, `/admin/location-history`, `/admin/notify-allocation` return **503 fail-closed** — exactly the documented degraded response; auth is NOT weakened. **Core employee app unaffected** — mobile never calls `/admin/*`. Blocker category: SA→EB integration only.

## T4 — GCS: READY

- Bucket `final-airos-os-dev-employee-objects-94363806721`: private, uniform access, public-access-prevention enforced, STANDARD/asia-south1.
- `GCSStorage` (google-cloud-storage + ADC) active when `GCS_BUCKET` set — **S3 code path is unreachable in dev config** (leave `S3_*` unset; `GCSStorage.__init__` raises clearly if misconfigured — no silent provider switch). No ephemeral/local storage exists.
- `save/delete/open` interface + `/media/file/{key}` proxy preserved; `storage_key_from_url` maps `storage.googleapis.com/<bucket>/<key>`; no public/signed URLs needed for reads (server-side streaming after auth). Runtime SA holds bucket-scoped `storage.objectAdmin`.

## T5 — DB: READY

`airos_eb_app` verified least-privilege (LOGIN + matrix grants; no DDL/superuser). `airos_sa_app`/`postgres` untouched. `alembic_version = v9f2b5c8d1e4` unchanged — **zero migrations needed/run**. No startup migration path exists in the app.

**Combined connection budget:** SA (~4 inst × ~3) + EB (4 inst × (2+1)) + migrate job + admin ≈ **≤20** vs db-custom-1-3840 limit (~100+) — safe headroom. 1 uvicorn worker; engine disposed on shutdown.

## T6 — Final env matrix (verified names against `Settings`)

| Var | Source | Req | Verified |
|---|---|---|---|
| `APP_ENV=production`, `DEBUG=false`, `PORT` | deploy env | Y | ✓ |
| `DATABASE_URL` | `postgresql+asyncpg://airos_eb_app@/airos_dev?host=/cloudsql/…/.s.PGSQL.5432` + `${SUPABASE_DB_PASSWORD}` slot | Y | form verified; live connect at deploy |
| `SUPABASE_DB_PASSWORD` | secret `airos-dev-eb-db-password` | Y | ✓ secret exists |
| `JWT_SECRET_KEY` | secret `airos-dev-eb-jwt-secret` (dedicated) | Y | ✓ |
| `REDIS_URL` | `redis://<host>:6379` | recommended | **pending host** |
| `GCS_BUCKET` | `final-airos-os-dev-employee-objects-94363806721` | for uploads | ✓ |
| `PUSH_PROVIDER` / `FCM_PROJECT_ID` | `log`→`fcm` / `final-airos-os` | opt | init verified |
| `LOCATION_SERVICE_API_KEY` | none — unset → `/admin/*` 503 | opt | documented |
| `CORS_ORIGINS` | dev web origins only | Y | set at deploy |
| `RUN_EMBEDDED_SCHEDULER=false` | explicit | Y | ✓ |
| `USER_CACHE_TTL_S`, `BOOTSTRAP_ENABLED`, `PERF_HEADERS_ENABLED=false`, pool vars | defaults | — | ✓ |
| `S3_*`, `CENTRIFUGO_*`, `STORAGE_BACKEND` | unset | — | S3 unreachable |

No production fallback, no external storage fallback, no startup migrations, no schedulers.

## T7 — Docker: READY

Rebuild `airos-eb-api-dev:local` — SUCCESS (cached layers, google-cloud-storage 3.17.1 + google-auth present). Container boot with prod env: `/health` → `{"status":"ok"}` · `/ready` → **503** (DB unreachable locally — correct honest readiness) · non-root **uid 10001** · clean shutdown. DB/Redis/GCS live-connectivity proven earlier via Cloud SQL Connector + IAM bindings; full e2e connectivity verifies post-deploy.

## Costs (monthly, dev)

Redis ~₹3,000 · GCS <₹85 · Cloud Run 2vCPU/1GiB min-1 ~₹2,500-3,800 · secrets/IAM ~₹0 → **≈ ₹3,100 now; ≈ ₹5,600-6,900 after deploy.**

## Outstanding blockers → deploy gate

1. Redis host pending (CREATING) — set `REDIS_URL` when READY; app is safe without it meanwhile.
2. `LOCATION_SERVICE_API_KEY` — needs SA coordination; only affects `/admin/*`.
3. FCM end-to-end device test — post-deploy, authorized test device only.
4. Cloud Run deploy approval — **this gate.**

**STOPPED — awaiting explicit deployment authorization.**
