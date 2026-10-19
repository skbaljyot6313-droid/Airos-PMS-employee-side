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
