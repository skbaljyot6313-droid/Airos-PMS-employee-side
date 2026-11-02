# AiROS Employee Backend — Deployment Audit (Phase 0)

Date: 2026-11-02 · Branch: `development-branch` · Commit base `309528d`
+ uncommitted work (36 files, preserved).

Scope: Employee repository only. Super Admin codebase untouched.
This document contains **no secret values** — only names/references.

## 1. Application profile

| Item | Finding |
|---|---|
| Framework | FastAPI ≥0.115, app title `Airco PMS Employee API`, version 1.0.0 |
| Entrypoint | `backend/app/main.py` — module-level `app` (factory-style lifespan, no app factory fn) |
| ASGI server | `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers` (from `backend/Dockerfile` CMD) |
| Python | `python:3.12-slim` image; `requires-python >=3.11` |
| Deps | `backend/requirements.txt` (no lockfile — floors only): fastapi, uvicorn[standard], sqlalchemy[asyncio], asyncpg, alembic, pydantic(-settings), python-dotenv, argon2-cffi, pyjwt, redis, arq, boto3, python-multipart, cryptography, tzdata + test deps |
| Dockerfile | `backend/Dockerfile` — slim, non-root `appuser`, `HEALTHCHECK` hits `/health`, `EXPOSE $PORT`. **No CMD-time migrations** (migrations are a separate compose `migrate` service — good for Cloud Run) |
| App factory | `app/main.py`: middleware RequestID → AccessLog → SecurityHeaders → GZip → CORS; routes under `settings.API_V1_PREFIX` (`/api/v1`); `/health`, `/health/db`, `/ready`; exception handlers |
| Middleware | custom RequestID/AccessLog/SecurityHeaders + FastAPI GZip/CORS; CORS from `CORS_ORIGINS` env |

## 2. Persistence & data

| Item | Finding |
|---|---|
| ORM | SQLAlchemy 2 async, `AsyncEngine` + `async_sessionmaker`, `TimedAsyncSession` (metrics) |
| DB driver | asyncpg; `postgresql://` auto-normalized to `+asyncpg`; pgbouncer detection (`"pooler" in host`) disables prepared-statement cache — **irrelevant on Cloud SQL, harmless** |
| Pool | `DB_POOL_SIZE=2`, `DB_MAX_OVERFLOW=1`, `DB_POOL_TIMEOUT=10`, `DB_POOL_RECYCLE=900`, `DB_POOL_PRE_PING=true` — bounded per process; engine disposed at lifespan shutdown |
| Alembic | `backend/alembic/` + `alembic.ini`; `env.py` builds URL from `settings.database_url` (never hardcoded); `target_metadata = Base.metadata`; **42 revisions, single linear chain, single head `v9f2b5c8d1e4`** |
| Alembic autostart | **None** — no `alembic upgrade` in Dockerfile/app startup. Migrations are manual/`compose migrate` only. Safe for Cloud Run |
| Models | ~24 tables: companies, users, refresh_tokens, properties, areas, zones, rooms, dorms, beds, washrooms, washroom_fixtures, employees, tasks+history+submissions+images, maintenance_tickets+events+attachments, occupancies, attendance_days/breaks/requests, notifications, device_registrations, location_events, resource_state_events, work_allocation_* , work_templates*, audit_events, mobile_releases, location_tracking_sessions, **shifts + employee_shift_assignments (read-only, owned by SA)** |

## 3. Auth & security

