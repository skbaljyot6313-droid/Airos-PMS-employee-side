# Dockerized Android Build — AiROS Employee

Build the development APK entirely inside Docker. **No JDK or Android SDK
is required (or installed) on the Windows host** — only Docker Desktop.

## Files

| File | Role |
|---|---|
| `frontend/Dockerfile.android-build` | Build image: Eclipse Temurin JDK 21 + Node 20 + Android cmdline-tools (`platform-tools`, `platforms;android-35`, `build-tools;35.0.0`) — versions match `variables.gradle` (compileSdk 35, AGP 8.7.2); the repo's own Gradle wrapper is used |
| `frontend/scripts/docker-build-apk.sh` | In-container steps: `npm ci` → `vite build` → `cap sync` → `gradlew assembleDebug` → aapt validation → copy APK to `dist/android/` |
| `frontend/docker-compose.android-build.yml` | Declarative equivalent of the `docker run` command |
| `scripts/build-android-docker.ps1` | Windows entrypoint — builds the image, runs the container, verifies the APK |

## Usage

```powershell
# From the repo root — builds the image on first run, then the APK:
.\scripts\build-android-docker.ps1

# Override the API URL or output name:
.\scripts\build-android-docker.ps1 -ApiUrl "https://airos-eb-api-dev-94363806721.asia-south1.run.app/api/v1" -ApkName airos-employee-dev

# Skip the (cached anyway) image build step:
.\scripts\build-android-docker.ps1 -SkipImageBuild
```

Equivalent with compose (from `frontend/`):

```bash
docker compose -f docker-compose.android-build.yml build
docker compose -f docker-compose.android-build.yml run --rm android-build
```

## Output

`dist/android/airos-employee-dev.apk` — a debug-signed APK (Android
auto-generated debug keystore), package `com.theairco.airos.employee`.
The script prints and validates `package` / `versionName` / `versionCode`
via `aapt dump badging` before writing the file.

## Design notes

- **Repo mount**: the repo root mounts at `/repo`; the APK is copied to
  `/repo/dist/android/` → visible on the host at `dist/android/`
  (gitignored).
- **node_modules protection**: a named volume masks
  `frontend/node_modules` — `npm ci` inside the container manages a
  Linux-side install and never corrupts the host's Windows modules.
- **Gradle cache**: named volume `airos-gradle-cache` → repeat builds
  skip dependency downloads.
- **Non-privileged**: the container runs with default capabilities; no
  host credentials or unrelated directories are exposed.
- **API pinning**: `VITE_API_URL` is required — the in-container script
  fails fast if unset (no silent fallback). Default in the PS1/compose is
  the development Cloud Run URL with the mandatory `/api/v1` suffix.
- **`VITE_EMPLOYEE_API_URL`** (compose only) overrides the default
  without editing files.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `docker info` fails | Docker Desktop not running — start it first |
| `working directory ... invalid` (Git Bash) | MSYS path conversion — the PS1 script avoids it; if invoking `docker run` by hand, prefix `MSYS_NO_PATHCONV=1` |
| Gradle can't resolve plugins | Container needs internet; check proxy/VPN |
| First run very slow | Node deps + Gradle cache are cold; subsequent runs reuse named volumes |
| APK old after edits | `vite build`/`cap sync`/`assembleDebug` all re-run each time; the artifact is always fresh — only dependency caches persist |
