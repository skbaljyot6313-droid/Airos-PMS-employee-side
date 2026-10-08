# AiROS Staff — Frontend API & Data Documentation

Deep index of the employee-facing frontend (`production/employee/frontend`).

**App:** AiROS Staff — a mobile-first operations app for property employees (tasks, checklists, photo evidence, maintenance ticketing).
**Stack:** React 19 + TypeScript + Vite 8 + Tailwind CSS 4 + Capacitor 7 (Android) + Express static host (`server.ts`).
**Backend contract:** FastAPI backend mounted at `/api/v1` (base URL from `VITE_API_URL`). All IDs on the wire are `*_uid` strings.

---

## 1. Architecture Overview

```
src/
├── api/                    # Single HTTP boundary — screens never call fetch directly
│   ├── client.ts           # apiClient(), token storage, refresh, error normalization
│   ├── auth.ts             # /auth/* endpoints
│   ├── tasks.ts            # /tasks/* endpoints + wire→display normalization
│   ├── maintenance.ts      # /maintenance/* + zone workspace assembly
│   ├── directory.ts        # /zones /areas /properties /employees /rooms /dorms /washrooms
│   └── media.ts            # /media/uploads multipart upload
├── context/
│   └── AuthContext.tsx     # Session, user/company/employee enrichment, login/logout
├── screens/
│   ├── auth/LoginScreen.tsx
│   └── employee/
│       ├── TasksScreen.tsx            # Tab 1 — task buckets
│       ├── TaskDetailScreen.tsx       # Task detail + evidence capture + submit
│       ├── MaintenanceScreen.tsx      # Tab 2 — zone list
│       ├── ZoneWorkspaceScreen.tsx    # Zone unit grid (rooms/dorms/beds/washrooms/fixtures)
│       ├── MaintenanceNewScreen.tsx   # Guided raise-ticket flow
│       ├── MaintenanceDetailScreen.tsx# Ticket detail + start/resolve actions
│       └── ProfileScreen.tsx          # Tab 3 — identity, workplace, edit contact, logout
├── components/
│   ├── common/             # Buttons, BottomNav, ScreenHeader, StatusBadge, PriorityBadge,
│   │                       # FeedbackStates (Loading/Error/Empty), DeviceFrame
│   ├── tasks/TaskCard.tsx
│   └── maintenance/        # ZoneCard, UnitTile, DormCard, WashroomCard, UnitActionSheet,
│                           # MaintenanceCard
├── types/index.ts          # Display models (normalized shapes screens consume)
├── theme/tokens.ts         # Design tokens (referenced; Tailwind classes used inline)
├── App.tsx                 # AuthProvider + manual stack/tab router (no react-router)
└── main.tsx                # Entry
```

**Key architectural rules (enforced in code):**

- `api/client.ts` is the **only** place that calls `fetch`. No screen constructs URLs.
- API layer normalizes wire payloads into display shapes (`types/index.ts`); screens never read raw backend fields.
- `visual_state` on resources is **server-computed** — the frontend never derives it.
- Coverage/eligibility is enforced server-side; the frontend mirrors it via `/maintenance/eligible-locations`.

---

## 2. Runtime Configuration

| Item | Value | Source |
|---|---|---|
| API base URL | `import.meta.env.VITE_API_URL`, default `http://localhost:8000/api/v1` | `.env` (see `.env.example`) |
| Android emulator URL | `http://10.0.2.2:8000/api/v1` | `.env.example` |
| Physical device URL | `http://<lan-ip>:8000/api/v1` | `.env.example` |
| API origin (media host) | Base URL minus `/api/vN` suffix — exported as `API_ORIGIN` | `client.ts` |
| App server | Express on `PORT` (default 3000); Vite middleware in dev, `dist/` statics in prod | `server.ts` |
| Capacitor | appId `com.airos.staff`, webDir `dist`, dev server `http://10.0.2.2:3000` (cleartext) | `capacitor.config.json` |
| Camera | `@capacitor/camera` on native; `<input type="file">` fallback on web | Task/Maintenance screens |

**Token storage (localStorage):**

| Key | Contents |
|---|---|
| `airos_staff_access_token` | Bearer access token |
| `airos_staff_refresh_token` | Refresh token |

**Custom window event:** `airos_unauthorized` — dispatched when a 401 survives refresh; `AuthContext` listens and forces sign-out with "session timed out" message.

---

## 3. API Client (`src/api/client.ts`)

### `apiClient<T>(endpoint, options): Promise<T>`

| Option | Default | Purpose |
|---|---|---|
| `timeoutMs` | `20000` (`60000` for uploads) | AbortController timeout |
| `auth` | `true` | Attach `Authorization: Bearer <access>`; `false` for login/refresh/logout |
| `_retried` | internal | Guarantees at most one refresh+retry per request |

**Behavior:**

