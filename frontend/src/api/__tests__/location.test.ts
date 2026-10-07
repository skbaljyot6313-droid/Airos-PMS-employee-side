import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock the HTTP boundary — the api module under test calls apiClient,
// and the tracker reaches it through src/api/location.ts.
const apiClientMock = vi.fn();
vi.mock('../client', () => ({ apiClient: (...args: unknown[]) => apiClientMock(...args) }));

// Mock the Capacitor seams — vitest runs on Node, never a native bridge.
const isNative = vi.fn();
vi.mock('@capacitor/core', () => ({
  Capacitor: { isNativePlatform: () => isNative() },
}));
const checkPermissions = vi.fn();
const requestPermissions = vi.fn();
const getCurrentPosition = vi.fn();
vi.mock('@capacitor/geolocation', () => ({
  Geolocation: { checkPermissions, requestPermissions, getCurrentPosition },
}));

import { getCurrentLocation, postCurrentLocation } from '../location';

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
// locationTracker — foreground loop lifecycle
// ---------------------------------------------------------------------------

describe('locationTracker', () => {
  let tracker: typeof import('../../services/locationTracker');

  beforeEach(async () => {
    vi.resetModules(); // fresh module state per test (running/permissionAsked)
    tracker = await import('../../services/locationTracker');
  });

  afterEach(() => tracker.stopLocationTracking());

  it('is a full no-op on web (non-native platform)', async () => {
    isNative.mockReturnValue(false);
    await tracker.startLocationTracking();
    expect(checkPermissions).not.toHaveBeenCalled();
    expect(apiClientMock).not.toHaveBeenCalled();
  });

  it('posts a fix on the first tick when permission is granted', async () => {
    isNative.mockReturnValue(true);
    checkPermissions.mockResolvedValue({ location: 'granted', coarseLocation: 'granted' });
    getCurrentPosition.mockResolvedValue({
      timestamp: 1_760_000_000_000,
      coords: {
        latitude: 12.9716,
        longitude: 77.5946,
        accuracy: 8,
        altitude: null,
        altitudeAccuracy: null,
        speed: null, // null speed/heading must be omitted
        heading: 90,
      },
    });
    apiClientMock.mockResolvedValue({ recorded: true, server_timestamp: 1, expires_in: 60 });

    await tracker.startLocationTracking();
    await vi.waitFor(() => expect(apiClientMock).toHaveBeenCalledTimes(1));

    const [endpoint, init] = apiClientMock.mock.calls[0];
    expect(endpoint).toBe('/location/current');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({
      latitude: 12.9716,
      longitude: 77.5946,
      accuracy: 8,
      heading: 90,
      timestamp: 1_760_000_000,
    });
  });

  it('requests permission once and never re-prompts after denial', async () => {
    isNative.mockReturnValue(true);
    const denied = { location: 'denied', coarseLocation: 'denied' };
    checkPermissions.mockResolvedValue(denied);
    requestPermissions.mockResolvedValue(denied);

    await tracker.startLocationTracking();
    expect(requestPermissions).toHaveBeenCalledTimes(1);
    expect(getCurrentPosition).not.toHaveBeenCalled();
    expect(apiClientMock).not.toHaveBeenCalled();

    // A later start re-checks silently — no nagging re-prompt.
    await tracker.startLocationTracking();
    expect(checkPermissions).toHaveBeenCalledTimes(2);
    expect(requestPermissions).toHaveBeenCalledTimes(1);
    expect(apiClientMock).not.toHaveBeenCalled();
  });

  it('skips the cycle silently when GPS is unavailable', async () => {
    isNative.mockReturnValue(true);
    checkPermissions.mockResolvedValue({ location: 'granted', coarseLocation: 'granted' });
    getCurrentPosition.mockRejectedValue(new Error('location unavailable'));

    await expect(tracker.startLocationTracking()).resolves.toBeUndefined();
    await new Promise((r) => setTimeout(r, 0)); // let the first tick settle
    expect(getCurrentPosition).toHaveBeenCalledTimes(1);
    expect(apiClientMock).not.toHaveBeenCalled();
  });

  it('skips the cycle silently when the API call fails', async () => {
    isNative.mockReturnValue(true);
    checkPermissions.mockResolvedValue({ location: 'granted', coarseLocation: 'granted' });
    getCurrentPosition.mockResolvedValue({
      timestamp: Date.now(),
      coords: {
        latitude: 1,
        longitude: 2,
        accuracy: 5,
        altitude: null,
        altitudeAccuracy: null,
        speed: null,
        heading: null,
      },
    });
    apiClientMock.mockRejectedValue({ status: 503, code: 'LIVE_LOCATION_UNAVAILABLE' });

    await tracker.startLocationTracking();
    await vi.waitFor(() => expect(getCurrentPosition).toHaveBeenCalledTimes(1));
    expect(apiClientMock).toHaveBeenCalledTimes(1); // swallowed — no throw
  });
});
