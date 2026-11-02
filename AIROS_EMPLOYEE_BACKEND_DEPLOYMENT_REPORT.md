# AiROS Employee Backend — Deployment Report

Deployed 2026-11-02 · Project `final-airos-os` (94363806721) · `asia-south1`.

## Service

| Field | Value |
|---|---|
| URL | `https://airos-eb-api-dev-94363806721.asia-south1.run.app` |
| Revision | `airos-eb-api-dev-00001-szm` (100% traffic) |
| Image | `asia-south1-docker.pkg.dev/final-airos-os/airos-dev/airos-eb-api-dev:309528d` |
| Digest | `sha256:6099603c96fd00fb38972e8ea43ed0efb15ccd4c145a29f18bd8b7b24c81ded8` |
| Sizing | 2 vCPU / 1GiB · min 1 / max 4 · concurrency 20 |
| Runtime SA | `airos-eb-dev-runtime@final-airos-os.iam.gserviceaccount.com` |
| Networking | Cloud SQL attachment `airos-postgres-dev` + direct VPC egress `default`/`private-ranges-only` |
| Ingress | `--allow-unauthenticated` (infra layer); app JWT enforces auth on every protected route |

## Verified live results (real calls)

| Check | Result |
|---|---|
| `GET /health` | **200** `{"status":"ok","env":"production"}` |
| `GET /ready` | **200** `database: connected, redis: connected` |
| `POST /auth/login` (bad body) | 422 schema validation — endpoint live |
| `GET /tasks` (no token) | **401 UNAUTHENTICATED** — auth enforced |
| `GET /mobile/version?platform=android` | 200 real release row (1.0.0/vc1, pre-existing in shared dev DB) |
| `GET /admin/live-locations` | 503 `LIVE_LOCATION_UNAVAILABLE` — fail-closed as designed |

## Shared resources (verified)

- **Database:** `airos_dev` on `airos-postgres-dev` — the SAME instance/DB as SA. App connects as `airos_eb_app` via unix socket (`/cloudsql/…/.s.PGSQL.5432`), secrets via `airos-dev-eb-database-url` + `airos-dev-eb-jwt-secret` (Secret Manager, secret-level accessor on runtime SA). Alembic head `v9f2b5c8d1e4` — **no migrations run**; `airos_sa_app`/`postgres` untouched.
- **GCS:** SA's deployed env uses `STORAGE_BACKEND=local` (ephemeral) — **no pre-existing SA bucket exists**. The project's sole app bucket `final-airos-os-dev-employee-objects-94363806721` is the designated dev objects bucket; EB uses it via `GCSStorage`+ADC (bucket-scoped `storage.objectAdmin`). Zero collision with SA objects (none exist). SA→bucket grant is a documented follow-up when SA migrates off local storage.
- **Redis:** `airos-redis-dev` `10.43.178.219:6379`, DIRECT_PEERING — **live-connected** (see `/ready`).

## FCM / location

`PUSH_PROVIDER=log` (ADC path ready via runtime SA; flips to `fcm` after authorized device test — `FCM_PROJECT_ID=final-airos-os`). `LOCATION_SERVICE_API_KEY` unset → `/admin/*` 503 fail-closed; core employee flows unaffected. No key invented.

## Mobile display name

`frontend/app.json` `"name"` + `android/app/.../strings.xml` `app_name` → **"Airos Property Pro"**. Package `com.theairco.airos.employee`, versionName 1.0.14, vc16 unchanged. No iOS project exists. No build/distribution performed.

## Budget & cost

Combined pool ≤20 vs ~100 limit. Monthly ≈ **₹5,600–6,900** (Cloud Run ~₹2,500–3,800 + Redis ~₹3,000 + GCS <₹85).

## Follow-ups

1. `LOCATION_SERVICE_API_KEY` shared dev value (SA coordination) for `/admin/*`.
2. FCM device test → `PUSH_PROVIDER=fcm`.
3. SA GCS migration → grant `airos-sa-dev-runtime` bucket-scoped access to the same bucket.
4. Real-device APK e2e: login → tasks → attendance → uploads vs this URL.