1. Sets `Content-Type: application/json` unless the body is `FormData` or a header exists.
2. Attaches `Authorization` from `secureStorage.getToken()` when `auth: true`.
3. On `401` + `auth` + not retried → `singleFlightRefresh()` (concurrent 401s share one `POST /auth/refresh`) → retry once. On refresh failure → clear tokens, dispatch `airos_unauthorized`, throw 401 `ApiError`.
4. `204` → `undefined`. Non-OK → `normalizeError()`.
5. Abort → `{ status: 0, code: 'TIMEOUT' }`; other network failures → `{ status: 0, code: 'NETWORK_ERROR' }`.

### `secureStorage`

`getToken()`, `getRefreshToken()`, `setTokens(access, refresh)`, `setAccessToken(access)`, `clearTokens()` — all wrapped in try/catch (private-mode safe).

### `mediaUrl(path)`

Resolves a backend-relative path (`/uploads/x.jpg`) against `API_ORIGIN`; absolute `http(s)` URLs pass through. **Convention:** submission payloads send the raw `path`; views render `mediaUrl(path)`.

### Error normalization (`ApiError`)

```ts
interface ApiError {
  status: number;                    // HTTP status, 0 = network/timeout
  code?: string;                     // 'TIMEOUT' | 'NETWORK_ERROR' | 'UNAUTHORIZED' | server code
  message: string;
  fieldErrors?: { field?: string; message: string; code?: string }[];
}
```

FastAPI envelopes handled:
- `{ detail: [{loc, msg, type}] }` (422 validation) → `fieldErrors[]` (field = last `loc` segment)
- `{ detail: string }` → message
- `{ detail: { message, field?, code? } }` → message + optional single fieldError
- Fallback messages per status: 400, 401, 403, 404, 409, 422, 429, 500, 502, 503.

---

## 4. Endpoint Inventory

Base: `{VITE_API_URL}` (e.g. `http://host:8000/api/v1`). All authenticated calls send `Authorization: Bearer <access_token>`.

### 4.1 Auth

| Method | Endpoint | Request body | Response | Client fn | Used by |
|---|---|---|---|---|---|
| POST | `/auth/login` | `{ identifier, password }` | `AuthSession { access_token, refresh_token, user, company }` | `loginApi` | LoginScreen → AuthContext.login |
| POST | `/auth/refresh` | `{ refresh_token }` | `{ access_token }` | internal `refreshAccessToken` | apiClient (auto, on 401) |
| POST | `/auth/logout` | `{ refresh_token }` | — | `logoutApi` (best-effort, errors swallowed) | AuthContext.logout → ProfileScreen |
| GET | `/auth/me` | — | `{ user: User, company: Company }` | `getMeApi` | Session restore on app launch |
| PATCH | `/auth/me` | `{ name?, phone?, email? }` | `User` | `updateMeApi` | ProfileScreen edit modal |

**Access gate (client-side):** after login/`me`, `applySession` throws a 403 `ApiError` unless `user.role === 'employee'` **and** `user.employee_uid` is set — non-employee roles cannot use the app.

### 4.2 Tasks

| Method | Endpoint | Request | Response (wire) | Client fn | Used by |
|---|---|---|---|---|---|
| GET | `/tasks?limit=200` | — | `{ items: task_out[], total }` (employee-scoped server-side) | `fetchTasksApi` | TasksScreen |
| GET | `/tasks/{task_uid}` | — | `task_out` | `getTaskDetailApi` | TaskDetailScreen |
| POST | `/tasks/{task_uid}/start` | — | `task_out` | `startTaskApi` | TaskDetailScreen (auto-chained before submit for pending/assigned/reopened) |
| POST | `/tasks/{task_uid}/submit` | `{ note?, photo_urls: string[] }` | `task_out` | `submitTaskApi` | TaskDetailScreen |

**`task_out` wire fields consumed by `mapTask`:**

| Wire field | → Display field (`Task`) | Notes |
|---|---|---|
| `task_uid` | `id` | Routing key |
| `ticket_number` | `ticket_number` | Display ID (nullable) |
| `title` | `title` | |
| `work_type` \|\| `task_type` | `category` | Title-cased |
| `room_number` / `dorm_name`+`bed_uids[]` / `washroom_name`+`washroom_fixture_label` | `location_name` | "Room N" / "Dorm · N beds" / "WC · Fixture" / "Common area" |
| `zone_uid` | `zone_uid`, `zone_name` | Name joined from `GET /zones` (best-effort) |
| `priority` | `priority` | `low|medium|high|critical|urgent` |
| `status` | `status` | See status vocabulary §7 |
| `due_date` | `due_date`, `due_at` | `due_at` only set when value contains `T` (a date-only string carries no clock time — `hasClockTime`) |
| `due_time`, `scheduled_for`, `expires_at` | same | |
| `description` | `instructions` | |
| `checklist[]: {title, required, description}` | `checklist[]: {id=cl-N, label, required, completed=false, description}` | Completion state is local-only |
| `verification: {photo_required, min_photos, max_photos, checklist_required, supervisor_approval}` | `verification_config` | `min_photos` defaults to 1 when photo_required, `max_photos` defaults 5 |
| `completion_images[]: {image_uid, url, file_name, created_at}` | `evidence[]: {id, url(raw path), filename, uploaded_at}` | |
| `history[]: {event_uid, type, at, note, actor_name}` | `history[]: {id, event_type, timestamp, notes, actor_name}` | Latest `rejected`/`reopened`/`redo_requested` event's note → `reopen_reason` |
| `employee_uid` | `assigned_to_employee_id` | |
| `assigned_to_name`, `supervisor_name` | same | |

