# AiROS Employee — Final Deployment Authorization Review

Date: 2026-11-02 · Read-only review. Nothing deployed, migrated, or
modified. Branch `development-branch`; all prior work preserved.

## 1. Redis — READY

`airos-redis-dev`: **READY** · `10.43.178.219:6379` · BASIC 1GB ·
DIRECT_PEERING on `default` VPC (asia-south1) · no public IP.
`REDIS_URL=redis://10.43.178.219:6379` (verified host — not guessed).
Cloud Run reaches it via **direct VPC egress** (`--network=default
--subnet=default --vpc-egress=private-ranges-only`) — no VPC connector.
Runtime SA needs no special IAM for Redis (network-layer access).

## 2. Readiness/health semantics — SAFE DEGRADED OK

- `/health`: liveness only (process up) — safe for Cloud Run startup.
- `/ready`: checks DB (and reports Redis/S3 flags) → 503 **does not
  block Cloud Run traffic** (Cloud Run probes `/health`-style TCP/start;
  `/ready` is informational unless wired as a startup probe — it is not).
- Redis is **not** startup-mandatory — app boots without it; only
  `/location/*`+`/admin/*` 503 in its absence. No contract change needed.
- No artificial-success changes made or proposed.

## 3. FCM — READY (log by default)

`FCMProvider` → `google-auth` **ADC** on `airos-eb-dev-runtime`
(`firebasecloudmessaging.admin` grants `messages.create`). SA-JSON path
only activates if `FCM_SERVICE_ACCOUNT_JSON` env is set — **leave it
unset** so ADC can't be shadowed. `PUSH_PROVIDER` stays `log` until an
authorized device test flips it to `fcm`. No notifications sent.

## 4. Location integration — fail-closed, non-core

`LOCATION_SERVICE_API_KEY` unset → `/admin/live-locations`,
`/admin/location-history/*`, `/admin/notify-allocation` → 503
(constant-time gate, fail closed — auth not bypassed). Zero employee
routes depend on them; the mobile app never calls `/admin/*`. No key
invented — needs SA-side coordination to mint a shared dev value.

## 5. Infrastructure re-verified

- `alembic_version` = `v9f2b5c8d1e4` — unchanged; **no migrations run**.
- Roles: `airos_eb_app` (least-privilege), `airos_sa_app`, `postgres` —
  SA/postgres grants untouched.
- GCS: private bucket, uniform access, PAP, ADC via runtime SA
  (`storage.objectAdmin` bucket-scoped); `GCSStorage` selected by
  `GCS_BUCKET` — S3 unreachable with `S3_*` unset; no local storage.
- Secrets referenced: `airos-dev-eb-db-password`, `airos-dev-eb-jwt-secret`
  (secret-level `secretAccessor` on the runtime SA).
- DB budget: SA (~12) + EB (4×3) + migrate+admin ≈ ≤20 vs ~100 limit.
- Docker image: builds clean, non-root uid 10001, `/health` OK,
  `/ready` honest-503 locally, clean engine disposal.

## 6. Proposed deploy configuration (pending approval)

```
gcloud run deploy airos-eb-api-dev \
  --image=asia-south1-docker.pkg.dev/final-airos-os/airos-dev/airos-eb-api-dev:<tag> \
  --region=asia-south1 --service-account=airos-eb-dev-runtime@final-airos-os.iam.gserviceaccount.com \
  --add-cloudsql-instances=final-airos-os:asia-south1:airos-postgres-dev \
  --network=default --subnet=default --vpc-egress=private-ranges-only \
  --cpu=2 --memory=1Gi --min-instances=1 --max-instances=4 --concurrency=20 \
  --allow-unauthenticated \
  --set-env-vars='APP_ENV=production,DEBUG=false,REDIS_URL=redis://10.43.178.219:6379,GCS_BUCKET=final-airos-os-dev-employee-objects-94363806721,PUSH_PROVIDER=log,RUN_EMBEDDED_SCHEDULER=false,CORS_ORIGINS=<dev-origins>,DATABASE_URL=postgresql+asyncpg://airos_eb_app@/airos_dev?host=/cloudsql/final-airos-os:asia-south1:airos-postgres-dev/.s.PGSQL.5432&user=airos_eb_app' \
  --set-secrets='SUPABASE_DB_PASSWORD=airos-dev-eb-db-password:latest,JWT_SECRET_KEY=airos-dev-eb-jwt-secret:latest'
```
(Image push to AR required first: `docker tag` + `docker push` with
`gcloud auth configure-docker`.) Unauthenticated at infra layer — app
JWT gates every route; mobile clients can't hold ID tokens.

## 7. Remaining blockers

1. `LOCATION_SERVICE_API_KEY` shared dev value — SA coordination; only `/admin/*`.
2. FCM real-device test — post-deploy; `log` provider until then.
3. Live DB connectivity from Cloud Run — first-connect verify at deploy
   (unix-socket `DATABASE_URL` + `--add-cloudsql-instances`).

## 8. Monthly cost

Redis ≈ ₹3,000 · GCS <₹85 · Cloud Run 2vCPU/1GiB min-1 ≈ ₹2,500–3,800 ·
secrets ~₹0 → **≈ ₹5,600–6,900 total after deploy.**

## FINAL RECOMMENDATION: **READY** (with Redis IP now assigned; the only
open items are the two non-core integrations above, both fail-closed).

**STOPPED — awaiting explicit Cloud Run deployment authorization.**
