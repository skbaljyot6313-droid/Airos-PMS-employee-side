# AiROS Employee — Android Build Reference

## Artifact

| Field | Value |
|---|---|
| Output | `dist/android/airos-employee-dev.apk` (gitignored `dist/`) |
| Type | Debug APK, auto-signed with the Android debug keystore |
| Package ID | `com.theairco.airos.employee` |
| versionName / versionCode | `1.0.14` / `16` (from `frontend/app.json`) |
| Baked API | `https://airos-eb-api-dev-94363806721.asia-south1.run.app/api/v1` (dev only; **no production fallback** — the build script fails if `VITE_API_URL` is unset) |

## How to build

```powershell
.\scripts\build-android-docker.ps1          # Docker Desktop only — no JDK/SDK on host
```

Pipeline inside the container (`frontend/scripts/docker-build-apk.sh`):

1. `npm ci` — lockfile-exact deps (Linux-side volume; host modules untouched)
2. `npm run build` — Vite production bundle with `VITE_API_URL` baked in
3. `npx cap sync android` — copies `dist/` into `android/app/src/main/assets`, regenerates `capacitor-cordova-android-plugins`
4. `gradlew assembleDebug` — repo's own Gradle 8.11.1 wrapper, AGP 8.7.2, compileSdk 35, Java 21
5. `aapt dump badging` — asserts `package='com.theairco.airos.employee'`, prints `versionCode`/`versionName`
6. Copies `app-debug.apk` → `dist/android/<APK_NAME>.apk`

Environment image (`frontend/Dockerfile.android-build`): Temurin 21 + Node 20 + Android cmdline-tools (android-35, build-tools 35.0.0, platform-tools), licenses pre-accepted.

## Versioning rules

- `app.json` is the single version source (`expo.version` → versionName, `expo.android.versionCode` → versionCode). Gradle reads it directly.
- Bump: `cd frontend && node scripts/bump-version.mjs <X.Y.Z> [releasedCode]` — monotonic `versionCode = max(repo, released) + 1`; never reuse a code.
- Signing: debug keystore for dev; release builds use `android/keystore.properties` (gitignored, absent → unsigned warning).

## Preserved features verified in the build

- Permissions: INTERNET, ACCESS_COARSE/FINE_LOCATION, FOREGROUND_SERVICE(+LOCATION), POST_NOTIFICATIONS, REQUEST_INSTALL_PACKAGES
- `LocationTrackingService` (FGS location), `AiroMessagingService` (FCM data-only → shared seen-ledger), `AppUpdatePlugin` (`AirosUpdate`), `LocationTrackerPlugin` (`AirosLocation`)
- Capacitor plugins synced: `@capacitor/app`, `@capacitor/camera`, `@capacitor/geolocation`, `@capacitor/push-notifications`
- `google-services.json` → `final-airos-os` (FCM + App Distribution app)
- `capacitor.config.json` carries no `server.url` — APK bundles `dist/`, never live-loads a dev server
