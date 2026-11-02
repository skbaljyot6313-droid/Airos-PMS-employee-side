# Airos Property Pro — Auto-Update Implementation

Branch `development-branch` · Backend `airos-eb-api-dev` on Cloud Run ·
GCS `final-airos-os-dev-employee-objects-94363806721` (private, ADC).

## Reused (verified working, unchanged)

- `mobile_releases` table + `get_active_release` (single active row per
  platform, ordered by version_code — monotonicity + no-downgrade on
  activation), release mgmt endpoints gated by `RELEASE_MANAGEMENT_API_KEY`.
- `GET /mobile/version` (public), `GET /mobile/apk` (rate-limited proxy —
  devices only ever fetch from the API origin; bucket stays private).
- `updateService.ts` (versionCode-integer compare, 4h throttle, pending-APK
  reconcile, auth-token on the proxied download) + `UpdateDialog`
  (optional/mandatory, notes, progress) + `AppUpdatePlugin` (`AirosUpdate`
  — https-only + trusted-host download, FileProvider content URI,
  signature-compatibility check vs the installed app, versionCode >
  installed gate, pending-APK prefs, `REQUEST_INSTALL_PACKAGES` handling).

## Implemented this change

**Backend** (`backend/`):
- `schemas/mobile.py` — `MobileVersionResponse` + `sha256`,
  `file_size_bytes`, `installed_version_code`, `update_available`,
  `mandatory_update` (all optional/null-safe — backward compatible).
- `api/v1/mobile.py` — `/mobile/version` accepts `installed_version_code`
  query param → server computes `update_available`/`mandatory_update`
  (mandatory = update exists AND (force_update OR below minimum_code));
  `sha256`/`file_size_bytes` read from the stored object's metadata —
  storage errors can never break the version check.
- `api/v1/mobile.py` — `POST /releases/apk` now computes the APK's
  SHA-256 and stamps `{sha256, file_size_bytes}` onto the GCS object.
- `core/storage.py` — `StorageBackend.save(..., metadata=None)` +
  `head(key)`; `GCSStorage` writes/reads blob metadata via ADC; `S3Storage`
  maps metadata too (non-GCP path stays dormant with `GCS_BUCKET` set).

**Android** (`AppUpdatePlugin.java`): pending-APK prefs carry
`sha256`+`size_bytes` (set at `downloadApk`, verified in `installApk`
before the FileProvider handoff): mismatch → pending dropped +
`SIZE_MISMATCH`/`CHECKSUM_MISMATCH` deny. Signature/versionCode/package
gates unchanged. **TS:** bridge options (`expectedSha256`,
`expectedSizeBytes`), `MobileVersionInfo` fields, download call wiring —
`npx tsc --noEmit` clean.

## Schema delta — deferred (approval-gated per spec)

No migration applied. For full `status` (draft/published/withdrawn),
`package_id`, `published_at` columns on `mobile_releases` — a one-revision
Alembic proposal is required; current code is fully functional without it
(`is_active` covers published/withdrawn; publish-time validation lives in
the release workflow below).

## Publish workflow (developer)

```
1. bump:   cd frontend && node scripts/bump-version.mjs <X.Y.Z>   # vc++
2. build:  ..\scripts\build-android-docker.ps1                    # -> dist/android/airos-employee-dev.apk
3. sha256: certutil -hashfile dist\android\*.apk SHA256
4. upload: POST {API}/api/v1/mobile/releases/apk?platform=android&version_code=<vc>
           headers: Authorization: Bearer <RELEASE_MANAGEMENT_API_KEY>, multipart file
           -> {url}  (server stamps sha256+size into GCS metadata)
5. draft:  POST /mobile/releases {version, version_code, minimum_*,
           download_url:<url>, release_notes, force_update}
6. publish: POST /mobile/releases/{id}/activate   # explicit step only
```
New release only becomes installable after `activate`; older releases stay
as rollback targets. **Requires redeploy of the backend image for the new
response fields** — current deployed revision predates this change.

## Test results (actual)

- `pytest tests/unit/test_mobile_releases.py`: **19/19 pass** (incl.
  publish→public-version payload shape, upload stores binary + metadata
  arg, activation, PATCH repoint). 35 related tests pass overall.
- `npx tsc --noEmit`: clean.
- Live API `/mobile/version` (deployed rev): 200 with pre-change shape —
  new fields activate on next backend deploy.

Pending (not run — need a device + redeployed backend + a signed vc17
build): real download, checksum mismatch on-device, interrupted/expired
download, install cancel, vc16→vc17 upgrade, no-network path.

## Limitations

- Checksum verify is silent-skip when a release lacks stamped metadata
  (externally-hosted binaries) — signature+versionCode gates still apply.
- Signed URLs unnecessary: `/mobile/apk` proxies after any URL check —
  bucket never public, no creds exposed.
- Server-side package-ID validation of the binary isn't parsed (binary
  manifest); the device enforces the real package before install and the
  publish step asserts it in release metadata convention.