**Submit contract notes:** backend lifecycle is start → submit; starting marks `in_progress` and flags the resource for cleaning. The backend accepts `{note, photo_urls}` — **checklist completion is a client-side gate only**; the server validates evidence, not checkboxes.

### 4.3 Maintenance

| Method | Endpoint | Request | Response (wire) | Client fn | Used by |
|---|---|---|---|---|---|
| GET | `/maintenance` | — | `{ items: ticket_out[], total }` — scoped to **assigned to me OR reported by me** | `fetchMaintenanceApi` | MaintenanceScreen (badge), ZoneWorkspace (active tickets) |
| GET | `/maintenance/{ticket_uid}` | — | `ticket_out` | `getMaintenanceDetailApi` | MaintenanceDetailScreen |
| POST | `/maintenance` | see below | `ticket_out` | `createMaintenanceTicketApi` | MaintenanceNewScreen |
| POST | `/maintenance/{ticket_uid}/start` | — | `ticket_out` | `startMaintenanceTicketApi` | MaintenanceDetailScreen |
| POST | `/maintenance/{ticket_uid}/resolve` | `{ resolution_notes, photo_urls? }` | `ticket_out` | `resolveMaintenanceTicketApi` | MaintenanceDetailScreen resolve sheet |
| GET | `/maintenance/eligible-locations` | — | `{ rooms: [...], dorms: [...] }` (coverage-scoped) | `fetchEligibleLocationsApi`, `fetchEligibleSets` | MaintenanceNewScreen step 1; zone coverage derivation |

**POST `/maintenance` body:**

```json
{
  "property_uid": "string (required, from user.property_uid)",
  "room_uid | dorm_uid | bed_uid | washroom_uid": "exactly one target uid",
  "washroom_fixture_uid": "optional, with washroom_uid, for fixture-level tickets",
  "maintenance_type": "snake_case wire value (see map below)",
  "issue": "string (required)",
  "description": "string (optional)",
  "priority": "low|medium|high|critical",
  "attachment_urls": ["/uploads/x.jpg", "..."]  // raw upload paths, kind='issue'
}
```

Server enforces zone/area coverage → `403` outside coverage.

**`ticket_out` wire fields consumed by `mapTicket`:**

| Wire field | → Display field (`MaintenanceTicket`) | Notes |
|---|---|---|
| `ticket_uid` | `id` | |
| `ticket_number` | `ticket_number` | `MT-YYYY-NNNNN` display ID |
| `issue`, `description` | same | |
| `maintenance_type` | `category` | Via `TYPE_LABELS` (unknown → title-cased) |
| `room_number` \|\| `location_label` \|\| `dorm_name` \|\| `washroom_name` | `location_name` | Falls back to `'Property'` |
| `zone_uid` | `zone_uid`, `zone_name` | Name joined from `/zones` |
| `priority`, `status` | same | Wire `open` → display `reported` (`wireStatus`) |
| `attachments[]: {kind, url}` | `photos` (kind=`issue`), `resolution_photos` (kind=`resolution`) | Resolved via `mediaUrl` |
| `room_uid`, `dorm_uid`, `bed_uid`, `washroom_uid`, `washroom_fixture_uid` | same | Resource linkage for workspace matching |
| `assigned_to` | `assigned_to_employee_id` | |
| `assigned_to_name`, `reported_by_name` | same | |
| — | `is_reported_by_me` | Derived: `assigned_to !== myEmployeeUid` (visible tickets are always mine, so not-assigned ⇒ I reported it) |
| `created_at`, `resolved_at`, `closed_at`, `resolution_notes` | same | |
| `events[]: {action, at, actor_name, comment}` | `history[]: {status, timestamp, actor_name, notes}` | |

### 4.4 Directory / Resources (`src/api/directory.ts`)

| Method | Endpoint | Response | Client fn | Used by |
|---|---|---|---|---|
| GET | `/zones?limit=N` (N=200 default, 500 in enrichment/workspace) | `ListResponse<Zone>` | `listZonesApi` | AuthContext, task/ticket zone-name joins, zone lists |
| GET | `/areas?limit=200` | `ListResponse<Area>` | `listAreasApi` | AuthContext enrichment |
| GET | `/properties?limit=50` | `ListResponse<Property>` | `listPropertiesApi` | AuthContext enrichment |
| GET | `/employees?limit=500` | `ListResponse<EmployeeRecord>` | `listEmployeesApi` | AuthContext enrichment |
| GET | `/rooms?limit=500[&zone_uid=X]` | `ListResponse<Room>` | `listRoomsApi` | Zone lists, workspace |
| GET | `/dorms?limit=500[&zone_uid=X]` | `ListResponse<Dorm>` (embeds `beds[]`) | `listDormsApi` | Zone lists, workspace |
| GET | `/washrooms?limit=500[&zone_uid=X]` | `ListResponse<Washroom>` (embeds `fixtures[]`) | `listWashroomsApi` | Zone lists, workspace |

