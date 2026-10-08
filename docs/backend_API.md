# AiROS Employee Backend — API Documentation

Deep index of `production/employee/backend` — a FastAPI modular monolith serving the AiROS Staff mobile/web frontend. Extracted from the AiROS management backend; preserves the existing PostgreSQL schema, JWT auth, and wire contracts (`*_uid` keys, snake_case).

**Stack:** FastAPI · SQLAlchemy 2 async (asyncpg) · PostgreSQL (Supabase-compatible) · Alembic · Argon2id · PyJWT (HS256) · optional Redis (rate limiting) · S3/Supabase/local media storage.
**API root:** `{origin}/api/v1` (`API_V1_PREFIX`). OpenAPI at `/docs` + `/openapi.json` (disabled in production).
**Media:** uploaded files served from `{origin}/uploads/*` (local backend) or an object-store URL.

---

## 1. Project Layout

```
app/
├── main.py                    # FastAPI app, middleware, /health /health/db /ready, /uploads mount
├── api/v1/
│   ├── router.py              # aggregates: auth, tasks, maintenance, resources, media
│   ├── auth.py                # /auth/login /refresh /logout /me (GET+PATCH)
│   ├── tasks.py               # /tasks list/detail/start/submit
│   ├── maintenance.py         # /maintenance list/detail/create/start/resolve + eligible-locations
│   ├── resources.py           # /zones only
│   └── media.py               # /media/uploads
├── dependencies/auth.py       # Bearer → User; role guards (get_current_user, require_*)
├── services/                  # auth, task, maintenance, structure, occupancy,
│                              # resource_state, work_allocation, task_location
├── repositories/              # workspace (scoped reads), user, company, refresh_token
├── schemas/                   # unversioned DTOs + serializers; schemas/v1 re-exports
├── models/                    # SQLAlchemy ORM (existing AiROS schema)
├── domain/                    # resource_states, transitions, resource_events
└── core/                      # config, database, security, exceptions, rate_limit,
                               # storage, redis, logging, middleware
```

**Request flow:** `route → service → repository/ORM → PostgreSQL`. Routes hold HTTP concerns only; services own lifecycle rules; repositories own tenant-scoped reads.

**Health probes (root, not under `/api/v1`):**

| Method | Path | Purpose | Response |
|---|---|---|---|
| GET | `/health` | Liveness | `{status:"ok", service, env}` |
| GET | `/health/db` | DB connectivity (`SELECT 1`, 10 s bound) | `200 {status:"ok",database:"connected"}` · `503 DATABASE_UNAVAILABLE` |
| GET | `/ready` | DB + Redis readiness | `200` ok / `503` degraded `{status, database, redis}` |

---

## 2. Configuration (env)

