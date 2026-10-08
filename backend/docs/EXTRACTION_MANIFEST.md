# Extraction manifest

## Calculated inventory

- Total backend files inspected: **143** non-secret source/configuration files plus the secret `.env` as a separate configuration input. The count excludes `.venv`, caches, runtime uploads, `backend.log`, and `.env`; `.env` was inspected only for variable names, copied only to the gitignored runtime location, and never printed.
- Employee-related files identified: **34** direct API, schema, auth, service, repository, and test files.
- Shared dependencies identified: **57** core/domain/model/repository/service files.
- Files in the extracted backend: **132** (including the gitignored runtime `.env`, new API, versioned schema, docs, tests, scripts, and deployment files; caches excluded).
- Files intentionally excluded: **52** indexed source/config files not required at runtime or replaced by focused equivalents.
- Files requiring further investigation: **0** for the current mobile contract. One operational verification remains: connect/readiness against the intended deployed database from an authorized environment. Future mobile use of history/scheduling endpoints requires a new dependency review.

Counts are generated from the repository state at extraction time. The file-level audit is in `FILE_MANIFEST.md`.

## Included employee API

- Login, access-token validation, refresh-token persistence/revocation, `/auth/me`, and self-profile update.
- Employee-scoped task list/detail/start/submit and v1 task serialization.
- Employee-scoped maintenance list/detail/create/eligible-locations/start/resolve.
- Authenticated JPEG/PNG/WebP evidence upload.
- Zone listing used by task filters.
- Health/readiness endpoints.

## Shared dependencies

- All ORM models: required to preserve SQLAlchemy relationship/foreign-key metadata and existing DB compatibility. Template tables are metadata dependencies for task checklist/verification and maintenance evidence rules.
- `StructureService`, `WorkAllocationService`, and location resolution: required by task and maintenance services.
- `ResourceStateService`, occupancy model/service, canonical states/transitions/events: maintenance creation changes resource projections and closure is supervisor-owned.
- Storage, Redis rate limiting, DB/session, logging, middleware, and security.
- The complete linear Alembic chain: later employee-required schema revisions cannot be detached from their ancestors, and the service targets the existing AiROS database head.

## Deliberately excluded

- `api/v1/hr.py`, templates, work batches, and monolithic admin/property CRUD routes.
- HR schemas and HR-only employee administration APIs.
- Property/company administration services and APIs.
- Day/maintenance analytics, reconciliation API, task operations dashboards, template generation service, rollover service, and arq workers.
- Administrative scripts, local uploaded data, logs, and caches. The requested runtime `.env` was copied verbatim but is gitignored; no values are included in documentation or reports.
- Signup: company provisioning is administrative and is not consumed by Staff Mobile.
- Embedded scheduler/worker ownership: employees consume tasks but this API does not generate administrative schedules. The setting remains false for compatibility.

## Dependency graphs

- Auth route → rate limiter/current user → AuthService → user/company/refresh-token repositories → user/company/token models → DB/security.
- Tasks route → current user → WorkspaceRepository/TaskService → Task/Employee/Structure/Template metadata → allocation/location/storage → DB.
- Maintenance route → employee/current-user dependencies → MaintenanceService → allocation + structure + ResourceStateService → occupancy/task blockers → DB.
- Resources route → current user → tenant-scoped WorkspaceRepository → property/area/zone models → DB.
- Media route → current user/rate limiter → storage factory → local or S3/Supabase adapter.

## Migration decision

No migration was removed from the 33-revision linear history. Even apparently administrative revisions are ancestors of the employee-required head. The extracted Alembic environment therefore recognizes the same database version and metadata. Applying migrations remains an explicit operator action.
