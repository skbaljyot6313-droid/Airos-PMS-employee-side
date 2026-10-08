/**
 * Location tracking orchestrator — the JS half of background tracking.
 *
 * Capture/upload live ENTIRELY in the native LocationTrackingService
 * (foreground service + Fused Location Provider + on-disk retry queue).
 * This module only:
 *   1. mints/stops backend tracking sessions (/location/start|stop),
 *   2. hands the native service its upload config (URL + tokens),
 *   3. adopts an already-running service after app restart,
 *   4. keeps native credentials fresh after token refresh.
 *
 * No setInterval, no WebView-dependent capture — the OS owns the loop.
 * Web dev is a no-op (plugin absent). Every failure degrades silently:
 * tracking is observability, it must never break the app.
 */

import { Capacitor } from '@capacitor/core';
import { Geolocation } from '@capacitor/geolocation';
import {
  startTrackingSession,
  stopTrackingSession,
} from '../api/location';
import {
  API_BASE,
  secureStorage,
  TOKEN_REFRESHED_EVENT,
} from '../api/client';
import { NativeLocation } from './nativeLocation';

/** localStorage key for the active backend session — lets a relaunched
 *  app adopt the service's session instead of minting a duplicate. */
const SESSION_KEY = 'airos_tracking_session';

let starting = false;
let permissionAsked = false;
let denialLogged = false;
let listenersArmed = false;

function storedSession(): string | null {
  try {
    return localStorage.getItem(SESSION_KEY);
  } catch {
    return null;
  }
}

function setStoredSession(id: string | null): void {
  try {
    if (id) localStorage.setItem(SESSION_KEY, id);
    else localStorage.removeItem(SESSION_KEY);
  } catch {
    /* storage unavailable — tracking still runs natively */
  }
}

/** Fine-location permission — requested once per app run; later calls
 *  only re-check (a grant via system settings is picked up). */
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
      console.warn('Location permission denied — tracking disabled');
    }
    return false;
  } catch (err) {
    if (!denialLogged) {
      denialLogged = true;
      console.warn('Location permission check failed:', err);
    }
    return false;
  }
}

/** Push current credentials to the service — it also self-refreshes on
 *  401, but pushing fresh tokens after a WebView refresh avoids a wasted
 *  request cycle. */
async function pushAuth(): Promise<void> {
  const accessToken = secureStorage.getToken();
  if (!accessToken) return;
  try {
    await NativeLocation.updateAuth({
      accessToken,
      ...(secureStorage.getRefreshToken()
        ? { refreshToken: secureStorage.getRefreshToken()! }
        : {}),
    });
  } catch {
    /* service absent/stopped — next start() carries tokens anyway */
  }
}

function armListeners(): void {
  if (listenersArmed || typeof window === 'undefined') return;
  listenersArmed = true;
  window.addEventListener(TOKEN_REFRESHED_EVENT, () => {
    void pushAuth();
  });
}

/**
 * Start tracking. Idempotent and restart-safe:
 *  - service already running → adopt its session, done;
 *  - otherwise → mint a backend session, configure, launch the service.
 */
export async function startLocationTracking(): Promise<void> {
  if (!Capacitor.isNativePlatform()) return;
  if (starting) return;
  starting = true;
  try {
    armListeners();
    const accessToken = secureStorage.getToken();
    if (!accessToken) return;

    const state = await NativeLocation.getState();
    if (state.running && state.sessionId) {
      setStoredSession(state.sessionId);
      void pushAuth(); // tokens may have rotated while the app was dead
      return;
    }
    if (!(await ensurePermission())) return;

    const { tracking_session_id, tracking_interval_seconds } =
      await startTrackingSession();
    await NativeLocation.start({
      apiBase: API_BASE,
      accessToken,
      ...(secureStorage.getRefreshToken()
        ? { refreshToken: secureStorage.getRefreshToken()! }
        : {}),
      sessionId: tracking_session_id,
      intervalSeconds: tracking_interval_seconds,
    });
    setStoredSession(tracking_session_id);
  } catch {
    // Backend down / plugin missing — the app still works; the next
    // reconcile (resume or auth change) retries.
  } finally {
    starting = false;
  }
}

/**
 * Stop tracking — service first (so no further fixes upload), then the
 * backend session. Both best-effort: a dead network must not wedge logout.
 */
export async function stopLocationTracking(): Promise<void> {
  if (!Capacitor.isNativePlatform()) return;
  try {
    await NativeLocation.stop();
  } catch {
    /* plugin absent or already stopped */
  }
  const sid = storedSession();
  setStoredSession(null);
  if (sid) {
    try {
      await stopTrackingSession(sid);
    } catch {
      // Server-side the marker TTL expires; the session row stays an
      // accurate 'still open at last contact' record.
    }
  }
}