All config flows through `app/core/config.py` `Settings` — no module reads `os.getenv` directly.

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | `production` disables `/docs`, adds HSTS, enables prod warnings |
| `API_V1_PREFIX` | `/api/v1` | Mount point for the v1 router |
| `DATABASE_URL` | — | Full async URL; `postgresql://` auto-normalized to `postgresql+asyncpg://`; `${SUPABASE_DB_PASSWORD}` placeholder supported |
| `SUPABASE_DB_HOST/PORT/NAME/USER/PASSWORD` | `5432`/`postgres`/`postgres` | Alternative: build the URL from parts |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` / `DB_POOL_RECYCLE` / `DB_POOL_TIMEOUT` | `5`/`5`/`1800`/`30` | Pool tuning; pooler hosts auto-disable prepared-statement cache |
| `JWT_SECRET_KEY` | **required** | HS256 signing key |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | JWT `exp` |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `30` | Refresh-token row expiry |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowlist |
| `REDIS_URL` | unset | Enables Redis fixed-window rate limiting; otherwise in-memory per-process fallback (fails open) |
| `RATE_LIMIT_ENABLED` | `true` | Master switch |
| `STORAGE_BACKEND` | `auto` | `auto` prefers S3 → Supabase → local; `local`/`s3`/`supabase` force |
| `UPLOAD_DIR` | `uploads` | Local storage root (mounted at `/uploads`) |
| `MAX_TASK_COMPLETION_IMAGES` | `10` | Server-side cap on evidence photos per submission |
| `S3_*` / `SUPABASE_*` | — | Object storage credentials (`S3_BUCKET`, keys, `S3_ENDPOINT_URL`, `S3_PUBLIC_BASE_URL`, `SUPABASE_STORAGE_BUCKET`) |
| `SQL_ECHO` | `false` | Log all SQL (dev only) |
| `DEBUG` | `true` | Leaks exception detail only when true **and** non-production |

---

## 3. Authentication & Authorization

### Tokens

- **Access token:** JWT HS256. Claims: `sub`/`user_id`, `company_id`, `role`, `iat`, `exp`, `type:"access"`. Sent as `Authorization: Bearer <token>`.
- **Refresh token:** opaque `secrets.token_urlsafe(48)`; stored **SHA-256 hashed** in `refresh_tokens` with expiry; revoked on logout.
- `decode_access_token` never raises — invalid/expired → `401 UNAUTHENTICATED`.

### `get_current_user` (every authenticated route)

Bearer → decode → `sub` as UUID → load `User` → `user.is_active` required → `401` otherwise.

### Roles (`UserRole` — wire strings match frontend exactly)

`super_admin` · `property_manager` · `human_resource` · `department_manager` · `employee`

| Guard | Allows | Used on |
|---|---|---|
| `get_current_user` | any active user | all authenticated routes |
| `require_employee` | super_admin, property_manager, employee | `POST /maintenance` |
| `require_property_manager` / `require_super_admin` | staff | (present, unused by v1 routes) |

### Tenant & actor scoping (server-enforced)

- `company_id`/`property_id` of the **caller** is the tenant scope — client-supplied IDs are never trusted (`WorkspaceRepository._company_scope`; `_property_for_write` → `404` on cross-property).
- **Tasks:** employees only ever see/act on `Task.employee_id == user.employee_id` (list + detail + lifecycle). `403 FORBIDDEN` otherwise.
- **Maintenance:** employees see tickets `assigned_to == employee_id` OR `reported_by == user.id`; create enforces **zone/area coverage** (`_enforce_employee_coverage` → `403`).
- **Review/closure** decisions that release a resource (approve, reject, close, disapprove, cancel, delete) are **super_admin-only** (`_require_resource_authority` / `_require_release_authority`) — not exposed on v1 routes but enforced in services.

### Rate limiting

Fixed-window by client IP (X-Forwarded-For trusted from proxy): **`login` 10/min**, **`refresh` 30/min**, **`upload` 30/min**. Over-limit → `429 RATE_LIMITED`. Redis when configured, else in-memory; **fails open** on Redis errors.

### Middleware

`RequestIDMiddleware` (echoes/accepts `X-Request-ID`) → `AccessLogMiddleware` (`X-Response-Time`, structured log w/ user+company from JWT) → `SecurityHeadersMiddleware` (`nosniff`, `DENY`, referrer, permissions-policy; HSTS in prod) → `GZipMiddleware` (≥500 B) → `CORSMiddleware` (allowlist, credentials).

---

## 4. Wire Conventions

- IDs serialize as `*_uid` strings (UUIDs); internal FK columns are `*_id`.
- List envelope: `{ items: [...], total: int, page: 1, limit: 20 }` (page/limit are metadata — lists return the full scoped set; `GET /tasks` honors `limit` as a fetch bound only).
- **Two error envelopes are emitted together:**
  - `{"detail": {"message", "code", "field?"}}` — FastAPI-style, what the frontend reads
  - `{"error": {"code", "message"}}` — structured variant
  - 422 validation → `{"detail": [{loc: [...], msg, type}], "error": {...}}`; field name = `loc[-1]`
- **Media URLs:** local storage returns relative `/uploads/<key>`; S3/Supabase return absolute URLs. Clients resolve relative paths against the API origin.
- Datetimes: ISO 8601, UTC (`resolved_at`, `closed_at`, `created_at`…). `due_date`/`due_time`/`start_time` are **naive IST wall-clock strings** (recurrence math runs in `Asia/Kolkata`).

### Error codes catalog

| Code | HTTP | Raised when |
|---|---|---|
| `UNAUTHENTICATED` | 401 | Missing/invalid/expired Bearer, inactive user |
| `INVALID_CREDENTIALS` | 401 | Bad identifier/password (uniform — never reveals which) |
| `INVALID_REFRESH_TOKEN` | 401 | Refresh token unknown/expired/user inactive |
| `FORBIDDEN` | 403 | Role/scope/coverage violation; inactive role guards |
| `ACCOUNT_INACTIVE` | 403 | `is_active=false` at login |
| `EMAIL_ALREADY_EXISTS` | 409 | PATCH `/auth/me` email collision |
| `NOT_FOUND` | 404 | Entity missing or outside tenant/property scope |
| `CONFLICT` | 409 | Illegal lifecycle transition (wrong current status, expired occurrence, terminal state) |
| `VALIDATION_ERROR` | 422 | Domain validation failure (`field` set) — also Pydantic 422s |
| `INVALID_UPLOAD` | 422 | Bad MIME, oversized, empty, or signature-mismatched upload (`field:"photos"`) |
| `RATE_LIMITED` | 429 | Rate limit hit |
| `STORAGE_UNAVAILABLE` | 502 | Object store save failed |
| `DATABASE_ERROR` / `DATABASE_UNAVAILABLE` | 503 | SQL failure / connectivity (DNS, refused, timeout, TLS) |
| `INTERNAL_ERROR` | 500 | Unhandled (message hidden in prod) |

---

## 5. Endpoint Reference

### 5.1 Auth — `/api/v1/auth`

#### `POST /auth/login` — rate-limited 10/min/IP
**Body** `LoginRequest`: `{ identifier: str (email OR username, 1–255), password: str (1–128) }`
**200** `AuthResponse`:
```json
{
  "access_token": "<jwt>",
  "refresh_token": "<opaque>",
  "token_type": "bearer",
  "user":    { "uid", "name", "email", "username", "role",
               "company_uid", "property_uid?", "employee_uid?", "zone_uid?",
               "phone?", "job_title?", "company_name?" },
  "company": { "company_uid", "name", "legal_name?", "brand_name", "email",
               "phone", "address?", "pin_code?", "operational_day_start", "created_at" }
}
```
**Errors:** `401 INVALID_CREDENTIALS` · `403 ACCOUNT_INACTIVE`. On success: `last_login_at` stamped; refresh-token row persisted in the same transaction.

#### `POST /auth/refresh` — rate-limited 30/min/IP
**Body** `{ refresh_token: str }` → **200** `{ access_token, token_type:"bearer" }`. Looks up hashed token; rejects unknown/expired/inactive-user tokens (`401 INVALID_REFRESH_TOKEN`). No rotation — issues a new access token only.

#### `POST /auth/logout`
**Body** `{ refresh_token: str|null }` → **204**. Revokes the hashed refresh row; null/absent is a silent no-op.

#### `GET /auth/me`
Auth required → **200** `MeResponse { user, company }` (same shapes as login). Session-restore endpoint.

#### `PATCH /auth/me`
Auth required. **Body** `UpdateProfileRequest`: `{ name?: str (1–255), phone?: str (alias phone_number), email?: str (validated, lowercased) }` → **200** `UserOut` (same `user` shape). `409 EMAIL_ALREADY_EXISTS` on collision; `422` on invalid email.

---

### 5.2 Tasks — `/api/v1/tasks` (all require Bearer)

#### `GET /tasks?limit=N`
`limit`: int 1–500, default 20 (fetch bound).
**Scope:** company → property; employees additionally restricted to `employee_id == caller's`. Ordered `created_at` desc.
**200** `{ items: [task_out…], total, page, limit }` — **slim payloads**: `history`, `completion_images`, `completion_submissions`, `checklist`, `verification` are empty/null on list rows (detail endpoint resolves them). Route resolves each task's `area_uid` from its zone/unit.

