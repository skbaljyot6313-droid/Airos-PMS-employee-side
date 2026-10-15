# Realtime (Centrifugo) — Employee Backend & Mobile App

Status: **deployed and production-verified** (employee token endpoints,
WebSocket connect, own-channel subscribe — see §Verification).

Centrifugo v6.9.7 runs as a shared Railway service for both the
Super Admin backend and this Employee Backend. It uses an in-memory
engine with a single replica. Realtime is an **optimization layer** —
events are invalidation hints, never authoritative data. Every screen
still reads truth from the REST API, and the existing polls remain the
reconciliation backstop.

## Channel grammar

    priv:prop:{property_uid}:{topic}   prop channel — SA-side dashboards
    priv:emp:{employee_uid}            employee's own private channel

`priv` is a server-authoritative namespace: clients cannot subscribe
without a JWT minted by a backend. `allow_subscribe_for_client` is
false for both anonymous and authenticated clients at Centrifugo level.

This backend mints tokens for `priv:emp:{uid}` **only** — and only when
`uid == caller.employee_id`. Property/admin channels are minted by the
SA backend.

## Endpoints (`/api/v1/realtime`)

Both require the normal employee JWT (`get_current_user`).

- `GET /realtime/token` → `{token, expires_at, ws_url}`
  HS256 JWT, `sub=<user.id>`, `info={role,company_id,property_id}`,
  TTL `CENTRIFUGO_CONN_TOKEN_TTL_SECONDS` (default 300s).
  `ws_url` = `CENTRIFUGO_WS_URL`, else `CENTRIFUGO_URL` +
  `/connection/websocket`.
- `POST /realtime/subscribe` `{channels:[…]}` → `{tokens, expires_at}`
  Per-channel JWTs, `sub=<user.id>` + `channel`, TTL
  `CENTRIFUGO_SUB_TOKEN_TTL_SECONDS` (default 600s).

| Case | Result |
|---|---|
| No/invalid employee JWT | 401 |
| Realtime unconfigured | 503 `REALTIME_UNAVAILABLE` |
| Channel ≠ `priv:emp:{caller.employee_id}` | 403 `CHANNEL_DENIED` |
| Malformed channel / other namespaces | 403 |
| Centrifugo rejects a foreign sub token | WS close 3500 |

## Publishing (`app/core/centrifugo.py`)

- `publish_bg()` — fire-and-forget `POST {CENTRIFUGO_URL}/api/publish`
  with `X-API-Key`. Called **after** `session.commit()` returns;
  failures log a warning and never affect the mutation.
- `queue_event()` — buffers events on `session.info`; an
  `after_commit` hook in `app/core/database.py` drains them, so
  resource-state transitions inside outer transactions still only
  publish on real commit. Rollback drops the buffer (`after_rollback`).
- `location_publish_allowed()` — per-employee throttle (Redis `NX` +
  in-process fallback) coalescing 10 s device fixes to
  `LOCATION_PUBLISH_MIN_INTERVAL_SECONDS` (default 8 s).

### Emitted events (payloads are minimal uids — never sensitive data)

| Event | Emp channel | Prop channel | Trigger |
|---|---|---|---|
| `task.updated` | assignee | `prop:{pid}:tasks` | task start/submit mutations |
| `maintenance.created` / `.updated` | assignee | `prop:{pid}:maintenance` | ticket create/start/resolve |
| `attendance.checked_in` / `.checked_out` / `.break_started` / `.break_ended` | employee | `prop:{pid}:attendance` | attendance lifecycle |
| `employee.location_updated` | — | `prop:{pid}:locations` | live-location ingest (throttled) |
| `resource.state_changed`-style unit events | — | `prop:{pid}:units` | post-commit queue drain |

Note: assignment events originate in the **SA backend** — this API
publishes employee-side lifecycle events; the notification feed still
materializes SA-side assignments on read.

## Mobile (`src/services/realtime.ts`)

