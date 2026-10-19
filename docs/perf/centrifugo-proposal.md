# Centrifugo proposal — Phase 4 (NOT APPLIED)

Everything below is a **proposed config diff only**. Nothing here is
applied to the shared Centrifugo deployment — the same instance serves
the Super Admin backend, so any namespace change is a coordinated,
human-approved rollout. Code shipped in Phase 4 works with the CURRENT
config; it only uses `wasRecovering`/`recovered` signals that become
meaningful once history is enabled.

## Current behavior (verified in code)

- The EB API publishes `{v, id, type, ts, data}` envelopes via
  `POST /api/publish` (`backend/app/core/centrifugo.py`).
- Employee app subscribes to `priv:emp:{employee_uid}` only — self-scoped
  token minting (`/realtime/subscribe`).
- SA channels `priv:prop:{property_uid}:{tasks,units,attendance,
  maintenance,locations,employees}` are minted by the SA backend.
- No history configured → a reconnecting client cannot recover missed
  publications; the 45 s `/notifications` poll + screen re-pulls are the
  reconciliation floor.
- `publish_bg` is fire-and-forget; business mutations never fail on
  Centrifugo. Post-commit ordering is now enforced by `queue_event` +
  the `after_commit` dispatch hook (rollback → no event).

## Proposed namespace diff

```jsonc
{
  "namespaces": [
    {
      "name": "priv",
      "history_size": 50,        // NEW — keep last 50 publications
      "history_ttl": "300s",     // NEW — 5 min retention window
      "force_recovery": true,    // NEW — SDKs attempt stream recovery
      "force_push_join_leave": false
    }
  ]
}
```

Rationale:

- `history_size`/`history_ttl` bound server memory — emp channels are
  low-rate (a few events/min at most); 50 msgs / 5 min is ample for a
  reconnect window without unbounded growth.
- `force_recovery` lets centrifuge-js attempt recovery on resubscribe;
  `SubscribedContext.wasRecovering && !recovered` then means "history
  existed and could not be replayed" — the Phase-4 client treats exactly
  that case as a silent gap (cache wipe + refetch; implemented).
- Recovery failure modes (history overflow, epoch loss) all funnel into
  `recovered=false` → client reconciles. No correctness depends on
  recovery succeeding — it only reduces refetch frequency.

Rollout order:

1. Apply namespace diff to the shared Centrifugo (staging first).
2. Verify `wasRecovering`/`recovered` semantics on reconnect (kill app,
   mutate, relaunch).
3. Enable `REALTIME_COMPANY_CHANNEL_ENABLED` for the company channel.

## Optional company channel (implemented, flag OFF)

`company:{company_uid}` — carries ONLY `{type: company.ref_changed,
uid, ref_version}` markers emitted on bootstrap-scope mutations (zone
create/update/delete in `StructureService`). The client refetches
`/bootstrap` on mismatch — no payload data crosses the channel.

Authorization: `/realtime/subscribe` mints `company:*` tokens ONLY when
`REALTIME_COMPANY_CHANNEL_ENABLED=true` AND the channel's uid equals the
caller's `company_id`. Default OFF — the shared Centrifugo accepts the
channel name natively (no `priv:` prefix needed since the publish uses
the API key server-side; subscription still requires a minted JWT).

Client gate: `VITE_COMPANY_CHANNEL=1` subscribes alongside the emp
channel; flag off → the code path never runs.

## SA-backend dependencies (NOT implemented — human-owned)

These events would let the employee app react to SA-side mutations.
Emitters live in the SA backend on the same Centrifugo; document only:

- `shift.changed` — an employee's shift assignment edited → client
  invalidates `attendance:` + `shift` static cache. Currently invisible
  until next poll.
- `coverage.changed` — employee zone/area coverage edited → invalidate
  `maintenance:eligible` + `maintenance:zones`. Currently invisible
  until next poll.
- `task.assigned` for SA-created assignments where no
  `/admin/notify-allocation` call is made — see
  `NOTIF_SYNC_ON_READ` rollout notes (phase-5-proposal.md).
- `task.completed` for SA-side approvals — this service emits it for
  its own `approve_task` path; SA approvals on the shared DB need
  SA-side emitters for full coverage.

## Security notes

- Emp-channel authorization is unchanged: token mint only when
  `user.employee_id` matches.
- Company channel mint is flag-gated AND same-company enforced; it
  carries a version marker, never data — a compromised subscription
  leaks only "something changed" timing.
- `priv:prop:*` channels remain SA-minted; this API still refuses to
  mint them for employees.