#### `GET /tasks/{task_id}`
`task_id`: UUID path. **200** full `task_out` (see §6.1) incl. `history[]`, `completion_images[]`, `completion_submissions[]`, and **detail-only** `checklist` + `verification` resolved from the task's `work_templates` row when `template_id` is set.
**Errors:** `404 NOT_FOUND` (missing/cross-property) · `403 FORBIDDEN` (employee ≠ assignee).

#### `POST /tasks/{task_id}/start`
Assignee-only (or staff). Body: none.
**Transition:** `pending | assigned | reopened` → `in_progress`. Appends `started` history event. If the task's resolved `work_type` is `cleaning`, the target resource is flagged `cleaning` through `ResourceStateService` (skips on higher-priority states).
**Errors:** `409 CONFLICT` wrong status or `expires_at` passed ("occurrence has expired") · `403` not assignee · `404`.
**200** `task_out`.

#### `POST /tasks/{task_id}/submit` — employee completion path
Assignee-only. **Body** `TaskSubmitRequest`: `{ note?: str (≤4000), photo_urls: string[] }`.
**Transition:** → `submitted` (PENDING_CHECK — awaits super-admin approval). Creates a `TaskCompletionSubmission` (attempt_number increments), a `submitted` history event carrying `note`+`photos`, and durable `TaskCompletionImage` rows (deduped URLs, ordered).
**Evidence gate:** `min_photos`/`max_photos` from the bound template's `verification` (`min_photos` default 1 when `photo_required`, else 0); cap = `min(MAX_TASK_COMPLETION_IMAGES=10, template max_photos)` → `422 VALIDATION_ERROR field:"photo_urls"`.
**Errors:** `409` already `submitted`/`completed`/`cancelled`/`abandoned`/expired · `403` · `404`.
**200** `task_out` (full detail shape).

