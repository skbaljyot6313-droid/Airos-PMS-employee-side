/**
 * Update service — checks the backend release registry and reports whether
 * the installed build is current, outdated, or unsupported.
 *
 * Design rules:
 *  - versionCode is the authoritative comparison (integers — 1.0.10 > 1.0.9
 *    would break a lexicographic compare).
 *  - Throttled to one network check per 24h (cached timestamp); callers can
 *    force a check (login, app resume).
 *  - Never throws, never blocks the app — network failure just defers the
 *    check. Only an explicit `required` result gates usage, and that only
 *    happens after a successful response.
 *  - The installed version comes from the native package metadata via
 *    @capacitor/app — nothing is hardcoded in React code.
 */

import { App } from '@capacitor/app';
import { Capacitor } from '@capacitor/core';

import { getMobileVersion, MobileVersionInfo } from '../api/mobile';
import { NativeUpdate } from './updateInstaller';

const LAST_CHECK_KEY = 'airos_update_last_check';
// Resume checks are throttled to every 4h; app-start and login checks are
// always forced, so a freshly published release is discovered on the next
// cold start regardless of when the last check ran.
const THROTTLE_MS = 4 * 60 * 60 * 1000;

export interface UpdateState {
  kind: 'none' | 'optional' | 'required';
  info: MobileVersionInfo | null;
}

const NONE: UpdateState = { kind: 'none', info: null };
let state: UpdateState = NONE;
const listeners = new Set<(s: UpdateState) => void>();

/** Last diagnostic category — surfaced only by the debug UI; safe values,
 *  never credentials or raw server errors. */
export type UpdateDiag =
  | 'IDLE'
  | 'THROTTLED'
  | 'APP_INFO_ERROR'
  | 'UPDATE_API_ERROR'
  | 'UPDATE_PARSE_ERROR'
  | 'NO_UPDATE'
  | 'OPTIONAL_UPDATE'
  | 'FORCED_UPDATE';
let lastDiag: UpdateDiag = 'IDLE';
export const getUpdateDiag = (): UpdateDiag => lastDiag;

const diag = (category: UpdateDiag, detail?: string) => {
  lastDiag = category;
  // console.info reaches adb logcat (Capacitor/Console) — no secrets logged.
  console.info(`[UPDATE] ${category}${detail ? ` — ${detail}` : ''}`);
};

export function subscribe(listener: (s: UpdateState) => void): () => void {
  listeners.add(listener);
  listener(state);
  return () => listeners.delete(listener);
}

function emit(next: UpdateState): void {
  state = next;
  listeners.forEach((l) => l(state));
}

export function getUpdateState(): UpdateState {
  return state;
}

/** Pure decision — exported for tests. */
export function evaluateUpdate(
  installedCode: number,
  info: MobileVersionInfo,
): UpdateState {
  const required =
    info.force_update || installedCode < info.minimum_version_code;
  if (required) return { kind: 'required', info };
  if (installedCode < info.latest_version_code)
    return { kind: 'optional', info };
  return NONE;
}

/** Installed version info from the Android package metadata — never hardcoded. */
export interface InstalledInfo {
  version: string;
  versionCode: number;
}

export async function installedInfo(): Promise<InstalledInfo | null> {
  if (!Capacitor.isNativePlatform()) return null;
  try {
    const info = await App.getInfo();
    const code = Number.parseInt(info.build, 10);
    console.info(`[UPDATE] installed version=${info.version} versionCode=${info.build}`);
    return Number.isFinite(code) ? { version: info.version, versionCode: code } : null;
  } catch {
    return null;
  }
}

/** Installed versionCode from the Android package metadata (App.getInfo().build). */
export async function installedVersionCode(): Promise<number | null> {
  const i = await installedInfo();
  return i ? i.versionCode : null;
}

export function shouldCheckNow(force: boolean, now = Date.now()): boolean {
  if (force) return true;
  if (state.kind === 'required') return true; // re-verify gates cheaply
  try {
    const last = Number(localStorage.getItem(LAST_CHECK_KEY));
    const due = !Number.isFinite(last) || now - last > THROTTLE_MS;
    if (!due) diag('THROTTLED', `last check ${Math.round((now - last) / 60000)}m ago`);
    return due;
  } catch {
    return true;
  }
}

