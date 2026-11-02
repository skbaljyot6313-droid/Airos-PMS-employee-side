# AiROS Employee — Development Release Workflow

Repeatable dev-build → distribute flow. All builds are development-only
(debug-signed, dev API). Nothing here touches production, Railway,
Supabase, or the Super Admin codebase.

## Prerequisites (once)

- Docker Desktop running (builds) — see `ANDROID_DOCKER_BUILD.md`
- `gcloud auth login` as a `final-airos-os` editor (local distribution)
- Testers added to group `airos-employee-dev-testers` (Firebase Console →
  App Distribution → Testers & Groups) — group exists, testers are NOT
  pre-seeded
- Dev API deployed (`airos-eb-api-dev`) — see "Backend dependency" below

## Local release

```powershell
# 1. Bump version (monotonic versionCode)
cd frontend; node scripts/bump-version.mjs 1.0.15; cd ..

# 2. Build the dev APK -> dist/android/airos-employee-dev.apk
.\scripts\build-android-docker.ps1

# 3. Distribute to testers (uses your gcloud credentials)
$env:GOOGLE_APPLICATION_CREDENTIALS=""   # use ADC: gcloud auth application-default login
firebase appdistribution:distribute dist/android/airos-employee-dev.apk `
  --app 1:94363806721:android:a2c92d7ac6a4c2ea066400 `
  --groups airos-employee-dev-testers `
  --release-notes "1.0.15 (vc16) | <sha> | dev API | <notes>"
```

Or via REST (no firebase CLI needed — used by `dev-distribution.yml`):

```
POST .../upload/v1/projects/94363806721/apps/<appId>/releases:upload   (binary)
POST .../v1/<release>:updateReleaseNotes
POST .../v1/<release>:distribute    { testerGroupResourceNames: […/airos-employee-dev-testers] }
```

## CI release (`.github/workflows/dev-distribution.yml`)

- Manual `workflow_dispatch` only — never auto-fires.
- Steps: typecheck → `npm ci` → vite build (dev API env) → cap sync →
  `assembleDebug` → aapt validation → artifact upload → optional FAD
  distribute when `distribute=true`.
- Requires repo secret `FIREBASE_SERVICE_ACCOUNT_EMPLOYEE_DEV` (service
  account JSON, *Firebase App Distribution Admin* role, final-airos-os)
  or WIF — never committed, never echoed.

## Release notes template

```
1.0.14 (vc16) · <short-sha> · dev API: airos-eb-api-dev
Changes: <what changed>
Known issues: <or "none">
Built: <UTC timestamp>
```

## Backend dependency (blocking real end-to-end use)

`airos-eb-api-dev` is **not deployed** — the intended URL returns 404.
Required before device testing:
1. Deploy the Employee API to Cloud Run `airos-eb-api-dev` in
   `final-airos-os/asia-south1` (Dockerfile exists at `backend/Dockerfile`;
   `gcloud run deploy` + env: `DATABASE_URL`, `JWT_SECRET_KEY`, Redis,
   S3 creds — do NOT reuse production values).
2. Run Alembic migrations on the dev database (`alembic upgrade head`).
3. (FCM) Set `FCM_SERVICE_ACCOUNT_JSON` to a **final-airos-os** service
   account — the app's tokens are now issued under this project.
4. (In-app updates) Create a `mobile_releases` row via
   `POST /mobile/releases` with `RELEASE_MANAGEMENT_API_KEY` if the
   in-app version check should also fire; FAD notifications alone are
   sufficient for dev.