**Employee task lifecycle:** `pending|assigned` → `start` → `in_progress` → `submit` → `submitted` → *(staff-only: approve → `completed`, reject → `reopened` → resubmit)*. Terminal: `completed`, `cancelled`, `abandoned` (daily rollover). Employees **cannot** complete directly — direct completion requires super_admin.

`task_out` statuses: `pending | assigned | in_progress | submitted | reopened | completed | cancelled | abandoned | scheduled | overdue`.

---

### 5.3 Maintenance — `/api/v1/maintenance` (all require Bearer)

#### `GET /maintenance`
**Scope:** employees → `assigned_to == me OR reported_by == me`; staff → property/company scope. Ordered `created_at` desc, `events`+`attachments` eager-loaded.
**200** `{ items: [ticket_out…], total }`.

#### `GET /maintenance/eligible-locations`
Employee-only (`403` otherwise). Returns the coverage-scoped raise targets:
```json
{ "rooms": [ { "room_uid", "room_number", "type", "zone_name" } ],
  "dorms": [ { "dorm_uid", "name", "dorm_type", "zone_name", "bed_count" } ] }
```
Coverage = employee's `zone_id` ∪ (all zones inside employee's `area_id`) ∪ resources with matching `area_id`. No coverage → `{rooms: [], dorms: []}`.

#### `POST /maintenance` — 201, `require_employee` role
**Body** `MaintenanceCreateRequest`:

| Field | Type | Rule |
|---|---|---|
| `property_uid` | UUID | required; must be in caller's scope |
| `room_uid` / `dorm_uid` / `bed_uid` / `washroom_uid` | UUID | **exactly one** required |
| `washroom_fixture_uid` | UUID | optional; only with `washroom_uid`, must belong to it |
| `maintenance_type` | str ≤64 | stored lowercase; canonical set: `electrical, plumbing, civil, carpentry, hvac, painting, furniture, appliance, internet, water_drainage, cleaning_equipment, safety_security, other` (defined, not hard-validated) |
| `issue` | str 3–255 | required |
| `description` | str ≤4000 | optional |
| `priority` | `low\|medium\|high\|critical` | default `medium`; invalid → 422 |
| `due_date` | str ≤64 | optional |
| `attachment_urls` | string[] | issue photos; stored as `kind:"issue"` attachments |

**Effects (single transaction):** validates target exists in property → enforces employee zone/area coverage (`403`) → generates `ticket_number` `MT-YYYY-NNNNN` (PG sequence `maintenance_ticket_seq`; count fallback on SQLite) → **auto-allocates** a technician via `WorkAllocationService.allocate` (zone/area round-robin, `work_type="maintenance"`) → `status="assigned"` when allocated else `"open"` → writes `created` (+`assigned`) events → records allocation history → **flags the target resource `maintenance`** via `ResourceStateService` (room / bed / washroom+fixture / dorm+its non-occupied non-inactive beds).
**Errors:** `422` wrong target count / bad refs / invalid priority · `403` outside coverage or role · `404` property.

