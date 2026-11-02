#!/usr/bin/env bash
# In-container build for the AiROS Employee dev APK.
#
# Runs inside the Dockerfile.android-build image with the repo mounted at
# /repo. Steps: npm ci -> vite build (dev API baked via VITE_API_URL) ->
# cap sync -> gradlew assembleDebug -> copy APK to /repo/dist/android/.
set -euo pipefail

REPO="${REPO_ROOT:-/repo}"
FRONTEND="$REPO/frontend"
ANDROID="$FRONTEND/android"
OUT_DIR="$REPO/dist/android"
OUT_APK="${APK_NAME:-airos-employee-dev}.apk"

# The dev API base is REQUIRED — no silent fallback, ever.
: "${VITE_API_URL:?VITE_API_URL must be set (e.g. https://airos-eb-api-dev-94363806721.asia-south1.run.app/api/v1)}"
echo "[build] VITE_API_URL=$VITE_API_URL"

cd "$FRONTEND"

echo "[build] npm ci"
npm ci --no-audit --no-fund

echo "[build] vite build"
npm run build

echo "[build] cap sync android"
npx cap sync android

echo "[build] gradlew assembleDebug"
cd "$ANDROID"
# The mounted repo may carry CRLF line endings (Windows checkout) which
# break the gradlew shell script — run a CR-stripped temp copy from the
# same directory so APP_HOME resolution still works.
GRADLEW_TMP="./.gradlew-lf"
trap 'rm -f "$GRADLEW_TMP"' EXIT
sed 's/\r$//' ./gradlew > "$GRADLEW_TMP"
bash "$GRADLEW_TMP" assembleDebug --no-daemon

APK="$ANDROID/app/build/outputs/apk/debug/app-debug.apk"
[ -f "$APK" ] || { echo "[build] ERROR: APK not found at $APK"; exit 1; }

# Validate the artifact — aapt badging must match the expected identity.
AAPT="${ANDROID_HOME}/build-tools/35.0.0/aapt"
BADGING="$("$AAPT" dump badging "$APK")"
PKG="$(echo "$BADGING" | sed -n "s/^package: name='\([^']*\)'.*/\1/p")"
VCODE="$(echo "$BADGING" | sed -n "s/.*versionCode='\([^']*\)'.*/\1/p")"
VNAME="$(echo "$BADGING" | sed -n "s/.*versionName='\([^']*\)'.*/\1/p")"
echo "[build] package=$PKG versionName=$VNAME versionCode=$VCODE"
[ "$PKG" = "com.theairco.airos.employee" ] || {
  echo "[build] ERROR: unexpected package '$PKG'"; exit 1; }

mkdir -p "$OUT_DIR"
cp "$APK" "$OUT_DIR/$OUT_APK"
echo "[build] APK written to $OUT_DIR/$OUT_APK"
ls -la "$OUT_DIR"
