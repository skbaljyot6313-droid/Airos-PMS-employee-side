# Location API

Owner: Employee Backend. The Super Admin backend consumes the admin
endpoints over HTTPS only — it never connects to Redis, and no Redis
credential is ever shared with it.

```text
Employee Android → POST /location/*      (employee JWT)
Super Admin BE   → GET  /admin/*         (X-Location-Service-Key)
```

**Production base URL:** `https://employee-api-production-c0e3.up.railway.app/api/v1`

## Authentication

| Route family | Auth | Notes |
|---|---|---|
| `POST /api/v1/location/*` | Employee JWT (`Authorization: Bearer`) | `employee_id` is derived from the token; any `employee_id` in the body is ignored. |
| `GET /api/v1/admin/*` | Service key — `X-Location-Service-Key: <LOCATION_SERVICE_API_KEY>` | Canonical contract for the SA backend. `Authorization: Bearer <key>` is also accepted. Constant-time compare; employee JWTs are rejected with 401. 503 when `LOCATION_SERVICE_API_KEY` is unset. |

## Session lifecycle

### `POST /api/v1/location/start`

Body: none. Creates a session row (Postgres lifecycle metadata only) and
the Redis hot-path marker the ingest path validates against.

```json
{
  "tracking_session_id": "uuid",
  "started_at": "2026-10-08T11:00:00+00:00",
  "tracking_interval_seconds": 10
}
```

- Employees may hold multiple sessions per day (shift gaps, app
  restarts). Sessions are deliberately decoupled from attendance days.
- If Redis is unavailable the request fails with 503 — no session is
  created, so retry is always safe.

### `POST /api/v1/location/stop`

```json
{ "tracking_session_id": "uuid" }
→ { "stopped": true, "stopped_at": "2026-10-08T19:00:00+00:00" }
```

- Stopping is idempotent: re-stopping returns the recorded `ended_at`.
- A stopped session rejects further ingestion (`INVALID_TRACKING_SESSION`).
- History is never deleted on stop.
- 404 `TRACKING_SESSION_NOT_FOUND` for unknown or foreign session ids.

## Ingest — `POST /api/v1/location/current`

One position fix per call. DB-free hot path: session check + dedup +
write land in two Redis pipelines.

```json
{
  "latitude": 12.9716,
  "longitude": 77.5946,
  "accuracy": 8.0,
  "accuracy_m": 8.0,
  "speed_mps": 1.2,
  "bearing_deg": 90.0,
  "altitude_m": 900.0,
  "captured_at": "2026-10-08T11:00:00Z",
  "tracking_session_id": "uuid",
  "sequence_number": 17,
  "source": "fused"
}
```

Required: `latitude`, `longitude`, `accuracy` (≥ 0), and a timestamp —
`captured_at` (ISO-8601, UTC preferred) or legacy `timestamp` (device
epoch seconds). Legacy synonyms `speed`/`heading` are still accepted.

Response:

```json
{
  "accepted": true,
  "recorded": true,
  "received_at": "2026-10-08T11:00:01.234Z",
  "location_timestamp": "2026-10-08T11:00:00Z",
  "server_timestamp": 1791234001.234,
  "expires_in": 120,
  "duplicate": false,
  "quality": "valid"
}
```

### Idempotency

`tracking_session_id` + `sequence_number` form the dedup key
(`SET NX`, `LOCATION_EVENT_DEDUP_TTL_SECONDS` retention). A retry of an
already-ingested fix returns `accepted: true, duplicate: true` and writes
nothing new — safe to retry on network loss. Fixes without both fields
are not deduped.

### Ordering

History is ordered by `captured_at` (device clock, stored in the ZSET
score). A delayed/offline fix lands at its captured position and never
clobbers a fresher live position. `received_at` is always the server
clock and is the authoritative arrival order.

### Timestamps and skew

- `captured_at` beyond `LOCATION_MAX_FUTURE_SKEW_SECONDS` in the future →
  400 `INVALID_TIMESTAMP`.
- Captures older than `LOCATION_MAX_EVENT_AGE_SECONDS` are accepted but
  flagged `delayed` — GPS noise is data.

### Quality flags

`quality` on the ack and every history point:

| Value | Meaning |
|---|---|
| `valid` | Within accuracy, freshness and movement bounds. |
| `low_accuracy` | `accuracy` > `LOCATION_LOW_ACCURACY_M`. Stored, not dropped. |
| `delayed` | Arrived after `LOCATION_MAX_EVENT_AGE_SECONDS`. |
| `suspicious_speed` | Implied speed vs the previous fix > `LOCATION_MAX_SPEED_MPS`. Stored, marked. |

Precedence: `delayed` > `low_accuracy` > `suspicious_speed`.

### Errors

| Status | Code | Cause |
|---|---|---|
| 400 | `INVALID_TRACKING_SESSION` | Unknown/expired/stopped session marker. Tracker should call `/start` again. |
| 400 | `INVALID_TIMESTAMP` | `captured_at` too far in the future. |
| 401 | — | Missing/expired employee JWT. |
| 422 | — | Schema violation (coordinates out of range, missing timestamp, …). |
| 429 | `LOCATION_RATE_LIMITED` | > `LOCATION_RATE_LIMIT_PER_MINUTE` fixes/minute/employee. |
| 503 | `LIVE_LOCATION_UNAVAILABLE` | Redis down. Retry with backoff. |

### Self-read — `GET /api/v1/location/current`

Returns the employee's own live fix, or a stale marker when expired.

## Admin — `GET /api/v1/admin/live-locations`

Snapshot of every employee with a non-expired fix.

Query params (all optional, composable):

