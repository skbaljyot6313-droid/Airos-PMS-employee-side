# AiROS Staff — codebase index

Employee-facing half of the AiROS property-operations platform (extracted from a
larger management backend). Two deployables:

- `backend/` — FastAPI modular monolith (`AiROS Employee API`), SQLAlchemy 2 async
  + asyncpg → PostgreSQL, Alembic (linear chain, ~50 revisions), optional Redis
  (sessions, rate limits, live-location store), Argon2id + JWT auth.
- `frontend/` — React 19 + TS + Vite + Tailwind 4 + Capacitor 7 Android app
  (`com.theairco.airos.employee`, "AiROS Staff") served by `server.ts` (Express;
  Vite middleware in dev, `dist/` statics in prod).

Detailed docs already exist: `docs/backend_API.md`, `docs/Frontend_API.md`,
`backend/docs/{ARCHITECTURE,EMPLOYEE_DOMAIN,LOCATION_API,MOBILE_COMPATIBILITY,
ENVIRONMENT,API_VERSIONING,EXTRACTION_MANIFEST,FILE_MANIFEST}.md`.

## Run / build / test

- Whole stack (default): `python main.py` → docker compose (postgres:5432,
  redis:6379, migrate→api:8000, web:3000). `python main.py --seed` adds demo
  tenant (`admin@demo.local` / `employee@demo.local`, `Demo!Pass123`).
- Bare-metal dev: `python main.py --native` (uvicorn --reload + `tsx server.ts`,
  optional Android emulator via `cap run`; `--web`, `--backend-only`,
  `--frontend-only`, `--backend-port/--frontend-port` flags).
- Backend tests: `cd backend && python -m pytest` (SQLite in-memory service
  tests; `pytest.ini_options` in `backend/pyproject.toml`, asyncio auto mode).
- Frontend: `npm run dev` (tsx server.ts), `npm run build` (vite), `npm run lint`
  (`tsc --noEmit`), `npm run test` (vitest).
- CI: `.github/workflows/ci.yml` (backend pytest, frontend typecheck+build,
  android assembleRelease). Deploy: `deploy-railway.yml` (`railway up --service
  employee-api`), `release-android.yml` (EAS APK + `POST /mobile/releases`).
- Railway prod API: `https://employee-api-production-c0e3.up.railway.app/api/v1`.

## Backend layout (`backend/app/`)

- `main.py` — app factory, middleware (RequestID → AccessLog →
  SecurityHeaders → GZip → CORS), `/health` `/health/db` `/ready`.
- `api/v1/router.py` — mounts: `auth`, `tasks`, `attendance`, `maintenance`,
  `resources` (`/zones` only), `media`, `notifications` (+`/devices/*`),
  `location`, `admin`, `mobile`.
- `dependencies/auth.py` — `get_current_user` (Bearer→User, Redis `sid`
  session check, fails open), `require_employee`/`require_super_admin`/
  `require_attendance_participant`; service-key gates
  `require_location_service` / `require_release_service` (shared bearer,
  constant-time, fail closed 503 when unset).
- `services/` — business logic: `task.py` (lifecycle + recurrence),
  `maintenance.py` (tickets, coverage, auto-allocation), `structure.py`
  (property/area/zone/room/dorm/washroom CRUD + occupancy-driven cleaning
  tasks — mostly for the wider product, employee API consumes it),
  `work_allocation.py` (zone/area round-robin), `resource_state.py` (sole
  resource-state authority — `transition`/`derive`/`repair`/`explain`),
  `attendance.py` (workday + leave-request review), `location_live.py` +
  `location_tracking.py` (Redis hot path + sessions/history),
  `notifications.py`, `push.py` (log|fcm providers), `rollover.py` (IST
  operational-day rollover — present for models/tests, no scheduler runs
  here), `occupancy.py`, `auth.py`, `mobile_release.py`, `task_location.py`.
