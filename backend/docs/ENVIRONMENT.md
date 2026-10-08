# Environment

| Variable | Purpose | Required | Used by | Secret | Default |
|---|---|---:|---|---:|---|
| `DATABASE_URL` | Async PostgreSQL URL | Yes, unless Supabase parts are set | DB/Alembic | Yes | none |
| `SUPABASE_DB_HOST/PORT/NAME/USER/PASSWORD` | Build DB URL from parts | Alternative | DB | password only | documented in `.env.example` |
| `JWT_SECRET_KEY` | Sign access tokens | Yes in production | Auth | Yes | empty |
| `JWT_ALGORITHM` | JWT algorithm | No | Auth | No | HS256 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access lifetime | No | Auth | No | 30 |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh lifetime | No | Auth | No | 30 |
| `CORS_ORIGINS` | Allowed comma-separated origins | No | FastAPI | No | localhost:3000 |
| `REDIS_URL` | Distributed rate limiter | No | Rate limiting | May be | none |
| `RATE_LIMIT_ENABLED` | Enable endpoint limits | No | API | No | true |
| `STORAGE_BACKEND` | `local`, `s3`, `supabase`, or `auto` | No | Media | No | auto |
| `UPLOAD_DIR` | Local upload directory | Local only | Media | No | uploads |
| `S3_ENDPOINT_URL/REGION/BUCKET/PUBLIC_BASE_URL` | Object-store routing | S3 only | Media | No | varies |
| `S3_ACCESS_KEY/S3_SECRET_KEY` | Object-store credentials | S3 only | Media | Yes | none |
| `SUPABASE_URL/SUPABASE_SECRET_KEY/SUPABASE_STORAGE_BUCKET` | Supabase storage | Supabase only | Media | key is secret | none/uploads |
| `DB_POOL_SIZE/MAX_OVERFLOW/RECYCLE/TIMEOUT` | SQLAlchemy pool tuning | No | DB | No | see example |
| `APP_NAME/APP_ENV/DEBUG/API_V1_PREFIX` | Application metadata/runtime | No | App | No | see example |

`RUN_EMBEDDED_SCHEDULER` is retained for configuration compatibility but defaults false: this employee API does not own generation jobs. Never commit `.env`.
