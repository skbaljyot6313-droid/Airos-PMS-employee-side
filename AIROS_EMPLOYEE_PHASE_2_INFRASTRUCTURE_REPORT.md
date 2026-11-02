# AiROS Employee — Phase 2 Infrastructure Report

Date: 2026-11-02 · Project `final-airos-os` (94363806721) · Region `asia-south1`.
No secret values appear in this document.

## 1. Database role — `airos_eb_app` (CREATED + grants applied)

Flags verified: `rolcanlogin=t`, superuser/createdb/createrole/replication/bypassrls all `f`.

### Permission matrix (validated against ORM writes in services/*)

| Tables | Grants | Basis |
|---|---|---|
| users, refresh_tokens, companies, employees | SELECT/INSERT/UPDATE/DELETE | auth + PATCH /me + refresh lifecycle |
| tasks, task_history_events, task_completion_submissions, task_completion_images | DML | start/submit/evidence |
| maintenance_tickets, _events, _attachments | DML | ticket CRUD lifecycle |
| rooms, dorms, beds, washrooms, washroom_fixtures | DML | ResourceStateService status transitions |
| resource_state_events, audit_events | DML | event ledgers (insert-only in practice) |
| attendance_days, attendance_breaks, attendance_requests | DML | workday + leave requests |
| notifications, device_registrations | DML | feed + push tokens |
| location_events, location_tracking_sessions | DML | geo evidence + session lifecycle |
| mobile_releases | DML | version read + service-key release mgmt |
| occupancies | DML* | reads for derive(); writes only if SA-flown paths ever run here |
| properties, areas, zones | **SELECT only** | scope/reference reads |
| shifts, employee_shift_assignments | **SELECT only** | SA-owned (models/shift.py read-only) |
| work_templates*, template_generations, work_allocation_*, zone/area_allocation_state, allocation_events | **SELECT only** | shared SA ledger reads (notification sync) |
| alembic_version | **SELECT only** | migration owned externally |
| sequences (all, public) | USAGE/SELECT | defensive — PKs are app-side UUIDs |

No DDL, no ownership, no superuser. `postgres` and `airos_sa_app` untouched.

## 2. Secrets (references only)

- `airos-dev-eb-db-password` — **new**, random 32-byte token (role password)
- `airos-dev-eb-jwt-secret` — **new**, dedicated Employee JWT secret
- Existing (SA-owned, referenced not modified): `airos-dev-app-db-password`, `airos-dev-database-url`, `airos-dev-jwt-secret`, `airos-dev-postgres-password`

**JWT cross-verification decision:** dedicated secret is safe — EB↔SA service calls use `LOCATION_SERVICE_API_KEY` shared bearer (constant-time), never user JWTs. Mobile tokens are EB-issued/EB-verified only.

## 3. Runtime service account — `airos-eb-dev-runtime` (CREATED)

| Binding | Role | Scope |
|---|---|---|
| Project | `roles/cloudsql.client` | Cloud SQL Connector auth |
| Secret `airos-dev-eb-db-password` | `roles/secretmanager.secretAccessor` | secret-level |
| Secret `airos-dev-eb-jwt-secret` | `roles/secretmanager.secretAccessor` | secret-level |
| Project | `roles/firebasecloudmessaging.admin` | FCM HTTP v1 send (least-privilege predefined role containing `firebasecloudmessaging.messages.create`) |
| Bucket `final-airos-os-dev-employee-objects-94363806721` | `roles/storage.objectAdmin` | **bucket-scoped** object R/W |

No Editor/Owner/SA-admin roles. ADC used everywhere — no key files.

## 4. Redis — `airos-redis-dev` (provisioning)

| Field | Value |
|---|---|
| Tier/size | BASIC, 1 GB, redis_7_2 |
| Network | `default` VPC, `connectMode=DIRECT_PEERING` (no public IP; reachable via Cloud Run **direct VPC egress** — no connector needed) |
| Endpoint | `redis://<host>:6379` — host assigned on READY (still CREATING at report time) |

**Cost:** ~$0.049/GB-hr × 730h ≈ **$35.8/mo ≈ ₹3,000** — under the ₹4,000 cap *because* direct VPC egress is free (a Serverless VPC connector would add ~$18/mo and breach it).

## 5. GCS — `gs://final-airos-os-dev-employee-objects-94363806721` (CREATED)

- Location `asia-south1`, STANDARD class, **uniform bucket-level access ON, public-access-prevention enforced**.
- Code: new `GCSStorage` backend in `app/core/storage.py` (google-cloud-storage + ADC, deferred import), selected when `GCS_BUCKET` is set; S3 remains for other envs. `storage_key_from_url` maps `storage.googleapis.com/<bucket>/<key>` back to keys; proxy `/media/file/{key}` unchanged — no public/signed URLs needed for the app's read path (server-side streaming stays the access pattern; signed-URL support can be added later for direct-download cases).
- `google-cloud-storage>=2.18` added to `requirements.txt` + `pyproject.toml`.
- SA↔EB shared-file access: **not granted** — documented requirement, needs a separate decision if SA must read employee objects.

## 6. Cost summary (monthly, dev)

| Resource | Est. |
|---|---|
| Memorystore Redis BASIC 1GB | ~$36 ≈ ₹3,000 |
| GCS (dev usage) | <$1 ≈ <₹85 |
| Cloud Run 2vCPU/1GiB, min 1 | ~$30-45 ≈ ₹2,500-3,800 (deploy-phase cost, flagged now) |
| Secrets/SQL client/etc | ~$0 |
| **Total infra now** | **≈ ₹3,100 + Cloud Run at deploy** |

## 7. Outstanding issues

- Redis endpoint pending (CREATING) — fill `REDIS_URL` once host issued.
- Signed URLs: not implemented (proxy path covers current reads) — evaluate if SA needs direct object reads.
- `FCM_SERVICE_ACCOUNT_JSON` path still supported as fallback; recommended: keep `PUSH_PROVIDER=fcm` + refactor to ADC later, or put SA-JSON in a secret (decision recorded, non-blocking).
