# AiROS Employee — Testing Report

Date: 2026-11-02 · Branch: `development-branch` · Build:
`dist/android/airos-employee-dev.apk` (debug, 7.75 MB, sha256 logged by
the build script) · FAD release `3666v6c05p3oo`.

## Verified locally (automated)

| Check | Result |
|---|---|
| Docker image builds | PASS — Temurin 21 + Node 20 + SDK (android-35, build-tools 35.0.0 + 34.0.0 auto-added by AGP) |
| `npm ci` in container | PASS — 340 packages, lockfile-exact |
| `vite build` (dev API baked) | PASS — 1722 modules, prod bundle |
| `npx cap sync android` | PASS — 4 plugins synced (app, camera, geolocation, push-notifications) |
| `gradlew assembleDebug` | PASS — BUILD SUCCESSFUL, 196 tasks, repo wrapper 8.11.1 |
| APK badging | PASS — `package=com.theairco.airos.employee versionName=1.0.14 versionCode=16` |
| FAD upload + notes + distribute | PASS — release `3666v6c05p3oo` live, group `airos-employee-dev-testers` |
| Frontend typecheck (`tsc --noEmit`) | not run here — wired into CI workflow |
| Backend pytest | out of scope — backend untouched |

## BLOCKED — requires manual action

| Item | Status | Needed |
|---|---|---|
| Dev API `airos-eb-api-dev` | **NOT DEPLOYED** — intended URL 404s on all paths | Deploy Employee API to Cloud Run (asia-south1) + run `alembic upgrade head` + set env (DATABASE_URL, JWT_SECRET_KEY, REDIS_URL, S3_*, FCM_SERVICE_ACCOUNT_JSON for **final-airos-os**) |
| Device install / login / feature tests | NOT RUN — no device, API offline | Install APK on a real device once API is up |
| Tester notifications | UNVERIFIED — group has **0 testers** | Add real tester emails in Firebase Console → they get the new-release email/tester-app alert |
| In-app `/mobile/version` check | WIRED but inert | Dev API must exist + a `mobile_releases` row via `POST /mobile/releases` (RELEASE_MANAGEMENT_API_KEY) |

## Real-device checklist (run after API deploy)

Install & identity: APK installs → launches → correct icon/name →
`versionName 1.0.14 / vc16` in Profile → package id matches.

Auth: `/health` reachable → login → session restore → refresh-token
rotation → logout → invalid token rejected (401 → forced sign-out).

Features: tasks list/detail/start/submit w/ photo evidence; maintenance
raise/start/resolve; attendance start/break/end + calendar; My Shift;
zones workspace; notifications feed + toasts; GPS tracking (grant
location permission → `POST /location/*` flows, OS-level work
notifications while backgrounded); media upload (JPEG/PNG/WebP/HEIC ≤10MB).

Update flow: install this build → distribute a second build (bump via
`bump-version.mjs`) → tester gets FAD alert → update installs over it →
`versionCode` increases → sessions/data preserved. Older build cannot
overwrite newer (Android enforces versionCode order).

## Known limitations

- Debug-signed APK can't overlay an install signed with a different key —
  uninstall the old build first.
- Dev API offline means the app will land on the connection-error retry
  screen (by design — no false success, no production fallback).
- `androidPackageRegistrationState: NOT_REGISTERED` on the FAD release —
  cosmetic; the app is registered at project level.
