# Phase 2 — Query Reduction Report

Branch: `perf/phase-2-query-reduction` (from `perf/phase-1-quick-wins`).
Baseline: `docs/perf/query-audit.md`.

## 2.1 — `GET /bootstrap` consolidated cold-start payload

**Commit**: this commit · **Flag**: `BOOTSTRAP_ENABLED` (default on; `false` → 404).

Collapses the serial startup chain `/auth/me` → `/zones` →
`/attendance/shift` → `/notifications/unread-count` into one call.

| Requirement | Implementation |
|---|---|
| unread_count is a plain count | `NotificationService.unread_count` reused verbatim — no `sync_assignment_notifications` (test: `test_unread_count_never_syncs`) |
| auth lookup once | `get_current_user` dependency only; service performs **zero** `users` queries (test: `test_get_by_id_runs_once_per_request_contract`) |
| sections fail independently | `null` section + `errors[section]` code; client falls back to the legacy endpoint per-section (test: `test_partial_failure_isolated`, `test_no_employee_link_errors_sections`) |
| `ref_version` | deterministic SHA-256[:16] over `{user,company,zones,shift,unread_count}` content — changes iff content changes (test: `test_ref_version_changes_with_content`) |
| company-scoped Redis cache 30-60s | `mt:boot:scope:{company}:{prop|all}` → `{company,zones}`, TTL 45 s, `jsonable_encoder` parity; eviction on `StructureService.create/update/delete_zone` post-commit; SA-backend writes bounded by TTL (tests: cache-hit, eviction) |
| ≤3 DB queries | warm path: shift(1) + unread(1) = **2**; zones+company from cache; cold path: +1 zones (test: `test_query_budget_on_warm_cache`) |
| old endpoints unchanged | `/auth/me`, `/zones`, `/attendance/shift`, `/notifications/unread-count` untouched; `resolve_my_shift` gained an optional `op_date` kwarg — the legacy route passes nothing, so its behavior is identical |

**Response shape**: `{ref_version, user, company, zones:{items,total,page,limit}, shift, unread_count:{unread}, errors}` — each section is wire-identical to its legacy endpoint so the client can fall back without a special parser.

**Divergence note**: bootstrap shift resolution computes `op_date` from the
caller's own `company.operational_day_start` instead of the
Employee→Property→Company lookup — identical for employee-scoped users
(same company); it skips the employee-existence query (an employee with no
row simply yields `not_assigned`).

**Tests**: `tests/unit/test_bootstrap.py` — 10 tests; +52 related tests
(shift/structure/notifications/openapi contract) green.

**Staging check**: compare `X-DB-Count` on `/bootstrap` vs the four legacy
calls on a real property graph; verify `ref_version` stability across
identical payloads and drift across content changes.

## 2.2 — User-row cache for `get_current_user`

**Commit**: this commit · **Key**: `mt:authctx:user:{uid}` · **TTL**: 60 s.

Every authenticated request used to pay one Postgres round trip
(`SELECT users … joinedload(company)`) just to resolve the caller. Now the
users+company row is read-through cached in Redis; a hit rebuilds the ORM
instances and attaches them to the request session.

| Design point | Implementation |
|---|---|
| Reconstruction safety | `_restore_columns` + `make_transient_to_detached` + `session.add` — persistent, columns NOT dirty, updates emit UPDATE (never INSERT, never stale write-back). `merge(load=False)` was tried and rejected — it marks every copied column dirty, which could write stale values back on a later commit. |
| Joined company survives | `user.__dict__["company"]` manual eager-load — `user.company.*` reads work without a lazy query |
| is_active semantics | checked on the returned instance in both paths; a warm cache tolerates deactivation ≤60 s (approved bound — SA-backend writes are TTL-guarded) |
| This service's own writes | `PATCH /auth/me` evicts via `evict_user_cache` post-commit |
| sid revocation | unchanged — checked on every request before the user load, never cached |
| Identity conflict | if the row is already in the session, `session.add` raises → falls back to `session.get` (returns the attached instance) |
| Redis down | falls through to `get_by_id` — identical to before |

**Tests**: `tests/unit/test_user_cache.py` — 7 tests (miss populates,
hit skips DB + restores company, UPDATE-not-INSERT regression, eviction
forces DB read, sid revocation on hits, TTL bound both directions,
no-Redis fallback). Suite: **328/328** green.

**Net effect**: `X-DB-Count` drops by 1 on every authenticated request
(cache-warm), and `X-DB-Exec-ms`/`X-PoolWait-ms` move correspondingly —
exactly what the Phase-0 headers are there to measure.

## 2.3 — `eligible_locations` query reduction

**Commit**: this commit.

| Query | Before | After |
|---|---|---|
| `_employee_coverage` | `session.get(Employee)` + `SELECT zone.id WHERE area_id` (2) | ONE `Employee ⋈ Zone ON area_id` outer join (1) |
| dorms + beds | `selectinload` → 2 queries | `joinedload` → 1 (`.unique().scalars()`) |
| washrooms + fixtures | `selectinload` → 2 queries | `joinedload` → 1 (`.unique().scalars()`) |
| rooms, zones map | unchanged | 2 |
| **Total** | ~8 sequential | **5 sequential** (covered by `test_eligible_locations_query_budget`) |

**Bounded parallelism deliberately not used**: one `AsyncSession` cannot
`asyncio.gather` executes, and opening per-query sessions needs pool
headroom we have not measured yet (Phase 0 `X-PoolWait-ms` data first) —
also breaks in-memory-SQLite test sessions (each connection = a fresh DB).
Joins are cheaper anyway: each removed query saves a full 300–700 ms RTT.

Also benefits `_enforce_employee_coverage` (ticket-submit path) — same
merged coverage query.