function stampLastCheck(now = Date.now()): void {
  try {
    localStorage.setItem(LAST_CHECK_KEY, String(now));
  } catch {
    // storage unavailable — next launch just checks again
  }
}

let checkInFlight: Promise<UpdateState> | null = null;

/**
 * Run one update check. Safe to call from startup/login/app-resume paths;
 * resolves silently on any failure. Pass force=true to bypass the throttle.
 * Concurrent callers share a single in-flight request — startup + resume +
 * manual checks can never produce parallel API calls.
 */
export function checkForUpdates(force = false): Promise<UpdateState> {
  if (checkInFlight) return checkInFlight;
  checkInFlight = doCheck(force).finally(() => {
    checkInFlight = null;
  });
  return checkInFlight;
}

async function doCheck(force: boolean): Promise<UpdateState> {
  if (!shouldCheckNow(force)) return state;
  try {
    const code = await installedVersionCode();
    if (code === null) {
      diag('APP_INFO_ERROR');
      return state; // web dev / plugin unavailable
    }
    const info = await getMobileVersion();
    if (!info || typeof info.latest_version_code !== 'number') {
      diag('UPDATE_PARSE_ERROR');
      return state;
    }
    console.info(
      `[UPDATE] latest server version=${info.latest_version} versionCode=${info.latest_version_code} ` +
        `minCode=${info.minimum_version_code} force=${info.force_update}`,
    );
    // Only a successful check updates the throttle timestamp — a failed
    // request must NOT park the app for another 24h.
    stampLastCheck();
    const next = evaluateUpdate(code, info);
    diag(
      next.kind === 'required'
        ? 'FORCED_UPDATE'
        : next.kind === 'optional'
          ? 'OPTIONAL_UPDATE'
          : 'NO_UPDATE',
      `installed=${code} latest=${info.latest_version_code}`,
    );
    emit(next);
  } catch (err) {
    // Network or endpoint failure — the app keeps working; retry later.
    diag('UPDATE_API_ERROR', (err as { code?: string })?.code);
  }
  return state;
}

/** Reset throttle + cached state (logout / tests). */
export function resetUpdateState(): void {
  state = NONE;
  try {
    localStorage.removeItem(LAST_CHECK_KEY);
  } catch {
    // ignore
  }
}

// ---------------------------------------------------------------------------
// In-app download / install flow — the WebView never opens the APK URL;
// the native AirosUpdate plugin downloads, validates, and hands the file to
// Android's package installer.
// ---------------------------------------------------------------------------

export type UpdatePhase =
  | 'idle'
  | 'downloading'
  | 'ready' // APK on disk, pending install
  | 'installing'
  | 'needs_permission'
  | 'error';

export interface UpdateFlow {
  phase: UpdatePhase;
  /** 0–100, or null when the server reports no content length. */
  progress: number | null;
  /** Safe failure category, never a raw server error. */
  error: string | null;
}

const IDLE_FLOW: UpdateFlow = { phase: 'idle', progress: null, error: null };
let flow: UpdateFlow = IDLE_FLOW;
const flowListeners = new Set<(f: UpdateFlow) => void>();

export function subscribeFlow(l: (f: UpdateFlow) => void): () => void {
  flowListeners.add(l);
  l(flow);
  return () => flowListeners.delete(l);
}

const emitFlow = (f: UpdateFlow) => {
  flow = f;
  // The native reject code is the only diagnostic for a failed download —
  // send it to logcat (Capacitor pipes console.* there) so support can
  // read it without rebuilding anything.
  if (f.phase === 'error') {
    console.warn(`[UPDATE] update flow failed: ${f.error}`);
  }
  flowListeners.forEach((l) => l(flow));
};
export const getUpdateFlow = (): UpdateFlow => flow;

let progressListenerBound = false;
function bindProgressListener(): void {
  if (progressListenerBound || !Capacitor.isNativePlatform()) return;
  progressListenerBound = true;
  void NativeUpdate.addListener('downloadProgress', (p) => {
    emitFlow({
      phase: 'downloading',
      progress: p.percent >= 0 ? p.percent : null,
      error: null,
    });
  });
}

