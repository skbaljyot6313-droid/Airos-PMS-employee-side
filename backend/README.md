# AiROS Employee Backend

Employee-focused FastAPI modular monolith extracted from the AiROS management backend for Staff Mobile. It preserves existing JWT, task, maintenance, resource-state, storage, tenant-scoping, database, and wire behavior while excluding admin/HR/property-management API surfaces.

## Capabilities

- Login, refresh, logout, current user, self-profile update
- Assigned task list/detail/start/submit with history and evidence
- Assigned/reported maintenance list/detail/create/start/resolve
- Employee maintenance location coverage and zone reads
- Authenticated evidence uploads through local or object storage
- Existing AiROS PostgreSQL schema and Alembic history

## Structure

- `app/api/v1`: focused HTTP routers
- `app/schemas/v1`: versioned public contract exports
- `app/services`: preserved domain behavior
- `app/repositories`: scoped reads and auth persistence
- `app/models`: unversioned SQLAlchemy persistence
- `app/domain`: canonical resource-state rules
- `app/core`: config, DB, security, Redis, storage, logging, middleware
- `alembic`: existing database migration history
- `tests`: API contract and extracted dependency tests
- `docs`: architecture, domain, environment, compatibility, and audit manifests

## Local development

```bash
cd new_backend
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# configure DATABASE_URL (or Supabase DB parts) and JWT_SECRET_KEY
alembic upgrade head
uvicorn app.main:app --reload
```

The API is under `/api/v1`; development docs are at `/docs`. `GET /health`, `/health/db`, and `/ready` provide probes.

## Testing

```bash
python -m pytest tests -q
```

For import/OpenAPI-only tests, a syntactically valid PostgreSQL URL is sufficient; tests do not connect unless a DB fixture is used. Extracted domain tests use isolated in-memory SQLite sessions.

## Docker

```bash
docker compose up --build
```

The local stack starts Postgres, Redis, migration, and API services. Production should point at the existing managed AiROS PostgreSQL database and durable S3/Supabase storage.

## Database and migrations

PostgreSQL remains the source of truth. The full linear Alembic history is retained because employee-required revisions depend on earlier ancestors. Never run migrations against production without normal review/backup procedures; this extraction does not reset or fork the schema.

## Mobile integration

Point Staff Mobile's API base to `<origin>/api/v1`. Existing paths and `*_uid` wire fields are preserved. See `docs/MOBILE_COMPATIBILITY.md`.

## Configuration and design

Copy `.env.example`; never commit `.env`. See `docs/ENVIRONMENT.md`, `docs/ARCHITECTURE.md`, and `docs/API_VERSIONING.md`. API versions are contract boundaries; services and models remain shared.