| Item | Finding |
|---|---|
| Password hashing | Argon2id via `argon2-cffi` (`core/security.py`) |
| JWT | HS256 (`JWT_ALGORITHM`), `JWT_SECRET_KEY` env, `sub`/`sid`/`role`/`company_id` claims; access 30min, refresh 30d (SHA-256 stored) |
| Sessions | Redis `sid` registry (`core/sessions.py`) — **fail-open** when Redis down (revocation check skipped, JWT still validated) |
| RBAC | `require_role` — super_admin / property_manager / employee (+ attendance participant); `get_tracking_principal` lightweight variant for location ingest |
| Rate limit | `core/rate_limit.py` — Redis fixed-window, in-memory fallback, fail-open |
| Service keys | `LOCATION_SERVICE_API_KEY`, `RELEASE_MANAGEMENT_API_KEY` — constant-time compare, fail-closed 503 |
| Errors | dual envelope `{detail:{message,code,field?}}` + `{error:{code,message}}`; SQLAlchemy → 503 `DATABASE_BUSY`/`DATABASE_ERROR` (no stack traces); unhandled → 500 generic in prod |
| Media | S3-only (`core/storage.py`), MIME+magic-byte check, ≤10MB, `/media/file/{key}` streams through API origin |

## 4. External service dependencies

| Dependency | Startup-critical? | Behavior when absent |
|---|---|---|
| PostgreSQL | **YES** — `settings.database_url` required (raises at import) | App won't boot; `/health/db` 503s |
| Redis | NO — accelerator | Sessions/rate-limit/user-cache fail open; **`/location/*` + `/admin/*` return 503** (honest — live location is Redis-only) |
| S3 object storage | Partial — app boots without | `/media/uploads`, `/media/file`, `/mobile/apk` fail; everything else works |
| Centrifugo | NO | `/realtime/*` 503s; frontend falls back to 45s polling |
| FCM | NO — `PUSH_PROVIDER=log` stub default | `FCMProvider.from_settings` raises only if `fcm` selected w/o creds; `log` provider always works |
| arq worker | NO — dep installed, no worker wired | `RUN_EMBEDDED_SCHEDULER` exists; **no scheduler code runs in this service** (rollover exists for SA-owned cron; compose sets `RUN_EMBEDDED_SCHEDULER=false`) |

## 5. Forbidden-reference scan

| Pattern | Hits |
|---|---|
| `railway` / `up.railway` in `app/` | 0 code refs (docs/comments only) |
| `supabase.co` in `app/` | 3 comments only (`media.py`, `mobile.py`, `storage.py` — describing unreachable-host fallback, no URLs) |
| Hardcoded external endpoints | `FCM_V1_URL` (`fcm.googleapis.com`) — legit Google API; no other external URLs |
| Hardcoded credentials | **NONE** — all secrets env-only via `Settings` |
| Local filesystem storage | None — storage is S3-only by design (no local backend exists) |
| Embedded scheduler | `RUN_EMBEDDED_SCHEDULER` flag exists; no scheduler loop in this service — flag is config-compat only |
| Production URLs | Dead doc references only (AGENTS.md, `location_api.md`) — no code |

## 6. Required GCP env summary (for Phase 3)

**Mandatory at startup:** `DATABASE_URL` (or `SUPABASE_DB_*` parts — replace with `postgresql+asyncpg://airos_eb_app:***@/airos_dev?host=/cloudsql/final-airos-os:asia-south1:airos-postgres-dev/.s.PGSQL.5432` via Cloud SQL unix socket), `JWT_SECRET_KEY` (reuse `airos-dev-jwt-secret` — shared with SA's dev JWTs).
**Recommended:** `REDIS_URL` (absent → `/location/*`+`/admin/*` 503, acceptable dev degradation), `S3_*` → **replace with GCS or leave unconfigured** (uploads fail otherwise), `LOCATION_SERVICE_API_KEY` (if SA calls `/admin/*`), `APP_ENV=production`, `DEBUG=false`, `CORS_ORIGINS` (mobile doesn't need CORS — web admin origin only), `USER_CACHE_TTL_S`, `BOOTSTRAP_ENABLED`.
**Optional:** `CENTRIFUGO_*` (realtime), `PUSH_PROVIDER=fcm` + `FCM_PROJECT_ID` + `FCM_SERVICE_ACCOUNT_JSON` (→ prefer ADC via runtime SA instead — code needs `google-auth` refactor or SA-JSON-in-Secret-Manager), `PERF_HEADERS_ENABLED=false`.
**Storage decision needed:** existing code is S3-shaped (boto3) — GCS interop keys OR `google-cloud-storage` refactor (see Phase 3 findings).
