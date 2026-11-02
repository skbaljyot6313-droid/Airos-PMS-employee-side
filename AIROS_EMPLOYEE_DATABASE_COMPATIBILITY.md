# AiROS Employee — Database Compatibility Report (Phase 1)

Date: 2026-11-02 · Live state read via Cloud SQL Python Connector
(read-only queries; credentials transient, never printed).

## 1. Live database state — VERIFIED

| Fact | Value |
|---|---|
| Instance | `airos-postgres-dev` (`final-airos-os:asia-south1:airos-postgres-dev`) |
| Engine | PostgreSQL 15, `db-custom-1-3840`, PRIMARY `34.14.182.118` |
| Database | `airos_dev` |
| **`alembic_version`** | **`v9f2b5c8d1e4`** — exactly the employee repo's single head |
| Tables | 39 — every table the employee ORM/migrations declare is present (incl. shared `shifts`, `employee_shift_assignments`, `work_templates*`, `work_allocation_*`, `mobile_releases`, `location_*`, `attendance_*`) |
| Roles | `postgres`, `airos_sa_app` only — **`airos_eb_app` does NOT exist** |

## 2. Employee migration chain — VERIFIED

- 42 revisions, **one linear chain, single head `v9f2b5c8d1e4`**
  (computed: it is the only revision not referenced as a `down_revision`).
- `env.py` sources the URL from `settings.database_url` — no embedded
  credentials; `target_metadata = Base.metadata` (autogen-capable).
- **No auto-migration at startup**: Dockerfile CMD is plain uvicorn;
  compose's `migrate` is a separate one-shot service. Cloud Run will not
  run migrations on boot.

## 3. Shared-history conclusion

The deployed DB sits at the employee chain's head. Two compatible
interpretations — either SA applied the same linear history from the
common extraction, or SA's chain is a superset that includes these
revisions. In both cases:

- **`alembic upgrade head` is a no-op for employee** — nothing to run.
- If a future employee migration lands, it must be coordinated
  (single migration owner — recommend: run migrations as a controlled
  Cloud Run **job**/one-off task with `airos_sa_app`-class owner creds,
  never from `airos_eb_app` at boot).

## 4. Conflicting-migration risk assessment

| Risk | Status |
|---|---|
| Employee startup auto-migrates | **NO** — confirmed absent |
| Employee migrations could alter SA tables | Only if NEW revisions are written; none exist now. Shared read-only tables (`shifts`, `employee_shift_assignments`) are mapped read-only in `models/shift.py` — employee code does not mutate them |
| Overlapping table ownership | Employee writes its own domain tables; SA writes shifts/templates/allocations → `work_allocation_history` ledger is the documented sharing point (employee reads it for notification synthesis; SA writes it) |
| `airos_eb_app` permissions | To be created — least-privilege: `CONNECT` + `USAGE(schema public)` + `SELECT,INSERT,UPDATE,DELETE` on employee-domain tables + `USAGE` on sequences; `SELECT`-only on `shifts`, `employee_shift_assignments`, `work_templates*`, `properties/areas/zones` reference reads it needs; **NO** superuser, **NO** DDL/ownership, **NO** `GRANT` |

## 5. Required actions before deploy (approval-gated)

1. **Create `airos_eb_app`** role + password (billable: $0 — role is free)
   — needs approval: `CREATE ROLE airos_eb_app LOGIN PASSWORD '…'` +
   scoped `GRANT`s. Script prepared on approval.
2. **Decide migration owner**: keep SA/operator-run migrations (recommended)
   — `airos_eb_app` gets **no DDL rights** so it can't migrate even if misused.
3. **Connection budget**: SA service + employee 4 max instances × (2+1 pool)
   ≈ ≤15 connections — far under the `db-custom-1-3840` default limit
   (~100+). Safe; document.
4. **Rollback**: no schema change planned — rollback = delete
   `airos_eb_app` grants if created.

## 6. Open item (not a blocker)

`airos_eb_app` DB password must be minted + stored in Secret Manager
(e.g. `airos-dev-eb-db-password`) alongside the existing
`airos-dev-app-db-password`/`airos-dev-database-url`/`airos-dev-jwt-secret`/
`airos-dev-postgres-password` set.