- `repositories/` — `workspace.py` (company/property-scoped list reads;
  `list_tasks` enforces `Task.employee_id == user.employee_id` for
  employees), `user.py`, `company.py`, `refresh_token.py`, `attendance.py`.
- `models/` — all ORM (companies, users, refresh_tokens, properties, areas,
  zones, rooms, dorms, beds, washrooms, washroom_fixtures, employees, tasks
  +history/submissions/images, maintenance_tickets +events/attachments,
  occupancies, attendance_days/breaks/requests, notifications,
  device_registrations, location_events, resource_state_events,
  work_allocation_*, work_templates*, audit_events, mobile_releases,
  location_tracking_sessions, shifts + employee_shift_assignments —
  shared tables written by the Super Admin backend; this repo owns the
  migration revision `v9f2b5c8d1e4` in its chain, maps them read-only
  in `models/shift.py`, and serves the caller's own assignment via
  `GET /attendance/shift` (`services/employee_shift.py` — resolution
  mirrors SA's effective_assignments: in-force on today's IST op-day,
  latest effective_from wins; UI route: Profile → My Shift card).
- `domain/` — canonical state vocab (`resource_states.py`), legal
  transitions + source gates (`transitions.py`), event sources
  (`resource_events.py`).
- `schemas/` — unversioned serializers (`*_out` helpers) + `schemas/v1/`
  contract re-exports.
- `core/` — `config.py` (Settings, env-only config), `database.py`,
  `security.py` (Argon2id, HS256 JWT with optional `sid`, SHA-256 refresh
  tokens), `sessions.py` (Redis session registry, fail-open),
  `rate_limit.py` (Redis fixed-window, in-memory fallback, fail-open),
  `redis.py` (`mt:` key prefix convention, accelerator-not-truth),
  `storage.py` (S3-compatible object store only — Supabase Storage's S3
  endpoint; no local-disk backend),
  `exceptions.py` (dual `detail`+`error` envelopes), `middleware.py`,
  `logging.py`.

## API surface (all under `/api/v1`)

- `POST /auth/login|refresh|logout`, `GET|PATCH /auth/me` (login 10/min,
  refresh 30/min).
- `GET /tasks`, `GET /tasks/{id}`, `POST /tasks/{id}/start|submit`.
- `GET|POST /maintenance`, `GET /maintenance/eligible-locations`
  (coverage-scoped picklist for every target kind: `rooms`, `dorms`,
  `beds` (nested under their dorm), `washrooms` (zone- and
  dorm-attached — coverage inherited from the owning dorm), `fixtures`
  (nested under their washroom)), `GET /maintenance/{id}`,
  `POST /maintenance/{id}/start|resolve`.
- `GET /zones` (only routed resource list — `/areas` `/rooms` `/dorms`
  `/washrooms` `/properties` `/employees` exist as serializers/repos but
  have NO v1 routes; frontend tolerates the 404s).
- `POST /media/uploads` (JPEG/PNG/WebP/HEIC MIME, magic-byte check, ≤10MB,
  30/min). `GET /media/file/{key}` (public, 240/min) streams a stored
  object through this origin — serializers emit `/api/v1/media/file/<key>`
  (`proxy_media_url` in storage.py) so devices never fetch from
  supabase.co/CDN hosts they may not reach. Keys are unguessable uuid
  blobs; the regex whitelist makes traversal impossible.
- `GET|POST /attendance/*` — today/start/break/resume/end, calendar,
  requests (+cancel; approve/reject are super_admin-only).
- `POST /location/start|current|stop`, `GET /location/current`
  (Redis-backed, sessions minted server-side, seq dedup).
- `GET /notifications`, `unread-count`, `/{uid}/read`;
  `POST /devices/register|unregister`.
- `GET /mobile/version` (public; `download_url` is the same-origin
  `/api/v1/mobile/apk` proxy path — updateService absolutizes it via
  `mediaUrl`), `GET /mobile/apk` (public, 30/min; streams the active
  binary from storage or server-fetches the stored external URL),
  `POST /mobile/releases[/.../activate]`,
  `PATCH /mobile/releases/{id}` (repoint `download_url` in place),
  `POST /mobile/releases/apk` (self-host the binary in object storage) —
  the release-management endpoints are service-key via
  RELEASE_MANAGEMENT_API_KEY.
- `GET /admin/live-locations`, `GET /admin/location-history/{id}`,
  `POST /admin/notify-allocation` (LOCATION_SERVICE_API_KEY — for the SA
  backend, not employees). notify-allocation receives a SA-side
  allocation event (`ticket_kind`, `ticket_uid`, `employee_uid`,
  `employee_name?`, `previous_employee_uid?`, `event_created_at?`),
  validates the work item is STILL assigned to that employee (stale →
  404), dedupes against same-kind rows at-or-after the event timestamp,
  and creates the notification via NotificationService at allocation
  time — the ledger-based feed synthesis in `list_notifications` remains
  the backstop for calls that never arrive.

## Frontend layout (`frontend/src/`)

- `api/client.ts` — sole fetch boundary; localStorage tokens
  (`airos_staff_access_token`/`_refresh_token`), single-flight 401 refresh,
  `airos_unauthorized` event → forced sign-out. `api/wire.ts` = wire DTOs;
  per-domain `api/*.ts` map wire → display types in `types/index.ts`.
- `context/AuthContext.tsx` — session restore, employee-role gate
  (`authGate.ts`), enrichment.
- `App.tsx` — manual `StackRoute` router (tabs | task-detail |
  zone-workspace | maintenance-new | maintenance-detail); `BottomNav` tabs:
  Tasks / Maintenance / Attendance / Profile. `UpdateManager` gates on
  forced updates.
- `screens/employee/` — TasksScreen, TaskDetailScreen, MaintenanceScreen,
  ZoneWorkspaceScreen, MaintenanceNewScreen, MaintenanceDetailScreen,
  AttendanceScreen, ProfileScreen; `screens/auth/LoginScreen.tsx`.
- `services/` — `locationTracker.ts` (orchestrates native tracking;
  web no-op), `nativeLocation.ts` + `updateInstaller.ts` (Capacitor plugin
  bridges), `updateService.ts` (versionCode compare, 4h throttle, pending
  APK reconcile).
- `android/app/src/main/java/com/airos/staff/` — `LocationTrackingService`
  (foreground FGS + Fused Location Provider + on-disk JSONL retry queue +
  self-refresh on 401 + session re-mint on INVALID_TRACKING_SESSION),
  `LocationTrackerPlugin` (`AirosLocation`), `AppUpdatePlugin`
  (`AirosUpdate` — APK download/install), `MainActivity`.
- Version source of truth: `app.json` (`expo.version` +
  `expo.android.versionCode`); `scripts/bump-version.mjs` bumps it.

## Conventions & invariants

- IDs on the wire are `*_uid` strings; lists envelope `{items,total,page,limit}`.
- Business dates are IST wall-clock `YYYY-MM-DD` strings
  (`operational_day_start`, default 06:00); never UTC-slice on the client
  (`api/attendance.ts` `businessDate`).
- `visual_state` on resources is server-computed — the frontend renders it,
  never derives it. `ResourceStateService` is the only state writer.
- Employees cannot self-complete work: tasks → `submitted` (PENDING_CHECK),
  tickets → `resolved`; only super_admin approves/closes (release point).
- Tenant scope = caller's `company_id`/`property_id`; employee coverage =
  `zone_id` ∪ zones inside `area_id` ∪ matching `area_id` resources.
- Redis is an accelerator, never truth — everything degrades/fails open
  except `/location/*` ingest and `/admin/*` which need it (503 honest).
- Error envelopes: `{detail:{message,code,field?}}` AND `{error:{code,message}}`.
- Migrations: full linear Alembic chain retained; apply via
  `alembic upgrade head` (compose `migrate` service / Railway preDeploy).
