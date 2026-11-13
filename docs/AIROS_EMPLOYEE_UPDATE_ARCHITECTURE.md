# AiROS Employee — Update Architecture

How "there is a newer build" reaches a tester, and what installs it.
Two delivery channels exist; they complement each other.

## Channel A — Firebase App Distribution (primary for dev builds)

- Each distributed release emails/notifies the members of
  `airos-employee-dev-testers`. The Firebase App Distribution tester app
  (or App Distribution's own flows) shows new releases and installs them.
- The app itself makes **no claim** that an update was installed — the
  installed version is always read from native package metadata
  (`App.getInfo`), never inferred from a release's existence.
- Works today for the debug APK; no server cooperation needed.

## Channel B — backend `GET /api/v1/mobile/version` (already implemented)

Contract (verified in `api/mobile.ts` + `services/updateService.ts`):

```
GET /mobile/version?platform=android      (unauthenticated, 10s timeout)
→ { platform, latest_version, latest_version_code,
    minimum_version, minimum_version_code,
    download_url, release_notes, force_update }
```

- `updateService.ts` compares **versionCode** (integer, monotonic —
  never a string compare), honors `minimum_version_code`/`force_update`,
  throttles checks to 4h (forced on cold start, login, resume).
- `UpdateDialog` shows current vs latest + release notes; `required` is
  un-snoozable, `optional` has Update now / Later.
- "Update now" → `AppUpdatePlugin` (`AirosUpdate`) downloads
  `download_url` (same-origin `/api/v1/mobile/apk` proxy or external),
  verifies the APK's versionCode, then hands it to the Android package
  installer (user confirms; `REQUEST_INSTALL_PACKAGES` is declared).
- Failures degrade silently — a dead API never blocks app startup.
- **Release rows** on the backend are created via the service-key-gated
  `POST /mobile/releases*` endpoints — on the dev API this needs the
  `RELEASE_MANAGEMENT_API_KEY` (backend dependency, see testing report).
- For dev builds distributed through Channel A, `download_url` can point
  at the Firebase App Distribution testing link for the release, or at a
  self-hosted APK uploaded via `POST /mobile/releases/apk`.

## Update UI (existing, unchanged)

`UpdateDialog` already implements the required experience: title,
current vs latest version, release notes, Update now / Later actions,
mandatory-update explanation with a working install path and a recovery
route (retry/error states in `updateService`).

## Native vs web-bundle changes — strict rule

| Change type | Delivery path |
|---|---|
| Capacitor plugins, Android permissions, native Java/Kotlin, Gradle deps/config, AndroidManifest | **New APK** → Firebase App Distribution |
| React components, JS logic, CSS, static assets | New APK too — **for now** (see below) |

### OTA / live-update evaluation (deferred)

A Capacitor live-update solution (e.g. Capgo, Capacitor-updater) could
push web-bundle changes without an APK — but it introduces a code-execution
delivery path (signing, rollback, channel management) and paid third-party
cost. Per plan this is a **separate future stage**: Firebase App
Distribution is sufficient for the first testing cycle, and nothing in
this change downloads or executes arbitrary code.

## Versioning convention

- Single source of truth: `frontend/app.json`
  (`expo.version` ↔ `versionName`, `expo.android.versionCode` ↔
  `versionCode`). Gradle reads it directly in `app/build.gradle`.
- Bump with `node scripts/bump-version.mjs <semver> [latestReleasedCode]`
  — it enforces `versionCode = max(repo, released) + 1`; codes are never
  reused.
- Current dev line: **1.0.14 / versionCode 16**.

## Limitations (honest list)

- FAD tester notifications depend on the tester's Firebase Tester app /
  email — delivery timing is Google's, not ours.
- In-app update check requires the dev API + a `mobile_releases` row;
  until the dev API is deployed and a release is registered, the check
  silently reports "no update".
- Debug-signed APKs can't be installed over a differently-signed install
  (must uninstall first) — relevant if a device holds an older build
  signed with another key.
- Android only; no iOS target exists in this repo.