| Param | Effect |
|---|---|
| `employee_id` | That employee only. |
| `property_id` / `zone_id` | Employees assigned there (one employees-table lookup; intersected with the live index). |
| `is_active` | Default `true`. `false` requires `employee_id` and returns the stale entry (null coordinates) for employees whose fix expired. |

```json
{
  "locations": [
    {
      "employee_id": "uuid",
      "latitude": 12.9716, "longitude": 77.5946,
      "accuracy_m": 8.0, "speed_mps": 1.2,
      "bearing_deg": 90.0, "altitude_m": 900.0,
      "captured_at": "2026-10-08T11:00:00+00:00",
      "received_at": "2026-10-08T11:00:01+00:00",
      "device_timestamp": 1791234000.0,
      "server_timestamp": 1791234001.0,
      "tracking_session_id": "uuid", "sequence_number": 17,
      "quality": "valid", "source": "fused",
      "is_live": true, "is_stale": false
    }
  ]
}
```

Canonical names above; legacy synonyms (`accuracy`, `speed`, `heading`)
are also emitted for backwards compatibility. No names or employee
metadata — the SA backend joins on `employee_id` itself.

## Admin — `GET /api/v1/admin/location-history/{employee_id}`

Time-ranged route history from daily Redis partitions (one pipelined
read per covered date — no key scans).

Query params:

| Param | Required | Effect |
|---|---|---|
| `from`, `to` | yes | ISO-8601 datetimes (UTC). `to` must be after `from`; span ≤ `LOCATION_MAX_HISTORY_RANGE_DAYS` (31). |
| `tracking_session_id` | no | Only points from that session. |
| `max_points` | no | Override the `LOCATION_MAX_HISTORY_POINTS` cap (10 000), 1–100 000. |

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
      "latitude": 12.9716, "longitude": 77.5946,
      "accuracy_m": 8.0, "speed_mps": 1.2,
      "bearing_deg": 90.0, "altitude_m": 900.0,
      "captured_at": "2026-10-08T11:00:00+00:00",
      "received_at": "2026-10-08T11:00:01+00:00",
      "tracking_session_id": "uuid",
      "sequence_number": 17,
      "quality": "valid"
    }
  ]
}
```

Points are chronological by `captured_at`. When the range holds more
than the point cap, points are stride-downsampled (evenly spaced —
coverage, not truncation) and `downsampled` is `true`.

## Storage semantics

| Key | Type | TTL |
|---|---|---|
| `mt:location:emp:{id}` | HASH — live fix | `LOCATION_CURRENT_TTL_SECONDS` (120 s) |
| `mt:location` | ZSET — live index, score = expiry epoch | members pruned on read |
| `mt:location:history:{id}:{YYYY-MM-DD}` | ZSET — day partition, score = captured ms | `LOCATION_HISTORY_RETENTION_DAYS` (90) |
| `mt:location:geo:{YYYY-MM-DD}` | GEO index (member = event id) | retention |
| `mt:location:session:{uuid}` | STRING JSON marker | `LOCATION_SESSION_TTL_SECONDS` (12 h) |
| `mt:location:event:{id}:{sid}:{seq}` | STRING dedup marker | `LOCATION_EVENT_DEDUP_TTL_SECONDS` (24 h) |

- Stale current location: when the live hash expires, `is_active=false`
  with `employee_id` returns a stale entry (null coordinates); unfiltered
  reads exclude it. History survives independently.
- Retention: day partitions expire `LOCATION_HISTORY_RETENTION_DAYS`
  after their date; expired partitions simply return empty results.
- The Super Admin backend must not depend on these key names — they are
  internal. The JSON contracts above are the API.

## curl examples (Super Admin backend)

```bash
# All live locations
curl -H "X-Location-Service-Key: $LOCATION_SERVICE_API_KEY" \
  "https://employee-api-production-c0e3.up.railway.app/api/v1/admin/live-locations"

# One employee
curl -H "X-Location-Service-Key: $LOCATION_SERVICE_API_KEY" \
  "https://employee-api-production-c0e3.up.railway.app/api/v1/admin/live-locations?employee_id=EMPLOYEE_UUID"

# Property / zone scope, active-only, stale check
curl -H "X-Location-Service-Key: $LOCATION_SERVICE_API_KEY" \
  "https://employee-api-production-c0e3.up.railway.app/api/v1/admin/live-locations?property_id=PROPERTY_UUID"
curl -H "X-Location-Service-Key: $LOCATION_SERVICE_API_KEY" \
  "https://employee-api-production-c0e3.up.railway.app/api/v1/admin/live-locations?zone_id=ZONE_UUID"
curl -H "X-Location-Service-Key: $LOCATION_SERVICE_API_KEY" \
  "https://employee-api-production-c0e3.up.railway.app/api/v1/admin/live-locations?employee_id=EMPLOYEE_UUID&is_active=false"

# Route history — time range + optional session filter + point cap
curl -H "X-Location-Service-Key: $LOCATION_SERVICE_API_KEY" \
  "https://employee-api-production-c0e3.up.railway.app/api/v1/admin/location-history/EMPLOYEE_UUID?from=2026-10-08T08:00:00Z&to=2026-10-08T18:00:00Z"
curl -H "X-Location-Service-Key: $LOCATION_SERVICE_API_KEY" \
  "https://employee-api-production-c0e3.up.railway.app/api/v1/admin/location-history/EMPLOYEE_UUID?from=2026-10-08T08:00:00Z&to=2026-10-08T18:00:00Z&tracking_session_id=SESSION_UUID&max_points=500"
```

Never put the real `LOCATION_SERVICE_API_KEY` in code, docs, or logs —
the SA backend receives it through its own secret store.
