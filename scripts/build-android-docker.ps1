<#
.SYNOPSIS
  Build the AiROS Employee development APK entirely inside Docker.

.DESCRIPTION
  No JDK or Android SDK is required on the host — the image carries
  Temurin JDK 21 + Android SDK (platform android-35, build-tools 35.0.0).
  Produces dist/android/airos-employee-dev.apk under the repo root.

.PARAMETER ApiUrl
  Employee API base URL baked into the web bundle. Defaults to the
  development Cloud Run service. Must end in /api/v1.

.PARAMETER ApkName
  Output APK file name (without .apk).

.PARAMETER SkipImageBuild
  Reuse the existing airos-employee-android-build:dev image.

.EXAMPLE
  .\scripts\build-android-docker.ps1
  .\scripts\build-android-docker.ps1 -ApiUrl "https://airos-eb-api-dev-94363806721.asia-south1.run.app/api/v1"
#>
[CmdletBinding()]
param(
  [string]$ApiUrl = "https://airos-eb-api-dev-94363806721.asia-south1.run.app/api/v1",
  [string]$ApkName = "airos-employee-dev",
  [switch]$SkipImageBuild
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Frontend = Join-Path $RepoRoot "frontend"
$Image    = "airos-employee-android-build:dev"
$OutDir   = Join-Path $RepoRoot "dist\android"
$OutApk   = Join-Path $OutDir "$ApkName.apk"

if ($ApiUrl -notmatch '/api/v\d+$') {
  Write-Warning "ApiUrl '$ApiUrl' does not end in /api/vN — apiClient appends route paths to it directly."
}

function Require-Docker {
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "docker not found on PATH — install Docker Desktop."
  }
  docker info *> $null
  if ($LASTEXITCODE -ne 0) { throw "Docker daemon is not running — start Docker Desktop first." }
}

Require-Docker

if (-not $SkipImageBuild) {
  Write-Host "==> Building image $Image" -ForegroundColor Cyan
  docker build -f (Join-Path $Frontend "Dockerfile.android-build") -t $Image $Frontend
  if ($LASTEXITCODE -ne 0) { throw "docker build failed ($LASTEXITCODE)" }
}

Write-Host "==> Building APK (VITE_API_URL=$ApiUrl)" -ForegroundColor Cyan
docker run --rm `
  -e "VITE_API_URL=$ApiUrl" `
  -e "APK_NAME=$ApkName" `
  -v "${RepoRoot}:/repo" `
  -v "airos-frontend-node-modules:/repo/frontend/node_modules" `
  -v "airos-gradle-cache:/root/.gradle" `
  -v "airos-android-debug-keys:/root/.android" `
  -w "/repo/frontend" `
  $Image bash scripts/docker-build-apk.sh
if ($LASTEXITCODE -ne 0) { throw "docker build run failed ($LASTEXITCODE)" }

if (-not (Test-Path $OutApk)) { throw "APK not found at $OutApk" }

$size = [math]::Round((Get-Item $OutApk).Length / 1MB, 1)
$hash = (Get-FileHash $OutApk -Algorithm SHA256).Hash
Write-Host ""
Write-Host "==> APK ready" -ForegroundColor Green
Write-Host "    path:   $OutApk"
Write-Host "    size:   ${size} MB"
Write-Host "    sha256: $hash"
