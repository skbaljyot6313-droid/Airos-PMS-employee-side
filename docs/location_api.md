# AiROS Live Location API — Integration Guide

External-system contract for reading live and historical employee
locations from the AiROS Staff employee backend.

**Base URL (production):**
`https://employee-api-production-c0e3.up.railway.app/api/v1`

## How it works

```text
Employee Android app ──(GPS fix every ~10 s)──▶ Employee API
                                                   │
                                                   ▼
                                          Redis (live fix + history)
                                                   ▲
Your system ──(polls over HTTPS)───────────────────┘
```

- Each tracked employee's phone uploads one position fix roughly every
  **10 seconds** via a native Android foreground service — uploads
  continue while the app is closed or the screen is off, as long as the
  employee stays logged in and location permission is granted.
- Fixes land in Redis: a **live snapshot** (expires 120 s after the last
  fix) plus **day-partitioned history** (retained 90 days).
- You **poll** `GET /admin/live-locations` for the snapshot — it is a
  pull model, not push/webhooks. Polling every 10 s is expected and
  cheap (Redis-only read, no database query unless a scope filter is
  used).
- A device that stops reporting (logout, force-stop, dead battery,
  no signal) drops out of the live list within ~2 minutes. Its history
  is retained.

## Authentication

Every request must carry the shared service key in a header:

```
X-Location-Service-Key: <LOCATION_SERVICE_API_KEY>
```

(`Authorization: Bearer <key>` is also accepted as a legacy form.)

- Employee/manager JWTs are **rejected** — this endpoint is
  service-to-service only.
- The key is compared in constant time. If the key is not configured
  server-side, the endpoint fails closed with `503`.
- Do not put the key in client-side code, mobile apps, public repos,
  or logs. The AiROS team provisions it out-of-band.

## Endpoint 1 — Live locations

```
GET /admin/live-locations
```

Snapshot of every employee whose fix is still live. Returns coordinates
only — no names or employee metadata; join `employee_id` against your
own employee records.

### Query parameters (all optional, composable)

| Param | Type | Effect |
|---|---|---|
| `employee_id` | UUID | Return that employee only. |
| `property_id` | UUID | Only employees assigned to this property. |
| `zone_id` | UUID | Only employees assigned to this zone. |
| `is_active` | bool | Default `true`. `false` requires `employee_id` and returns a stale entry (null coordinates, `is_stale: true`) when the fix has expired — distinguishes "offline" from "not in the list". |

### Response

```json
{
  "locations": [
    {
      "employee_id": "uuid",
      "latitude": 12.9716,
      "longitude": 77.5946,
      "accuracy_m": 8.0,
      "speed_mps": 1.2,
      "bearing_deg": 90.0,
      "altitude_m": 900.0,
      "captured_at": "2026-10-08T11:00:00+00:00",
      "received_at": "2026-10-08T11:00:01+00:00",
      "device_timestamp": 1791234000.0,
      "server_timestamp": 1791234001.0,
      "tracking_session_id": "uuid",
      "sequence_number": 17,
      "quality": "valid",
      "source": "fused",
      "is_live": true,
      "is_stale": false
    }
  ]
}
```

### Field reference

| Field | Meaning |
|---|---|
| `employee_id` | Employee UUID — join key for your records. |
| `latitude` / `longitude` | WGS-84 degrees. Null when `is_stale`. |
| `accuracy_m` | GPS accuracy radius in metres (lower = better). |
| `speed_mps` / `bearing_deg` / `altitude_m` | Motion data, may be null when the device does not report them. |
| `captured_at` | When the **device** captured the fix (authoritative time). |
| `received_at` | When the **server** ingested it. |
| `device_timestamp` / `server_timestamp` | Same instants as epoch seconds (legacy alias fields). |
| `tracking_session_id` | Which tracking session produced the fix. |
| `sequence_number` | Per-session monotonic counter. |
| `quality` | `valid` \| `low_accuracy` \| `delayed` \| `suspicious_speed` — see below. |
| `source` | Location provider (`fused`, `gps`, …), may be absent. |
| `is_live` | `true` while the fix is within the 120 s freshness window. |
| `is_stale` | `true` only in the `is_active=false` + `employee_id` lookup after expiry. |

Legacy synonym fields (`accuracy`, `speed`, `heading`) are also emitted
for backwards compatibility — prefer the `_m`/`_mps`/`_deg` names.

### `quality` flags

