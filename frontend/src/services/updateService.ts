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

/** Installed versionCode from the Android package metadata (App.getInfo().build). */
export async function installedVersionCode(): Promise<number | null> {
  if (!Capacitor.isNativePlatform()) return null;
  try {
    const info = await App.getInfo();
    const code = Number.parseInt(info.build, 10);
    return Number.isFinite(code) ? code : null;
  } catch {
    return null;
  }
}

export function shouldCheckNow(force: boolean, now = Date.now()): boolean {
  if (force) return true;
  if (state.kind === 'required') return true; // re-verify gates cheaply
  try {
    const last = Number(localStorage.getItem(LAST_CHECK_KEY));
    return !Number.isFinite(last) || now - last > THROTTLE_MS;
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
    if (code === null) return state; // web dev / plugin unavailable
    const info = await getMobileVersion();
    stampLastCheck();
    emit(evaluateUpdate(code, info));
  } catch {
    // Network or endpoint failure — the app keeps working; retry later.
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
