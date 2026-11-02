# AiROS Employee — Mobile Distribution & Infrastructure Audit

Audit date: 2026-11-02 · Branch: `development-branch` (created from
`dev/infrastructure-isolation` @ `309528d`, uncommitted work preserved)

This is the dedicated Employee mobile application repository. The Super
Admin backend is a separate codebase — nothing here touches it.

---

## 1. Verified technology stack

| Spec claim | Verified | Evidence |
|---|---|---|
| Capacitor 7 | YES | `@capacitor/* ^7.x` in `frontend/package.json`; `capacitor.config.json` |
| React 19 | YES | `react ^19.3.1` |
| Vite | YES | `vite ^8.3.0`, `vite.config.ts` |
| TypeScript | YES | `tsconfig.json`, `npm run lint` = `tsc --noEmit` |
| Application ID | YES | `applicationId "com.theairco.airos.employee"` in `app/build.gradle`; `appId` in `capacitor.config.json`; package in `app.json` |
| Native Capacitor (not RN/Expo) | YES | Native `frontend/android/` Gradle project + Capacitor plugins. `app.json`/`eas.json` are Expo-*shaped* config files reused as the version source — no Expo runtime is used |

## 2. Build inputs audit

| Item | Finding |
|---|---|
| `package.json` scripts | `dev` (tsx server.ts), `build` (vite), `lint` (tsc), `test` (vitest), `eas-build-*` hooks |
| Capacitor config | `frontend/capacitor.config.json` — appId + `webDir: dist`; NO `server.url` committed (dev launcher injects transiently, then restores) |
| Android structure | `frontend/android/` standard Capacitor project: `app/`, `capacitor-cordova-android-plugins/` (generated), `variables.gradle`, `capacitor.settings.gradle` |
| namespace vs applicationId | namespace `com.airos.staff` (Java code), applicationId `com.theairco.airos.employee` (installed package) — correct and distinct by design |
| Gradle | AGP **8.7.2**, wrapper **gradle-8.11.1**, compileSdk/targetSdk **35**, minSdk **23** |
| JDK requirement | **Java 21** — `capacitor.build.gradle` sets `VERSION_21`; `settings.gradle` has the foojay-resolver toolchain plugin |
| google-services plugin | `com.google.gms:google-services:4.4.2` classpath present; plugin applied conditionally when `google-services.json` exists |
| FCM | `firebase-messaging:24.1.0` + `@capacitor/push-notifications` + `AiroMessagingService` (data-only FCM → shared seen-ledger) |
| Version source | `app.json` → `expo.version 1.0.14`, `expo.android.versionCode 16` (bumped from 1.0.13/15 via `scripts/bump-version.mjs` — Gradle reads app.json directly) |
| Signing | `keystore.properties` (gitignored) drives the release signing config; absent → unsigned release warning. Debug builds use the auto-generated debug keystore |
| Permissions | INTERNET, COARSE+FINE_LOCATION, FOREGROUND_SERVICE(+LOCATION), POST_NOTIFICATIONS, REQUEST_INSTALL_PACKAGES — all required by existing features |

## 3. API configuration audit

| Item | Finding |
|---|---|
| Fetch boundary | `frontend/src/api/client.ts` is the ONLY URL construction point; `API_BASE = VITE_API_URL` (process env at build time → `.env` files) |
| Dev env | `frontend/.env.development` (gitignored by design) now pins `VITE_API_URL` to the dev Cloud Run URL with `/api/v1` suffix |
| Prod/CI env | `frontend/Dockerfile`, `ci.yml`, `build-android.yml` all pass `VITE_API_URL` explicitly — no production URL exists anywhere in the repo |
| Hardcoded production endpoints | NONE found. The old Railway URL was removed in commit `ca55264`; only doc references remain |
| Secrets in app | NONE. JWT secret lives backend-side only; `google-services.json` API key is a public client key by design |
| Auth | Argon2id + JWT (HS256) + refresh tokens; single-flight 401 refresh in `client.ts`; `airos_unauthorized` → forced sign-out. Unchanged — no Firebase Auth introduced |

## 4. Existing update & notification mechanisms

| Mechanism | State |
|---|---|
| `GET /api/v1/mobile/version` | EXISTS — `api/mobile.ts`; returns `{latest_version, latest_version_code, minimum_version*, download_url, release_notes, force_update}`. Unauthenticated by design |
| In-app updater | COMPLETE — `services/updateService.ts` (versionCode compare, 4h throttle, pending-APK reconcile) + `UpdateDialog` + native `AppUpdatePlugin` (`AirosUpdate`: downloadApk/installApk/canRequestPackageInstalls) + `REQUEST_INSTALL_PACKAGES` |
| Update gating | `UpdateManager` in `App.tsx` — forced updates are un-snoozable; optional updates snoozable per session |
| FCM push | IMPLEMENTED — device token → `POST /devices/register`; `AiroMessagingService` posts tray entries through the shared seen-ledger |
| Release registry | Backend `mobile_releases` table + service-key-gated `POST /mobile/releases*` endpoints exist — usable on the dev API once deployed |
| Firebase App Distribution | Was NOT configured — now set up (see FIREBASE_SETUP doc) |

## 5. CI/CD audit

| Workflow | Purpose | Gaps |
|---|---|---|
| `ci.yml` | backend pytest + frontend typecheck/build + `assembleRelease` on push/PR to `main` | bakes `VITE_API_URL=http://localhost:8000` (fine for CI compile-check); no FAD |
| `build-android.yml` | manual APK artifact (debug/release), release signing via secrets | bakes localhost URL; artifact only, no distribution |
| `dev-distribution.yml` (new) | manual dev build → artifact + optional FAD upload | added by this work; not yet run |

## 6. Blockers found during audit

1. **`airos-eb-api-dev` Cloud Run service does not exist.** The intended
   URL `https://airos-eb-api-dev-94363806721.asia-south1.run.app` returns
   Google-front-end 404 on every path (`/`, `/health`, `/api/v1/*`). Only
   `airos-sa-api-dev` (the Super Admin service) is deployed in
   `final-airos-os/asia-south1`. → API connectivity is **BLOCKED**; app
   config is prepared and pinned, with no fallback.
2. **Committed `google-services.json` pointed to the OLD Firebase project
   `airos-530a5`** (project number 732720607924) — replaced with the
   `final-airos-os` config for the newly registered app.
3. **No `development-branch` existed** — created at the working HEAD;
   uncommitted changes carried over untouched.
4. **No JDK/Android SDK on the host** — builds are fully Dockerized
   (`frontend/Dockerfile.android-build`); host stays clean.

## 7. Conclusions

- The app CAN produce an APK: Gradle config is complete and correct; the
  repo's own wrapper is used; FCM + update + location features are intact.
- Firebase Android app registration did NOT exist → created:
  `1:94363806721:android:a2c92d7ac6a4c2ea066400`.
- App Distribution API is enabled on the project; tester group
  `airos-employee-dev-testers` created (empty — testers must be added).
- Backend version-check works against `mobile_releases`; on the dev API
  there are no releases until one is published via the service-key route.