| Value | Meaning |
|---|---|
| `valid` | Within accuracy, freshness, and movement bounds. |
| `low_accuracy` | Accuracy worse than 500 m. Stored, not dropped. |
| `delayed` | Arrived more than 24 h after capture (offline replay). |
| `suspicious_speed` | Implied speed vs. previous fix above 80 m/s (GPS jump/teleport). Stored, marked. |

## Endpoint 2 — Route history

```
GET /admin/location-history/{employee_id}
```

Time-ranged route for one employee, ordered by device capture time.

### Query parameters

| Param | Required | Effect |
|---|---|---|
| `from`, `to` | yes | ISO-8601 datetimes (UTC). `to` must be after `from`; maximum span 31 days. |
| `tracking_session_id` | no | Restrict to points from that session. |
| `max_points` | no | Point cap override, 1–100 000 (default 10 000). |

### Response

```json
{
  "employee_id": "uuid",
  "from": "2026-10-08T00:00:00+00:00",
  "to": "2026-10-09T00:00:00+00:00",
  "total_points": 1234,
  "returned_points": 1234,
  "downsampled": false,
  "points": [
    {
      "latitude": 12.9716,
      "longitude": 77.5946,
      "accuracy_m": 8.0,
      "speed_mps": 1.2,
      "bearing_deg": 90.0,
      "altitude_m": 900.0,
      "captured_at": "2026-10-08T11:00:00+00:00",
      "received_at": "2026-10-08T11:00:01+00:00",
      "tracking_session_id": "uuid",
      "sequence_number": 17,
      "quality": "valid"
    }
  ]
}
```

When a range holds more points than the cap, points are **stride
downsampled** — evenly spaced so the route keeps its shape — and
`downsampled` is `true`. Points are never truncated mid-route.

## Semantics you should rely on

- **Freshness**: `received_at` is the server arrival time;
  `captured_at` is when the fix actually happened on the device. A phone
  that was offline replays queued fixes later — those arrive with old
  `captured_at`, appear in history at their true position, and are
  flagged `delayed`. They never overwrite a newer live position.
- **"Employee went offline"**: the live entry disappears within ~2 min
  of the last fix. History persists for 90 days.
- **Coverage**: only employees who are logged into the Android app with
  location permission granted report positions. There is no roster
  endpoint on this API — treat absent employees as "not currently
  reporting".
- **Ordering**: history is ordered by `captured_at` (device clock), not
  arrival order.

## Errors

| Status | Code | Meaning |
|---|---|---|
| 400 | `INVALID_FILTER` | `is_active=false` without `employee_id`. |
| 400 | `INVALID_HISTORY_RANGE` | Bad `from`/`to` — `to` ≤ `from` or span > 31 days. |
| 401 | — | Missing or wrong service key. |
| 503 | `LIVE_LOCATION_UNAVAILABLE` | Location store unavailable server-side. Retry with backoff. |

## Recommended polling

Poll `GET /admin/live-locations` every **10 s** (matching the device
cadence). Faster polling is permitted but yields no new data — device
fixes arrive at ~10 s intervals per employee.

## Examples

```bash
BASE="https://employee-api-production-c0e3.up.railway.app/api/v1"
KEY="<LOCATION_SERVICE_API_KEY>"   # provisioned by AiROS — never commit

# All live employees
curl -H "X-Location-Service-Key: $KEY" "$BASE/admin/live-locations"

# One employee (live or stale)
curl -H "X-Location-Service-Key: $KEY" \
  "$BASE/admin/live-locations?employee_id=EMPLOYEE_UUID&is_active=false"

# Employees at one property
curl -H "X-Location-Service-Key: $KEY" \
  "$BASE/admin/live-locations?property_id=PROPERTY_UUID"

# Route history for a shift window
curl -H "X-Location-Service-Key: $KEY" \
  "$BASE/admin/location-history/EMPLOYEE_UUID?from=2026-10-08T08:00:00Z&to=2026-10-08T18:00:00Z"
```

Minimal polling loop (Node.js):

```js
const BASE = "https://employee-api-production-c0e3.up.railway.app/api/v1";
const KEY = process.env.LOCATION_SERVICE_API_KEY;

async function pollLive() {
  const res = await fetch(`${BASE}/admin/live-locations`, {
    headers: { "X-Location-Service-Key": KEY },
  });
  if (!res.ok) throw new Error(`live-locations ${res.status}`);
  const { locations } = await res.json();
  for (const l of locations) {
    console.log(l.employee_id, l.latitude, l.longitude, l.captured_at);
  }
}

setInterval(() => pollLive().catch(console.error), 10_000);
```
