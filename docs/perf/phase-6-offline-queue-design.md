# Phase 6 — offline mutation queue (DESIGN ONLY, not implemented)

Design for letting the app queue mutations while offline and replay
them on reconnect. **No code in this phase** — the safety surface is
large enough that the contract needs review first.

## Scope

In scope (idempotent, retry-safe candidates):

- `POST /tasks/{id}/start` — status transition, repeatable.
- `POST /maintenance` — ticket create; needs a client-generated op id to
  dedupe server-side.
- `POST /maintenance/{id}/start`, `/resolve` — transition + payload.
- `POST /devices/register|unregister` — last-write-wins.
- `POST /media/uploads` — uploads only once content is produced; the
  queue stores the local URI and uploads on replay (not the bytes
  inline — the file may be purged; keep the path reference).

Explicitly OUT of scope:

- **Attendance start/break/resume/end** — any action requiring geofence
  confirmation or a server-trusted timestamp CANNOT be safely replayed
  offline. A queued "start day" that lands hours later would write a
  false `started_at`. Design decision: attendance shows an
  "offline — actions disabled" state instead of queueing.
- Task submissions with photos as a single atomic op — the media upload
  and the submit are separate calls; partial replay states must be
  handled (upload succeeds, submit fails → evidence orphan). The
  submission op records dependent op ids and replays them in order.
- Realtime-only paths (location ingest already has its own native
  on-disk JSONL retry queue — do NOT route it through this design).

## Client queue model

```ts
interface QueuedOp {
  op_id: string;          // client-generated uuid (also the dedupe key)
  kind: 'task.start' | 'maintenance.create' | 'maintenance.start'
      | 'maintenance.resolve' | 'devices.register' | 'devices.unregister'
      | 'media.upload' | 'task.submit';
  payload: unknown;        // wire-shaped body
  depends_on?: string[];   // op_ids that must succeed first (uploads)
  created_at: number;
  attempts: number;
  last_error?: { status: number; code: string };
}
```

- Persisted in `@capacitor/preferences` under
  `airos:queue:v1:{user_uid}` — user-namespaced, purged on logout,
  encrypted-at-rest is a nice-to-have (Android Keystore-backed prefs is
  a later hardening step — payloads contain no secrets).
- FIFO per user; `depends_on` creates a partial order (uploads before
  the referencing submit/resolve).
- Replay triggers: `realtimeResume()` path — app resume + connectivity
  restore + login. Max replay rate ~1 op / 200 ms to avoid a burst.

## Server contract (the part that makes replay safe)

1. **Header**: `Idempotency-Key: {op_id}` on every queued mutation.
2. **Server dedupe**: a `POST` that carries an `Idempotency-Key` stores
   `(employee_id, key) → (response_status, response_body, created_at)`
   in Postgres (new table `idempotency_keys` — a migration) with a
   unique constraint; a replayed request with the same key replays the
   STORED response, never re-executes. 72 h TTL cleanup.
3. For endpoints where a natural dedupe exists (task start on an
   already-started task → currently 409), the idempotency table still
   wins — the natural 409 is ambiguous for a client that never saw the
   first response.
4. 5xx on replay → exponential backoff, keep in queue. 4xx → drop the
   op, surface it in a "needs attention" inbox (the server said no —
   retrying won't change it).

## Failure / conflict semantics

- A server-side state change between enqueue and replay (task
  reassigned, ticket resolved by someone else) → the replay gets the
  REAL current error (403/409) → drop op + notify via the inbox —
  never silently overwrite.
- Account switch: queue is user-namespaced; another user's session
  never replays the first user's ops.
- Token refresh mid-replay: replay uses the same apiClient path (401 →
  refresh → retry once — a mutation retry is acceptable ONLY inside
  the idempotency-keyed replay, since dedupe makes it safe).

## Open questions for review

- Do submissions need conflict UI (server-approved-vs-queued-edit) or
  is drop-on-4xx sufficient for v1?
- Media uploads on metered connections — replay only on Wi-Fi?
- 72 h key retention vs. device-side op expiry (a week-old queued
  maintenance ticket may be stale context) — suggest matching both at
  72 h.
- `Idempotency-Key` table is a migration — **stop condition**: needs
  Alembic revision + SA-backend coordination (shared DB) before any
  implementation.