#### `GET /maintenance/{ticket_id}`
**200** `ticket_out` (see §6.2) incl. `events[]` + `attachments[]`. **403** for an employee who is neither assignee nor reporter; `404` missing/cross-property.

#### `POST /maintenance/{ticket_id}/start`
Assignee-only (or staff). `open | assigned | on_hold` → `in_progress` + `started` event.
**Errors:** `409` other statuses · `403` · `404`. **200** `ticket_out`.

#### `POST /maintenance/{ticket_id}/resolve`
Assignee-only. **Body** `MaintenanceResolveRequest`: `{ resolution_notes: str (3–4000, required), photo_urls: string[] }`.
**Transition:** → `resolved`, sets `resolved_at`, stores notes; photos become `kind:"resolution"` attachments tagged with the attempt number (increments on disapprove→re-resolve); `resolved` event appended; fixture targets get `last_maintenance_at`.
**Template evidence gate:** if `template_id` set, its `verification.min_photos`/`photo_required` must be satisfied → `422 field:"photo_urls"`.
**Note:** a `resolved` ticket **still blocks** the resource — release happens only at staff close/cancel (`_refresh_target`, `release_to="available"`, fixture → `operational`).
**Errors:** `409` already `resolved|closed|cancelled` · `403` not assignee · `404` · `422` notes <3 or evidence short.

**Ticket lifecycle:** `open` → `assigned` → `in_progress` → `resolved` → *(staff: `closed` | disapprove → `in_progress`)*; `on_hold` ↔ resume via `start`; terminal `closed`/`cancelled`. Blocking set: `{open, assigned, in_progress, on_hold, resolved}`.

---

### 5.4 Resources — `/api/v1`

#### `GET /zones`
Auth required; scoped to caller's property (or company for super_admin). Ordered `created_at`.
**200** `{ items: [zone_out…], total, page, limit }` where:
```json
{ "zone_uid", "property_uid", "area_uid", "name", "code", "zone_type",
  "floor", "description", "created_at" }
```

> **Scope note:** this backend intentionally exposes only `/zones`. `GET /areas`, `/properties`, `/employees`, `/rooms`, `/dorms`, `/washrooms` are **not routed** — the frontend calls them defensively and tolerates 404s (serializers `area_out`, `property_out`, `employee_out`, `room_out`, `dorm_out`, `washroom_out`, `rooms_payload`, `dorms_payload` exist in `app/schemas/workspace.py` for the wider product but have no v1 routes here).

---

### 5.5 Media — `/api/v1/media`

#### `POST /media/uploads` — 201, auth, rate-limited 30/min/IP
`multipart/form-data`, field **`file`**.
**Validation:** content-type ∈ `image/jpeg | image/png | image/webp | image/heic | image/heif` (note: magic-byte signature check implemented for jpeg/png/webp; heic/heif accepted by MIME) · ≤ **10 MB** · non-empty · signature must match the declared type → `422 INVALID_UPLOAD field:"photos"`.
**Storage:** key = `uuid4().hex` + extension **from validated content-type** (client filename never trusted). `auto` backend → S3 → Supabase (public bucket auto-created) → local `UPLOAD_DIR`.
**200/201** `{ "url": "<relative /uploads/x or absolute>", "key": "<object key>" }` · `502 STORAGE_UNAVAILABLE` on store failure.
**Serving:** local objects via the `/uploads` static mount (unauthenticated `StaticFiles`).

---

## 6. Wire Schemas (serializers)

### 6.1 `task_out` — `GET /tasks*` payload

