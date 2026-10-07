# Architecture

## Overview

`AiROS Staff Mobile → FastAPI /api/v1 → domain router → service → repository/query → SQLAlchemy → existing AiROS PostgreSQL`.

This is one deployable modular monolith. The public domains are Auth/Profile, Tasks, Maintenance, Resources/Zones, and Media. API routers contain HTTP concerns; extracted services preserve existing lifecycle rules; repositories preserve tenant-scoped reads; ORM models map the existing schema.

## Boundaries and dependency direction

- Auth → user/company/refresh-token repositories → models.
- Tasks → task service + workspace query → allocation, resource location/state, storage, task/template metadata.
- Maintenance → maintenance service → allocation + resource state → occupancy/task blockers.
- Resources → scoped repository → property/area/zone/resource models.
- Media → authenticated upload route → storage adapter.

Dependencies point API → service/repository → models/DB. Models never import API code. Versioning applies at routes and Pydantic contracts, not persistence.

## Authentication and authorization

The extraction retains Argon2 password verification, HS256 JWT access tokens, hashed refresh tokens, current-user lookup, active-user checks, role checks, property scope, employee assignment scope, and zone/area maintenance coverage.

## Database and migrations

The backend connects to the existing AiROS PostgreSQL schema. All 33 linear Alembic revisions are retained because later employee-required revisions depend on earlier revisions and Alembic must resolve the current database head. Do not initialize an unrelated schema or run destructive migrations against production.

## Infrastructure

PostgreSQL is required. Redis is optional and supports distributed rate limiting; the in-memory fallback preserves development availability. Local, S3-compatible, and Supabase object storage remain available for evidence uploads. Background generation workers are deliberately excluded: employee requests consume generated work but do not own administrative template generation. The complete task/template persistence metadata remains included for SQLAlchemy and task detail compatibility.

## Deployment

Run one API process. Docker Compose supplies optional local Postgres and Redis and runs the retained migration chain before API startup. CORS uses configured origins; wildcard origins are not introduced. Health, DB health, and readiness endpoints are exposed.
