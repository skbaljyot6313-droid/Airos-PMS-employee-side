import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock the HTTP boundary — the api module under test calls apiClient,
// and the tracker reaches it through src/api/location.ts.
// vi.hoisted: mock factories run before module-level consts.
const { apiClientMock, secureStorageMock } = vi.hoisted(() => ({
  apiClientMock: vi.fn(),
  secureStorageMock: {
    getToken: vi.fn(),
    getRefreshToken: vi.fn(),
    setTokens: vi.fn(),
    setAccessToken: vi.fn(),
    clearTokens: vi.fn(),
  },
}));
vi.mock('../client', () => ({
  apiClient: (...args: unknown[]) => apiClientMock(...args),
  secureStorage: secureStorageMock,
  API_BASE: 'https://api.test/api/v1',
  TOKEN_REFRESHED_EVENT: 'airos_token_refreshed',
}));

// Mock the Capacitor seams — vitest runs on Node, never a native bridge.
const isNative = vi.fn();
vi.mock('@capacitor/core', () => ({
  Capacitor: { isNativePlatform: () => isNative() },
}));
const checkPermissions = vi.fn();
const requestPermissions = vi.fn();
vi.mock('@capacitor/geolocation', () => ({
  Geolocation: { checkPermissions, requestPermissions },
}));

// The native bridge — registerPlugin can't run under Node.
const nativeLocation = vi.hoisted(() => ({
  start: vi.fn(),
  stop: vi.fn(),
  updateAuth: vi.fn(),
  getState: vi.fn(),
  openBatteryOptimizationSettings: vi.fn(),
}));
vi.mock('../../services/nativeLocation', () => ({
  NativeLocation: nativeLocation,
}));

import { getCurrentLocation, postCurrentLocation } from '../location';

// Node test env — the tracker persists its session id in localStorage
// and listens for token refreshes on window.
const store = new Map<string, string>();
vi.stubGlobal('localStorage', {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => void store.set(k, String(v)),
  removeItem: (k: string) => void store.delete(k),
  clear: () => store.clear(),
});
vi.stubGlobal('window', {
  dispatchEvent: () => true,
  addEventListener: () => {},
  removeEventListener: () => {},
});

const fix = {
  latitude: 12.9716,
  longitude: 77.5946,
  accuracy: 8,
  speed: 1.2,
  heading: 90,
  timestamp: 1_760_000_000,
};

beforeEach(() => {
  vi.clearAllMocks();
  isNative.mockReturnValue(false);
});

// ---------------------------------------------------------------------------
// api module — POST/GET contract over /location/current
// ---------------------------------------------------------------------------