/**
 * Delete the pending APK once the installed build reaches/passes it — this
 * is the loop-breaker: after Android swaps in the new version, the pending
 * file is stale and must never trigger another install.
 */
export async function reconcilePending(): Promise<void> {
  if (!Capacitor.isNativePlatform()) return;
  try {
    const [installed, pending] = await Promise.all([
      installedVersionCode(),
      NativeUpdate.getPendingApk(),
    ]);
    if (pending.exists && installed !== null && installed >= (pending.versionCode ?? 0)) {
      await NativeUpdate.deletePendingApk();
      if (flow.phase !== 'idle') emitFlow(IDLE_FLOW);
      return;
    }
    // A valid pending APK for a still-newer release survives.
    if (
      pending.exists &&
      state.info &&
      pending.versionCode === state.info.latest_version_code
    ) {
      // Returning from unknown-sources settings — resume into install.
      if (flow.phase === 'needs_permission') {
        await installPending();
      } else if (flow.phase === 'installing' || flow.phase === 'ready') {
        // The installer was dismissed without installing (a successful
        // update kills this process, so reaching here means it didn't
        // happen). Unstick the flow — Update now reuses the pending APK.
        emitFlow(IDLE_FLOW);
      }
    }
  } catch {
    // plugin absent — nothing to reconcile
  }
}

/** Skip-download check: reuse a valid pending APK for this release. */
export async function pendingMatches(latestCode: number): Promise<boolean> {
  if (!Capacitor.isNativePlatform()) return false;
  try {
    const pending = await NativeUpdate.getPendingApk();
    return pending.exists === true && pending.versionCode === latestCode;
  } catch {
    return false;
  }
}

async function installPending(): Promise<void> {
  emitFlow({ phase: 'installing', progress: null, error: null });
  try {
    await NativeUpdate.installApk();
    // Android's installer is now on top; if the user cancels it, the pending
    // APK stays and 'Update now' retries install without re-downloading.
  } catch (err) {
    const msg = err instanceof Error ? err.message : '';
    emitFlow({
      phase: 'error',
      progress: null,
      error: msg.includes('NO_PENDING') ? 'APK_NOT_FOUND' : 'INSTALL_FAILED',
    });
  }
}

let flowBusy = false;

/** "Update now" — download inside the app, then launch the installer once. */
export async function beginUpdate(info: MobileVersionInfo): Promise<void> {
  if (!Capacitor.isNativePlatform()) return;
  if (flowBusy) return;
  if (flow.phase === 'downloading' || flow.phase === 'installing') return;
  flowBusy = true;

  bindProgressListener();
  try {
    if (await pendingMatches(info.latest_version_code)) {
      await requestInstall();
      return;
    }
    emitFlow({ phase: 'downloading', progress: 0, error: null });
    await NativeUpdate.downloadApk({
      url: info.download_url,
      expectedVersionCode: info.latest_version_code,
    });
    emitFlow({ phase: 'ready', progress: 100, error: null });
    await requestInstall();
  } catch (err) {
    const msg = err instanceof Error ? err.message : '';
    emitFlow({
      phase: 'error',
      progress: null,
      error: msg || 'DOWNLOAD_FAILED',
    });
  } finally {
    flowBusy = false;
  }
}

async function requestInstall(): Promise<void> {
  try {
    const perm = await NativeUpdate.canRequestPackageInstalls();
    if (!perm.allowed) {
      emitFlow({ phase: 'needs_permission', progress: null, error: null });
      return;
    }
    await installPending();
  } catch {
    await installPending();
  }
}

/** "Allow installation" — opens the system unknown-sources settings page. */
export async function openInstallPermissionSettings(): Promise<void> {
  try {
    await NativeUpdate.openInstallPermissionSettings();
  } catch {
    // plugin absent
  }
}

/** Retry after a failed download — the pending file (if any) is reused. */
export function retryUpdate(): void {
  if (state.info) void beginUpdate(state.info);
}

/** Reset flow (used by tests and after logout). */
export function resetUpdateFlow(): void {
  flow = IDLE_FLOW;
}