```jsonc
{
  "task_uid": "uuid", "ticket_number": "TASK-YYYY-NNNNN|null",
  "property_uid": "uuid", "zone_uid": "uuid|null", "area_uid": "uuid|null",
  "room_uid": "uuid|null", "room_number": "str|null",
  "dorm_uid": "uuid|null", "dorm_name": "str|null",
  "bed_uids": ["uuid-str", ...] | null,
  "washroom_uid": "uuid|null", "washroom_name": "str|null",
  "washroom_fixture_uid": "uuid|null", "washroom_fixture_label": "str|null",
  "supervisor_uid": "uuid|null", "supervisor_name": "str|null",
  "employee_uid": "uuid|null", "assigned_to_name": "str|null",
  "allocation_batch_id": "uuid|null",
  "allocation_status": "auto_assigned|manually_assigned|unassigned",
  "allocation_method": "str|null", "allocation_reason": "str|null",
  "title": "str", "description": "str|null",
  "task_type": "fixed|repetitive|automated",
  "work_type": "cleaning|maintenance|inspection|housekeeping|other|…",
  "origin": "manual|checkout|template|automation",
  "status": "<task status>", "priority": "low|medium|high|urgent|critical",
  "due_date": "YYYY-MM-DD or ISO|null", "due_time": "HH:MM|null",
  "start_time": "HH:MM|null",
  "recurrence_start_date": "str|null", "recurrence_end_date": "str|null",
  "recurrence_window_end": "HH:MM|null",
  "created_by_name": "str|null",
  "recurrence": "hourly|every_2_hours|every_6_hours|every_12_hours|daily|weekly|monthly|quarterly|yearly|null",
  "recurrence_interval_days": "int|null", "series_id": "uuid|null",
  "scheduled_for": "iso|null", "expires_at": "iso|null",
  "template_id": "uuid|null",
  "abandoned_at": "iso|null", "abandoned_reason": "str|null", "abandoned_from_status": "str|null",
  "automation_rule": "obj|null",
  "history": [ { "event_uid", "type", "at", "actor_name", "note", "photos":[] } ],
  "completion_images": [ { "image_uid", "task_uid", "event_uid", "submission_uid",
                           "url", "file_name", "created_by_name", "created_at" } ],
  "completion_submissions": [ { "submission_uid", "task_uid", "event_uid", "attempt_number",
                                "employee_uid", "employee_name", "submitted_at", "status",
                                "reviewed_at", "reviewer_uid", "reviewed_by_name",
                                "review_comment", "images":[…] } ],
  "submitted_at": "iso|null", "completed_at": "iso|null", "created_at": "iso",
  "checklist": [ { "title", "required", "description?" } ] | null,   // detail only, from template
  "verification": { "photo_required", "min_photos", "max_photos", … } | null  // detail only
}
```

History event `type`s: `allocated | started | submitted | completed | rejected | reopened | approved | redo_requested | reassigned | edited | auto_generated | abandoned | room_status_changed`. Submission `status`: `pending | approved | disapproved`.

### 6.2 `ticket_out` — `GET /maintenance*` payload

```jsonc
{
  "ticket_uid": "uuid", "ticket_number": "MT-YYYY-NNNNN",
  "company_uid": "uuid", "property_uid": "uuid",
  "room_uid": "uuid|null", "room_number": "str|null",
  "dorm_uid": "uuid|null", "dorm_name": "str|null",
  "bed_uid": "uuid|null", "bed_number": "str|null",
  "washroom_uid": "uuid|null", "washroom_name": "str|null",
  "washroom_fixture_uid": "uuid|null", "washroom_fixture_label": "str|null",
  "location_label": "room_number | 'dorm · bed' | dorm_name | washroom_name | null",
  "reported_by_name": "str|null",
  "maintenance_type": "str", "issue": "str", "description": "str|null",
  "priority": "low|medium|high|critical",
  "status": "open|assigned|in_progress|on_hold|resolved|closed|cancelled",
  "assigned_to": "uuid|null", "assigned_to_name": "str|null",
  "zone_uid": "uuid|null",
  "allocation_batch_id": "uuid|null", "allocation_status": "…",
  "allocation_method": "str|null", "allocation_reason": "str|null",
  "due_date": "str|null",
  "resolved_at": "iso|null", "closed_at": "iso|null",
  "resolution_notes": "str|null",
  "created_at": "iso", "updated_at": "iso",
  "events": [ { "event_uid", "action", "actor_name", "comment", "at" } ],
  "attachments": [ { "attachment_uid", "url", "file_name", "mime_type",
                     "size_bytes", "kind": "issue|resolution", "attempt",
                     "uploaded_by_name", "created_at" } ]
}
```