- `startRealtime(employeeUid)` — fetches a connection JWT, opens one
  shared `Centrifuge` WebSocket, subscribes `priv:emp:{uid}` with a
  minted subscription token. `getToken` callbacks re-mint on expiry for
  both connection and subscription — renewal is automatic.
- Every publication triggers `pollNotificationsNow()` (instant feed
  poll) and fans out to listeners. `subscribeRealtimeEvents(prefixes,
  cb)` gives screens a debounced invalidation hook — wired into
  TasksScreen (`task.*`, `maintenance.*`, `ticket.*`), MaintenanceScreen,
  MaintenanceDetailScreen, TaskDetailScreen, AttendanceScreen
  (`attendance.*`).
- `realtimeResume()` — on Capacitor `appStateChange` resume: nudges
  `centrifuge.connect()` (no-op if connected) and polls the feed.
- `stopRealtime()` — logout cleanup; kills socket + listeners.
- 503 from `/realtime/token` → realtime marked unavailable for a 60 s
  cooldown, then retried; all other errors degrade silently to polling.
- If realtime is unconfigured, the app behaves exactly as before —
  45 s notification poll + manual refreshes.

## Environment variables (Railway `employee-api`)

- `CENTRIFUGO_URL` — HTTP API base of the Centrifugo service.
- `CENTRIFUGO_API_KEY` — `X-API-Key` for `/api/publish`.
- `CENTRIFUGO_TOKEN_SECRET` — HMAC secret for client JWTs; must match
  Centrifugo `token_hmac_secret_key` and the SA backend.
- `CENTRIFUGO_WS_URL` — public WSS endpoint handed to clients.
- Optional TTLs / throttle: `CENTRIFUGO_CONN_TOKEN_TTL_SECONDS`,
  `CENTRIFUGO_SUB_TOKEN_TTL_SECONDS`,
  `LOCATION_PUBLISH_MIN_INTERVAL_SECONDS`.

## FCM stays separate

Centrifugo never replaces FCM. A WebSocket is dead while the app is
suspended/terminated — OS-level work-allocation alerts still go through
`PUSH_PROVIDER=fcm` push; realtime only accelerates in-app refresh.

## Verification evidence (2026-10-15)

Production, employee `locverify@demo.local` (synthetic test employee):

```
PASS  unauth /realtime/token            401
PASS  login                             200
PASS  authed /realtime/token            200  ws_url=wss://centrifugo-production-943c…
PASS  subscribe own priv:emp channel    200
PASS  other-emp channel denied          403
PASS  property channel denied           403
PASS  malformed channel denied          403
PASS  WSS connect (conn JWT)            accepted, v6.9.7, ttl 297
PASS  WSS subscribe own channel         accepted, ttl 597
PASS  WSS subscribe foreign channel     rejected (3500 invalid token)
```

Test suites:

- Backend: `pytest` — 297 passed (23 realtime tests).
- Frontend: `vitest run` — 149 passed (10 realtime lifecycle tests).
- `tsc --noEmit` clean; `vite build` + `cap sync android` clean.

## Troubleshooting

- `REALTIME_UNAVAILABLE` (503) — a `CENTRIFUGO_*` var is unset on
  `employee-api`; check Railway service env.
- WS connect rejected (`invalid token`) — `CENTRIFUGO_TOKEN_SECRET`
  mismatch between this backend and the Centrifugo service config.
- Events published but app doesn't react — realtime socket only
  accelerates refresh; verify screen still correct after next poll
  cycle before suspecting event loss.
- Employee sees nothing realtime but app works — confirm
  `priv:emp:{uid}` subscription succeeded; non-own channels are 403 by
  design.

## Rollback

Unset `CENTRIFUGO_URL` (or all three required vars) on `employee-api`
and redeploy — endpoints 503, mobile degrades to the pre-realtime
polling behavior with zero code change. The mobile client never hard-
fails on realtime absence.