describe('location api', () => {
  it('postCurrentLocation POSTs the fix with a bounded timeout', async () => {
    apiClientMock.mockResolvedValue({
      recorded: true,
      server_timestamp: 1_760_000_001,
      expires_in: 60,
    });
    const ack = await postCurrentLocation(fix);
    expect(apiClientMock).toHaveBeenCalledWith('/location/current', {
      method: 'POST',
      body: JSON.stringify(fix),
      timeoutMs: 8000,
    });
    expect(ack).toEqual({
      recorded: true,
      server_timestamp: 1_760_000_001,
      expires_in: 60,
    });
  });

  it('postCurrentLocation omits undefined optional fields', async () => {
    apiClientMock.mockResolvedValue({ recorded: true, server_timestamp: 1, expires_in: 60 });
    const { speed: _s, heading: _h, ...minimal } = fix;
    await postCurrentLocation(minimal);
    const body = JSON.parse(apiClientMock.mock.calls[0][1].body as string);
    expect(body).toEqual(minimal);
    expect('speed' in body).toBe(false);
    expect('heading' in body).toBe(false);
  });

  it('getCurrentLocation GETs the caller-owned fix', async () => {
    apiClientMock.mockResolvedValue({ is_live: false, employee_uid: 'emp-1' });
    const res = await getCurrentLocation();
    expect(apiClientMock).toHaveBeenCalledWith('/location/current');
    expect(res.is_live).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// locationTracker — session orchestration over the native service
// ---------------------------------------------------------------------------

describe('locationTracker', () => {
  let tracker: typeof import('../../services/locationTracker');
  const granted = { location: 'granted', coarseLocation: 'granted' };
  const sid = '9f1c2d3e-aaaa-4bbb-8ccc-000000000001';

  beforeEach(async () => {
    vi.resetModules(); // fresh module state per test
    localStorage.clear();
    isNative.mockReturnValue(true);
    secureStorageMock.getToken.mockReturnValue('access-1');
    secureStorageMock.getRefreshToken.mockReturnValue('refresh-1');
    nativeLocation.getState.mockResolvedValue({
      running: false, sessionId: null, sequenceNumber: 0,
      lastFixAt: 0, queuedCount: 0,
    });
    checkPermissions.mockResolvedValue(granted);
    apiClientMock.mockResolvedValue({
      tracking_session_id: sid,
      started_at: '2026-10-08T11:00:00Z',
      tracking_interval_seconds: 30,
    });
    tracker = await import('../../services/locationTracker');
  });

  it('is a full no-op on web (non-native platform)', async () => {
    isNative.mockReturnValue(false);
    await tracker.startLocationTracking();
    await tracker.stopLocationTracking();
    expect(checkPermissions).not.toHaveBeenCalled();
    expect(apiClientMock).not.toHaveBeenCalled();
    expect(nativeLocation.getState).not.toHaveBeenCalled();
  });

  it('mints a session then starts the native service with auth config', async () => {
    await tracker.startLocationTracking();

    expect(apiClientMock).toHaveBeenCalledWith('/location/start', {
      method: 'POST',
      body: '{}',
    });
    expect(nativeLocation.start).toHaveBeenCalledWith({
      apiBase: 'https://api.test/api/v1',
      accessToken: 'access-1',
      refreshToken: 'refresh-1',
      sessionId: sid,
      intervalSeconds: 30,
    });
    expect(localStorage.getItem('airos_tracking_session')).toBe(sid);
  });

  it('adopts a still-running service instead of minting a session', async () => {
    nativeLocation.getState.mockResolvedValue({
      running: true, sessionId: sid, sequenceNumber: 41,
      lastFixAt: Date.now(), queuedCount: 0,
    });
    await tracker.startLocationTracking();
    expect(apiClientMock).not.toHaveBeenCalledWith(
      '/location/start', expect.anything());
    expect(nativeLocation.start).not.toHaveBeenCalled();
    expect(localStorage.getItem('airos_tracking_session')).toBe(sid);
    // fresh tokens are pushed to the running service
    expect(nativeLocation.updateAuth).toHaveBeenCalledWith({
      accessToken: 'access-1', refreshToken: 'refresh-1',
    });
  });

  it('does nothing when there is no access token', async () => {
    secureStorageMock.getToken.mockReturnValue(null);
    await tracker.startLocationTracking();
    expect(nativeLocation.getState).not.toHaveBeenCalled();
    expect(apiClientMock).not.toHaveBeenCalled();
  });

  it('requests permission once and never re-prompts after denial', async () => {
    const denied = { location: 'denied', coarseLocation: 'denied' };
    checkPermissions.mockResolvedValue(denied);
    requestPermissions.mockResolvedValue(denied);

    await tracker.startLocationTracking();
    expect(requestPermissions).toHaveBeenCalledTimes(1);
    expect(apiClientMock).not.toHaveBeenCalled();
    expect(nativeLocation.start).not.toHaveBeenCalled();

    await tracker.startLocationTracking();
    expect(checkPermissions).toHaveBeenCalledTimes(2);
    expect(requestPermissions).toHaveBeenCalledTimes(1);
  });

  it('swallows a failed session mint — no native start', async () => {
    apiClientMock.mockRejectedValue({ status: 503 });
    await tracker.startLocationTracking();
    expect(nativeLocation.start).not.toHaveBeenCalled();
    expect(localStorage.getItem('airos_tracking_session')).toBeNull();
  });

  it('stop stops the service then stops the stored backend session', async () => {
    await tracker.startLocationTracking();
    apiClientMock.mockClear();
    await tracker.stopLocationTracking();
    expect(nativeLocation.stop).toHaveBeenCalledTimes(1);
    expect(apiClientMock).toHaveBeenCalledWith('/location/stop', {
      method: 'POST',
      body: JSON.stringify({ tracking_session_id: sid }),
    });
    expect(localStorage.getItem('airos_tracking_session')).toBeNull();
  });

  it('stop is safe when the backend call fails', async () => {
    await tracker.startLocationTracking();
    apiClientMock.mockRejectedValue({ status: 0 });
    await expect(tracker.stopLocationTracking()).resolves.toBeUndefined();
    expect(nativeLocation.stop).toHaveBeenCalled();
  });
});