Event `action`s: `created | assigned | started | held | resumed | resolved | closed | cancelled | edited | commented | disapproved | room_status_changed`.

### 6.3 Resource-state contract (emitted by resource serializers — used internally / by wider product)

Every resource carries the canonical two-axis block:
```jsonc
{ "status": "<raw column>",
  "is_occupied": "bool",                      // open occupancy record
  "occupancy_state": "occupied|unoccupied|null", // null when no occupancy axis (washrooms, fixtures)
  "operational_state": "available|cleaning|maintenance|inactive"  // fixtures: operational|maintenance|inactive
  "visual_state": "maintenance|cleaning|inactive|occupied|available" }  // the ONE color the UI renders
```
Canonical status sets: room `{available, occupied, cleaning, maintenance}` · dorm same · bed `+inactive` · washroom `{available, cleaning, maintenance, inactive}` · fixture `{operational, maintenance, inactive}`.

---

## 7. Domain Rules (enforced server-side)

1. **Coverage enforcement:** employee ticket creation requires the target's `zone_id ∈ (employee.zone ∪ area's zones)` or matching `area_id` → `403`.
2. **Resource flagging:** `create` flags target `maintenance`; task `start` (work_type=cleaning) flags `cleaning`; illegal flags skipped (higher-priority state wins) via `ResourceStateService.transition` legal-transition table.
3. **Blocking sets:** maintenance blocks on `{open, assigned, in_progress, on_hold, resolved}`; tasks block on all non-terminal (`completed|cancelled|abandoned` release). `resolved` ≠ released — supervisor `close` is the acknowledgement point (`derive(release_to=…)`).
4. **Auto-allocation:** ticket creation runs zone/area-scoped persistent round-robin (`method:"round_robin"`, falls back `none`/unassigned); batch + history recorded on the ticket.
5. **Evidence durability:** submission photos become `TaskCompletionImage` rows bound to task + event + attempt; `storage_key` recovered via `storage_key_from_url` (only storage-owned URLs get deletion keys — external URLs can't trigger arbitrary deletes).
6. **Review gate:** employees submit for review; only super_admin approves/rejects/closes/cancels resource-bound work. Reject → `reopened` + `rejected` event (frontend `reopen_reason` source).
7. **Recurrence (IST wall-clock):** `expires_at` is the authoritative validity boundary — expired occurrences reject start/submit with `409`; completing a `repetitive` task spawns the next occurrence (deduped by `uq_tasks_series_due`); unfinished tasks are `abandoned` by the daily rollover.
8. **Fixture hygiene:** completing a fixture-scoped task stamps `last_cleaned_at`; resolving a fixture ticket stamps `last_maintenance_at` (fixture releases only at ticket close).
9. **Uniform auth failures:** login never reveals whether identifier or password was wrong; refresh/logout are idempotent.
10. **Ticket numbers** from PG sequences (`MT-YYYY-NNNNN`, `TASK-YYYY-NNNNN`), SQLite max-scan fallback for tests.

---

## 8. Data Model Summary (PostgreSQL)

| Table | Key fields | Notes |
|---|---|---|
| `companies` | company_name, brand_name, legal_name, email, phone_number, address, pin_code, operational_day_start (`HH:MM` IST, default 06:00), is_active | Tenant root |
| `users` | email (uniq), username (uniq), password_hash (Argon2id), role, property_id, employee_id, zone_id, phone_number, job_title, is_active, last_login_at | Login identity; scoped to company+property+employee |
| `refresh_tokens` | user_id, token_hash (SHA-256), expires_at, revoked | Opaque tokens |
| `properties` | company_id, name, code, location, city, state, status, manager_* | Property scope |
| `areas` | property_id, name (uniq/property), code, level_number, status | Floor level; cascades zones |
| `zones` | property_id, area_id, name (uniq/property), code, zone_type (`stay`…), floor, status | Functional zone; cascades resources |
| `rooms` | property_id, zone_id, area_id, room_number (uniq/property), type, status, bed_count, current_guest, cleaning_note | |
| `dorms` | property_id, zone_id, area_id, name, dorm_type, washroom, status, is_active, floor | `is_active` = lifecycle flag, separate from status |
| `beds` | dorm_id, property_id, bed_number (uniq/dorm), status, guest_name | `inactive` = retired inventory |
| `washrooms` | property_id, zone_id, area_id, dorm_id (uniq — one attached washroom per dorm), name (uniq/property), washroom_type, status | dorm_id NULL → zone-level facility |
| `washroom_fixtures` | washroom_id, property_id, fixture_type, fixture_number (uniq/washroom+type), status (`operational`…), last_cleaned_at, last_maintenance_at | Real row per fixture; label = `"Type NN"` |
| `employees` | company_id, property_id, zone_id, area_id, name, email, phone, username, job_title, department, status (`Active`/`Deactivated`), shift, leave_status (bool), leave_balance_days, start_date, avatar_color, deactivated_at, reactivated_at | zone XOR area coverage; `employee_is_assignable` gates new work |
| `tasks` | property_id, zone_id, area_id, employee_id, supervisor_id, ticket_number (uniq), room/dorm/bed_ids(JSON)/washroom/fixture refs + denormalized names, title, description, task_type, work_type, origin, status, priority, due_date, due_time, start_time, recurrence*, scheduled_for, expires_at, series_id, template_id, allocation_*, abandoned_*, operational_date, automation_rule | Partial unique idx: one open task per (property, room, title); series+due dedupe |
| `task_history_events` | task_id, type, at, actor_name, note, photos[] | Append-only timeline |
| `task_completion_submissions` | task_id, history_event_id (uniq), employee_id/name, attempt_number (uniq/task), status, submitted_at, reviewed_* | One row per review cycle |
| `task_completion_images` | task_id, history_event_id, submission_id, url, storage_key, file_name, created_by_* | Durable evidence |
| `maintenance_tickets` | ticket_number (uniq), company_id, property_id, room/dorm/bed/washroom/fixture refs + denormalized names, reported_by(_name), maintenance_type, issue, description, priority, status, assigned_to(_name), zone_id, allocation_*, template_id, due_date, resolved_at, closed_at, resolution_notes | Permanent record; resource status is derived |
| `maintenance_ticket_events` | ticket_id, action, actor_name, comment, created_at | Append-only |
| `maintenance_ticket_attachments` | ticket_id, url, file_name, mime_type, size_bytes, kind (`issue`/`resolution`), attempt, uploaded_by_name | |
| `work_allocation_batches` / `work_allocation_history` | round-robin bookkeeping | Zone/area pools |
| `occupancies` | room_id/bed_id, checked_out_at | Open row = occupancy axis |
| `work_templates`, `audit_events`, `resource_state_events` | template checklists/verification, audit, state-transition log | Read by task detail / resource engine |

---

## 9. Cross-Reference: Frontend ↔ Backend

| Frontend call (`src/api/*`) | Backend route | Status |
|---|---|---|
| `POST /auth/login` `POST /auth/refresh` `POST /auth/logout` `GET/PATCH /auth/me` | same | ✅ implemented |
| `GET /tasks?limit=200` · `GET/POST /tasks/{id}[/start|/submit]` | same | ✅ implemented |
| `GET /maintenance` · `GET/POST /maintenance/{id}[/start|/resolve]` · `GET /maintenance/eligible-locations` · `POST /maintenance` | same | ✅ implemented |
| `GET /zones` | `GET /zones` | ✅ implemented (`limit` param ignored by route — returns scoped set) |
| `POST /media/uploads` | same | ✅ implemented |
| `GET /areas` `GET /properties` `GET /employees` `GET /rooms` `GET /dorms` `GET /washrooms` | **not routed** | ⚠️ 404 — frontend catches and degrades (empty enrichment, empty resource lists). Workspace resources currently come only from `eligible-locations` + zone data unless these endpoints are restored |
| `GET /media…` images | `GET /uploads/*` static mount | ✅ |

The authoritative compatibility checklist lives in `backend/docs/MOBILE_COMPATIBILITY.md`; route registration is guarded by `tests/api/test_openapi_contract.py`.
