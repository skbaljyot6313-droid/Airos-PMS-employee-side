/**
 * Live location tracker — foreground-only, ~10 s cadence.
 *
 * Runs while an employee session is authenticated (wired in App.tsx).
 * Native-only: skipped entirely on web dev so the browser never prompts.
 * No background tracking, no wake locks — the OS may suspend the loop
 * when the app is backgrounded; the next foreground tick resumes it.
 *
 * Failure model — every failure skips the cycle, never breaks the app:
 *   permission denied   → request once at first start, log once, stop
 *   GPS unavailable     → getCurrentPosition rejects → skip cycle
 *   network/API failure → postCurrentLocation throws → skip cycle
 */

import { Capacitor } from '@capacitor/core';
import { Geolocation } from '@capacitor/geolocation';
import { postCurrentLocation } from '../api/location';

export const LOCATION_INTERVAL_MS = 10_000;
const POSITION_TIMEOUT_MS = 8_000;

let running = false;
let timer: ReturnType<typeof setTimeout> | null = null;
/** True once the OS permission prompt has been shown this app run —
 *  denial must never re-prompt on later start() calls. */
let permissionAsked = false;
let denialLogged = false;

/** Ensure fine-location permission. Requests once per app run; after a
 *  denial, later calls re-CHECK only (a grant via system settings is
 *  picked up without another prompt). */
async function ensurePermission(): Promise<boolean> {
  try {
    let status = await Geolocation.checkPermissions();
    if (status.location !== 'granted' && !permissionAsked) {
      permissionAsked = true;
      status = await Geolocation.requestPermissions({
        permissions: ['location'],
      });
    }
    if (status.location === 'granted') {
      denialLogged = false;
      return true;
    }
    if (!denialLogged) {
      denialLogged = true;
      console.warn('Location permission denied — live tracking disabled');
    }
    return false;
  } catch (err) {
    // System location services off / plugin missing — same degrade path.
    if (!denialLogged) {
      denialLogged = true;
      console.warn('Location permission check failed:', err);
    }
    return false;
  }
}

/** One fix → one POST. All errors are swallowed: a bad cycle is a skip,
 *  not a crash — the next scheduled tick retries on its own. */
async function tick(): Promise<void> {
  try {
    const pos = await Geolocation.getCurrentPosition({
      enableHighAccuracy: true,
      timeout: POSITION_TIMEOUT_MS,
    });
    const c = pos.coords;
    if (
      !Number.isFinite(c.latitude) ||
      !Number.isFinite(c.longitude) ||
      !Number.isFinite(c.accuracy)
    ) {
      return; // malformed fix — nothing worth sending
    }
    await postCurrentLocation({
      latitude: c.latitude,
      longitude: c.longitude,
      accuracy: c.accuracy,
      ...(Number.isFinite(c.speed) ? { speed: c.speed as number } : {}),
      ...(Number.isFinite(c.heading) ? { heading: c.heading as number } : {}),
      timestamp: Math.floor((pos.timestamp || Date.now()) / 1000),
    });
  } catch {
    // GPS timeout, revoked permission, offline, 503 (Redis down) — skip.
  }
}

/** Self-scheduling loop — the NEXT tick is armed only after the current
 *  one settles, so a slow GPS fix can never overlap a later cycle. */
async function loop(): Promise<void> {
  await tick();
  if (running) {
    timer = setTimeout(() => void loop(), LOCATION_INTERVAL_MS);
  }
}

/** Start the foreground loop. Idempotent; a no-op on web and a silent
 *  no-op when permission is denied. */
export async function startLocationTracking(): Promise<void> {
  if (running) return;
  if (!Capacitor.isNativePlatform()) return; // native-only this phase
  if (!(await ensurePermission())) return;
  running = true;
  void loop();
}

/** Stop the loop (logout / unmount). A tick already in flight finishes
 *  but is dropped by the running flag before scheduling continues. */
export function stopLocationTracking(): void {
  running = false;
  if (timer) {
    clearTimeout(timer);
    timer = null;
  }
}