`ListResponse<T> = { items: T[]; total: number }`.

**Wire resource shapes** (all carry `ResourceStateFields`):

```ts
ResourceStateFields = {
  status: string;
  visual_state: 'available'|'occupied'|'cleaning'|'maintenance'|'inactive';  // server-computed
  operational_state: string | null;
  occupancy_state: string | null;
  is_occupied: boolean;
}

Zone       { zone_uid, property_uid, area_uid|null, name, code|null, zone_type|null, floor|null, description|null }
Area       { area_uid, property_uid, name, level_number|null }
Property   { property_uid, name }
EmployeeRecord { employee_uid, property_uid, zone_uid|null, area_uid|null, name,
                 department|null, status|null, leave_status|null, job_title|null, shift|null }
Room       { room_uid, zone_uid|null, area_uid|null, room_number, type|null,
             bed_count|null, current_guest|null, ...ResourceStateFields }
Dorm       { dorm_uid, zone_uid|null, area_uid|null, name, dorm_type|null,
             beds: Bed[], ...ResourceStateFields }
Bed        { bed_uid, dorm_uid, bed_number, guest_name|null, ...ResourceStateFields }
Washroom   { washroom_uid, zone_uid|null, area_uid|null, dorm_uid|null, name,
             washroom_type|null, fixtures: WashroomFixture[], ...ResourceStateFields }
WashroomFixture { fixture_uid, washroom_uid, fixture_type, fixture_number, label,
             ...ResourceStateFields }
```

### 4.5 Media (`src/api/media.ts`)

| Method | Endpoint | Request | Response | Client fn | Used by |
|---|---|---|---|---|---|
| POST | `/media/uploads` | `multipart/form-data`, field `file` | `{ url, key }` | `uploadMediaApi` | TaskDetailScreen, MaintenanceNewScreen, MaintenanceDetailScreen |

- Input may be a `data:` URL (converted via `dataUrlToBlob`), `File`, or `Blob`; filename auto-generated (`photo-<ts>.<ext>` / caller-provided).
- Server validates MIME + magic bytes — JPEG/PNG/WebP only, **10 MB cap**. Timeout raised to 60 s.
- Returns `{ path: res.url (raw, for payloads), url: mediaUrl(res.url) (for <img>), key }`.
- `toEvidenceItem()` maps an upload to the `EvidenceItem` shape (raw path in `url`).

---

## 5. Display Models (`src/types/index.ts`)

### 5.1 Auth / identity

```ts
User      { uid, name, email, username, role: UserRole, company_uid,
            property_uid|null, employee_uid|null, zone_uid|null,
            phone|null, job_title|null, company_name|null }
UserRole  = 'super_admin'|'property_manager'|'human_resource'|'department_manager'|'employee'
Company   { company_uid, name, legal_name|null, brand_name|null, email|null, phone|null,
            address|null, pin_code|null, operational_day_start, created_at }
AuthSession { access_token, refresh_token, user, company }
```

