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

const LAST_CHECK_KEY = 'airos_update_last_check';
const THROTTLE_MS = 24 * 60 * 60 * 1000;

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

/**
 * Run one update check. Safe to call from login/app-resume paths; resolves
 * silently on any failure. Pass force=true to bypass the 24h throttle.
 */
export async function checkForUpdates(force = false): Promise<UpdateState> {
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