`Employee` (workplace context, assembled **client-side** in AuthContext from `/auth/me` + `/zones` + `/areas` + `/properties` + `/employees` — anything the backend doesn't expose stays `null`):

```ts
Employee {
  id                 // employee_uid
  name
  property_uid, property_name
  zone_uid,   zone_name     // record.zone_uid ?? user.zone_uid
  area_uid,   area_name
  department               // record.department ?? user.job_title
  status: 'active'|'inactive'|null
  leave_status: 'present'|'on_leave'|null
}
```

### 5.2 Task

```ts
Task {
  id                       // task_uid
  ticket_number: string|null
  title, category, location_name
  zone_uid, zone_name
  priority: 'low'|'medium'|'high'|'critical'|'urgent'
  status: TaskStatus        // see §7
  due_at: string|null       // only when wire due_date has a clock time
  due_date, due_time, scheduled_for, expires_at: string|null
  instructions: string|null
  checklist: { id, label, required, completed, description? }[]
  verification_config: { photo_required, min_photos, max_photos,
                         checklist_required?, supervisor_approval? }
  evidence: { id, url, uploaded_at?, filename? }[]   // url = raw backend path
  reopen_reason: string|null
  history: { id, event_type, timestamp, notes?, actor_name }[]
  assigned_to_employee_id, assigned_to_name, supervisor_name: string|null
}
TaskBucket = 'to_do' | 'in_review' | 'done'
```

### 5.3 Maintenance

```ts
MaintenanceTicket {
  id                       // ticket_uid
  ticket_number            // MT-YYYY-NNNNN
  issue, category: MaintenanceCategory, location_name
  zone_uid, zone_name
  priority: 'low'|'medium'|'high'|'critical'
  status: MaintenanceStatus          // see §7
  description?
  photos: string[]                   // absolute URLs (kind='issue')
  resolution_photos?: string[]       // kind='resolution'
  room_uid|dorm_uid|bed_uid|washroom_uid|washroom_fixture_uid: string|null
  assigned_to_employee_id, assigned_to_name, reported_by_name: string|null
  is_reported_by_me: boolean
  created_at, resolved_at?, closed_at?, resolution_notes?: string|null
  history?: { status, timestamp, actor_name, notes? }[]
}
```

### 5.4 Zone workspace

```ts
ZoneResource {
  id                       // room_uid | dorm_uid | bed_uid | washroom_uid | fixture_uid
  kind/type: 'room'|'dorm'|'bed'|'washroom'|'fixture'
  name                     // "Room N" | dorm name | "Bed N" | washroom name | fixture label
  state: 'available'|'occupied'|'cleaning'|'maintenance'|'inactive'   // = wire visual_state
  zone_uid
  parent_uid               // dorm_uid for beds & dorm-attached washrooms; washroom_uid for fixtures
  washroom_uid?            // set on fixtures (submitted alongside)
  path: string[]           // breadcrumb e.g. [zone, dorm, bed]
  active_ticket_id, active_ticket_number   // employee-visible active ticket, else null
  eligible: boolean        // raise-ticket permission (coverage)
}

ZoneSummary {
  id: zone_uid, name, type, area_uid, area_name
  counts: { rooms, dorms, beds, washrooms, other }
  open_issues              // resources with visual_state='maintenance'
}

ZoneWorkspace { zone: ZoneSummary, resources: ZoneResource[],
                active_tickets: { id, ticket_number, resource_id, issue,
                                  category, status, priority }[] }

MaintenanceTarget {        // locked unit carried workspace → raise flow
  kind, uid, washroom_uid?, zone_id, name, path }

EligibleLocation { id, kind: 'room'|'dorm', name, zone_name }
```

---

## 6. API Function Reference

### `src/api/auth.ts`

| Function | Signature | Endpoint | Notes |
|---|---|---|---|
| `loginApi` | `(identifier, password) → AuthSession` | POST `/auth/login` | `auth:false`; stores nothing itself |
| `getMeApi` | `() → {user, company}` | GET `/auth/me` | Session restore |
| `logoutApi` | `(refreshToken) → void` | POST `/auth/logout` | Best-effort; swallows errors |
| `updateMeApi` | `({name?, phone?, email?}) → User` | PATCH `/auth/me` | |

### `src/api/tasks.ts`

| Function | Endpoint(s) | Notes |
|---|---|---|
| `fetchTasksApi()` | GET `/tasks?limit=200` + GET `/zones` | Parallel; zone-name join is best-effort |
| `getTaskDetailApi(id)` | GET `/tasks/{id}` + GET `/zones` | |
| `startTaskApi(id)` | POST `/tasks/{id}/start` | Marks in_progress; flags resource for cleaning |
| `submitTaskApi(id, {note?, photo_urls})` | POST `/tasks/{id}/submit` | Status → `submitted` (awaits supervisor review) |
| `hasClockTime(v)` | — | `v.includes('T')` — date-only dues get no fabricated hour |

### `src/api/maintenance.ts`

| Function | Endpoint(s) | Notes |
|---|---|---|
| `fetchMaintenanceApi(myEmployeeUid?)` | GET `/maintenance` + GET `/zones` | Returns `{ assigned_to_me, reported_by_me }` split via `is_reported_by_me` |
| `getMaintenanceDetailApi(id, myEmployeeUid?)` | GET `/maintenance/{id}` + GET `/zones` | |
| `createMaintenanceTicketApi(payload)` | POST `/maintenance` | Maps display `category` → wire `maintenance_type`; exactly one resource uid field |
| `startMaintenanceTicketApi(id)` | POST `/maintenance/{id}/start` | |
| `resolveMaintenanceTicketApi(id, {resolution_notes, photo_urls?})` | POST `/maintenance/{id}/resolve` | Client requires notes ≥ 3 chars |
| `fetchEligibleLocationsApi()` | GET `/maintenance/eligible-locations` | Flattens `{rooms, dorms}` → `EligibleLocation[]` |
| `fetchMaintenanceZonesApi()` | `/zones` + `/maintenance/eligible-locations` + `/rooms` + `/dorms` + `/washrooms` | **Covered zones** = zones containing ≥1 eligible room/dorm (resource endpoints are property-scoped for reads; coverage boundary comes from eligible-locations) |
| `fetchZoneWorkspaceApi(zoneId, myEmployeeUid?)` | `/zones` + `/rooms?zone_uid` + `/dorms?zone_uid` + `/washrooms?zone_uid` + `/maintenance` | Assembles flat `ZoneResource[]` (rooms, dorms+beds, washrooms+fixtures), links active tickets per resource uid, builds zone summary + active_tickets index |

Constants: `TYPE_LABELS`/`TYPE_WIRE` (see §7), `ACTIVE_TICKET_STATUSES = {open, assigned, in_progress, on_hold}` — block re-raising on a unit.

### `src/api/directory.ts`

`listZonesApi(limit=200)`, `listAreasApi(limit=200)`, `listPropertiesApi(limit=50)`, `listEmployeesApi(limit=500)`, `listRoomsApi(zoneUid?)`, `listDormsApi(zoneUid?)`, `listWashroomsApi(zoneUid?)` — thin GET wrappers returning `ListResponse<T>`.

### `src/api/media.ts`

`uploadMediaApi(input: string|File|Blob, filename?) → {path, url, key}`; `dataUrlToBlob`; `toEvidenceItem(m, filename?) → EvidenceItem`.

---

## 7. Vocabularies & Mapping Tables

### Task status (`TaskStatus`)

Wire: `pending | assigned | in_progress | submitted | reopened | completed | cancelled | abandoned | scheduled | overdue`

**Buckets (TasksScreen):**
- `to_do` ← assigned, pending, in_progress, reopened, scheduled, overdue
- `in_review` ← submitted
- `done` ← completed, cancelled, abandoned

**Client-overridden display:** `TaskCard`/`TaskDetailScreen` render `overdue` when `due_at < now` and status ∉ {completed, cancelled, submitted}.

**Workable (`canWork`):** status ∈ {assigned, pending, in_progress, reopened} **and** not past `expires_at`.

### Maintenance status (`MaintenanceStatus`)

Wire → display: `open` → **`reported`**; `assigned`, `in_progress`, `on_hold`, `resolved`, `closed`, `cancelled` pass through.
`StatusBadge` renders `reopened` (tasks) as label **"Returned"**.

### Maintenance category (display ↔ wire `maintenance_type`)

| Display | Wire | Display | Wire |
|---|---|---|---|
| Electrical | `electrical` | Internet | `internet` |
| Plumbing | `plumbing` | Water / Drainage | `water_drainage` |
| Civil | `civil` | Cleaning Equipment | `cleaning_equipment` |
| Carpentry | `carpentry` | Safety | `safety_security` |
| HVAC | `hvac` | Furniture | `furniture` |
| Painting | `painting` | Appliance | `appliance` |
| Other | `other` | | |

### Resource visual state (`visual_state` — server-computed)

`available` (green), `occupied` (purple), `cleaning` (amber), `maintenance` (red), `inactive` (grey) — rendered via `RESOURCE_STATE_STYLES` in `UnitTile.tsx`.

### Task history event labels (TaskDetailScreen)

`allocated`→"Allocated to Employee", `started`→"Task Started", `submitted`→"Submitted for Review", `returned`→"Returned for Correction", `reopened`→"Reopened", `approved`→"Approved by Manager" (unknown types render raw).

---

## 8. Screen-by-Screen Index

Routing is a manual stack in `App.tsx` (`StackRoute` union): `tabs` → `task-detail` | `zone-workspace` | `maintenance-new` | `maintenance-detail`. Bottom nav: **Tasks** (badge = to-do count), **Maintenance** (badge = active assigned tickets), **Profile**.

### 8.1 `LoginScreen` (`screens/auth/LoginScreen.tsx`)

- **Needs:** none (unauthenticated).
- **Calls:** `AuthContext.login` → `loginApi` → POST `/auth/login`.
- **Displays:** username/email + password fields, show/hide password, `authError` banner, loading on submit.
- **Gate:** non-`employee` roles or missing `employee_uid` → rejected with 403 message by `applySession`.

### 8.2 `TasksScreen` — tab `tasks`

- **Calls:** `fetchTasksApi()` on mount + manual refresh.
- **Displays:** time-based greeting + `employee.name` first name; coverage chip (`employee.property_name` · `zone_name || area_name`); three buckets with live counts; `TaskCard` list.
- **`TaskCard` shows:** `category`, `priority`, `title`, `location_name` · `zone_name`, due label ("Today · HH:MM" / date / "No due time set" / "Overdue (HH:MM)"), `StatusBadge`.
- **Emits:** `onSelectTask(taskId)` → `task-detail`; `onTasksCountChange(todoCount)` → nav badge.
- **States:** loading skeleton, error w/ retry, per-bucket empty states.

### 8.3 `TaskDetailScreen` — route `task-detail`

- **Calls:** `getTaskDetailApi(taskId)`; `uploadMediaApi` per photo; `startTaskApi` then `submitTaskApi(id, {note?, photo_urls})` on submit.
- **Displays:** header (`ticket_number || title`, `category · location_name`, status badge); reopened banner (`reopen_reason`); expired banner; submit-success banner; action-error banner; meta card (category, priority, title, location+zone, due formatted, `assigned_to_name`); instructions; interactive checklist (required/optional tags, locked when `!canWork`); photo evidence grid (`evidence/min–max`, "Min N required" chip); completion notes textarea; history timeline.
- **Input/capture:** Capacitor `Camera.getPhoto` (camera/gallery) on native; hidden `<input type=file>` (`capture="environment"` for camera) on web; photos uploaded immediately, raw paths stored in local `evidenceList`.
- **Validation before submit:** all `required` checklist items checked; `photo_required` → `evidenceList.length ≥ min_photos`.
- **Lifecycle:** `pending|assigned|reopened` auto-`start` inside submit; success → status `submitted` → "Awaiting Property Manager Review" pill; `completed` → "Task Completed & Approved".

### 8.4 `MaintenanceScreen` — tab `maintenance`

- **Calls:** `fetchMaintenanceZonesApi()` + `fetchMaintenanceApi(employee_uid)` in parallel.
- **Displays:** "Your Zones" — `ZoneCard` per covered zone.
- **`ZoneCard` shows:** `name`, `type`, counts grid (Rooms/Dorms/Beds/Washrooms + optional Other), open-issue pill (`open_issues` → red "N Open Issues" or green "All clear").
- **Badge count** sent up: assigned tickets with status ∉ {resolved, closed, cancelled}.
- **Emits:** `onSelectZone(zone)` → `zone-workspace`. Empty state: "No zones assigned".

### 8.5 `ZoneWorkspaceScreen` — route `zone-workspace`

- **Calls:** `fetchZoneWorkspaceApi(zoneId, employee_uid)`.
- **Displays:** header (zone name, `X Rooms · Y Dorms · Z Beds`, refresh); open-issues strip; sections: **Rooms** (grid), **Dormitories** (`DormCard` expandable → beds grid + attached `WashroomCard`s + "Dorm-level issue"), **Standalone Beds**, **Washrooms** (`WashroomCard` expandable → fixture tiles + "Washroom-level issue"), **Other Units**.
- **`UnitTile` shows:** type icon, `ResourceStateBadge`, name, active ticket chip (`ticket_number`) or "+ Maint" affordance.
- **Tap a unit → `UnitActionSheet`:** resource name, `path` breadcrumb, state badge; if `active_ticket_id` → ticket summary + "View Ticket" (→ `maintenance-detail`); if `maintenance`/`inactive` w/o visible ticket → explanatory note (someone outside scope owns it; no duplicate raise offered); else → "Raise Maintenance" (→ `maintenance-new` with locked `MaintenanceTarget`).

### 8.6 `MaintenanceNewScreen` — route `maintenance-new`

- **Calls:** `fetchEligibleLocationsApi()` (only when no locked target); `uploadMediaApi` per photo; `createMaintenanceTicketApi(payload)` → success screen → `onSuccess(ticket.id)` → `maintenance-detail`.
- **Flow:** 4 steps (3 when target locked — location step skipped):
  1. **Location** — pick from eligible rooms/dorms (`name`, `zone_name`).
  2. **Category** — 13-button grid with icons (HVAC, Plumbing, Electrical, Carpentry, Furniture, Appliance, Painting, Internet, Water/Drainage, Cleaning Equipment, Civil, Safety, Other).
  3. **Issue** — per-category picklist (3–5 canned issues each, defined in `CATEGORIES`) + "Other custom issue" → free text becomes `issue`; optional `description` textarea.
  4. **Priority & Photos** — photo grid (upload/remove), review card (location/category/issue/priority), submit.
- **Payload assembly:** exactly one of `room_uid|dorm_uid|bed_uid|washroom_uid` (+`washroom_fixture_uid` for fixtures); `property_uid` from `user.property_uid` (missing → hard error "account is not linked to a property").
- **Success view:** ticket number, issue, location, assigned tech name (or "Queued / Unassigned") + "View Ticket" / "Back to Zone".

### 8.7 `MaintenanceDetailScreen` — route `maintenance-detail`

- **Calls:** `getMaintenanceDetailApi(ticketId, employee_uid)`; `startMaintenanceTicketApi`; `resolveMaintenanceTicketApi(id, {resolution_notes, photo_urls})`; `uploadMediaApi` for resolution photos.
- **Displays:** header (`ticket_number`, `category · location_name`, status); "Reported by you" banner (when `is_reported_by_me` and not assigned); header card (category, priority, issue, location+zone, reported timestamp, `reported_by_name`, assigned tech — "You (Assigned)" | name | "Unassigned"); description; issue photo grid; resolution block when `resolved` (notes + resolution photos + "under manager final audit" note); activity timeline (`history` — status label, time, actor, notes).
- **Actions (only when `assigned_to_employee_id === user.employee_uid`):**
  - `assigned` → **Start Work** → POST `/start`.
  - `in_progress` → **Resolve Ticket** → bottom sheet (notes ≥3 chars required, optional photo proof) → POST `/resolve`.
  - `resolved` → read-only "Work Resolved · Under Manager Review" pill.

### 8.8 `ProfileScreen` — tab `profile`

- **Calls:** `updateProfile` → `updateMeApi` (PATCH `/auth/me`); `logout` → `logoutApi` (POST `/auth/logout`) + local token clear.
- **Displays:** identity card (initials avatar, `user.name`, `@username`, `job_title` chip, `company.brand_name || name`); **Workplace Assignment (read-only, "System Locked")**: `employee.property_name`, `zone_name || area_name`, `department`, operational status (Active/Inactive/On Leave); **Personal Contact**: name/phone/email + edit modal (PATCH); authorization scoping info; sign-out with confirmation dialog.

---

## 9. Session & State Management (`AuthContext`)

| Exposed | Source |
|---|---|
| `user`, `company` | Login response or `GET /auth/me` |
| `employee` | `enrichEmployee()` — joins `employee_uid` against `/employees`, `/zones`, `/areas`, `/properties` (all best-effort) |
| `isAuthenticated` | `!!user && role==='employee' && !!employee_uid` |
| `isLoading` | Session restore / login in-flight |
| `authError` | Login errors + forced sign-out message |
| `login`, `logout`, `updateProfile`, `clearError` | Actions |

- **Restore:** on mount, if any token exists → `getMeApi()` → `applySession` (role gate) → `enrichEmployee`. 401/403 clears tokens; other failures (e.g. network) keep tokens and just warn.
- **Forced sign-out:** `airos_unauthorized` event → clear tokens + user state + "session timed out" message.
- **Logout:** clears local state + storage first, then best-effort `/auth/logout` revocation.

---

## 10. Component Inventory (display-data contracts)

| Component | Props → data shown |
|---|---|
| `TaskCard` | `Task` → category, priority, title, location·zone, due label/overdue, status badge |
| `MaintenanceCard` | `MaintenanceTicket` + `currentEmployeeId` → number, category, priority, issue, location·zone, assignee/"Reported by you" pill, photo count, created date, status (currently unused by screens) |
| `ZoneCard` | `ZoneSummary` → name, type, counts grid, open-issues pill |
| `UnitTile` | `ZoneResource` → type icon, state badge, name, ticket chip / "+ Maint" |
| `DormCard` | dorm + beds + washrooms + fixturesOf → expandable dorm with counts, issue count, children |
| `WashroomCard` | washroom + fixtures → expandable, state badge, fixture tiles |
| `UnitActionSheet` | resource + activeTicket → path, state, ticket summary/raise CTA/blocked note |
| `StatusBadge` | task/maintenance status + 'overdue' → label/color/icon map (§7) |
| `PriorityBadge` | `low|medium|high|critical` (+`urgent` falls back to medium styles) |
| `ScreenHeader` | title, subtitle, back, rightElement |
| `PrimaryButton/SecondaryButton/DangerButton` | loading, icon, size sm/md/lg |
| `EmptyState/ErrorState/LoadingState` | feedback copy + retry actions |
| `BottomNav` | tab + counts badges |
| `DeviceFrame` | 420px phone shell + status bar (desktop preview) |

---

## 11. Business Rules Captured in Code

1. **Employee-only app:** `role === 'employee'` + `employee_uid` required; otherwise 403 rejection at session apply.
2. **Server is authoritative:** statuses, `visual_state`, coverage, verification config — never recomputed client-side (except overdue display + bucket grouping, which are pure presentation).
3. **Coverage-derived zone list:** resource endpoints are property-scoped for reads, so "my zones" = zones containing ≥1 room/dorm returned by `/maintenance/eligible-locations`.
4. **One active ticket per unit (client mirror):** units with an employee-visible active ticket show it; units flagged `maintenance`/`inactive` without a visible ticket block re-raise (owner is outside scope). `ACTIVE_TICKET_STATUSES` gate matching.
5. **Exactly one target uid** per ticket create; fixtures submit both `washroom_uid` + `washroom_fixture_uid`.
6. **Checklist is a client gate only** — submission validity = photo evidence (server validates).
7. **Photos:** uploaded to `/media/uploads` immediately on capture; only the **raw path** is submitted in `photo_urls`/`attachment_urls`; `mediaUrl()` used purely for `<img>` rendering.
8. **Date-only due dates** carry no clock time — `due_at` stays `null` to avoid fabricating a due hour.
9. **Single-flight refresh:** concurrent 401s share one `/auth/refresh`; one retry per request; then forced sign-out.
10. **`myEmployeeUid` scoping:** `is_reported_by_me = assigned_to !== me` — valid because the backend only returns tickets assigned to or reported by the caller.

---

## 12. Backend Dependency Summary (what the API must provide)

| Capability | Endpoints |
|---|---|
| JWT auth (access+refresh), session restore, profile update, revocation | `/auth/login` `/auth/refresh` `/auth/me` (GET+PATCH) `/auth/logout` |
| Employee-scoped task list/detail + lifecycle | `/tasks` `/tasks/{id}` `/tasks/{id}/start` `/tasks/{id}/submit` |
| Employee-scoped maintenance list/detail + lifecycle + coverage targets | `/maintenance` `/maintenance/{id}` `/maintenance/{id}/start` `/maintenance/{id}/resolve` `/maintenance/eligible-locations` |
| Directory lookups & property-scoped resources | `/zones` `/areas` `/properties` `/employees` `/rooms` `/dorms` `/washrooms` |
| Image upload (JPEG/PNG/WebP ≤10MB) + hosted `/uploads/*` | `/media/uploads` |

**Required wire behaviors the frontend depends on:** `ListResponse {items,total}` envelopes; `*_uid` identifiers; `task_out`/`ticket_out` shapes incl. `checklist`, `verification`, `completion_images`, `history`/`events`, `attachments{kind,url}`; `visual_state` on all resources; employee scoping on `/tasks` and `/maintenance`; coverage enforcement (403) on `POST /maintenance`; FastAPI error envelopes `{detail: ...}`.
