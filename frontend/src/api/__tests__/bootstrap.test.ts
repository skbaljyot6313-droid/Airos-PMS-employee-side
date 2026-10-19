import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock the storage + api seams — vitest node env has no Preferences DOM
// impl and no network.
const mem = new Map<string, string>();

vi.mock('@capacitor/preferences', () => ({
  Preferences: {
    get: vi.fn(async ({ key }: { key: string }) => ({
      value: mem.get(key) ?? null,
    })),
    set: vi.fn(async ({ key, value }: { key: string; value: string }) => {
      mem.set(key, value);
    }),
    remove: vi.fn(async ({ key }: { key: string }) => {
      mem.delete(key);
    }),
    keys: vi.fn(async () => ({ keys: [...mem.keys()] })),
  },
}));

const apiClientMock = vi.fn();
vi.mock('../client', () => ({
  apiClient: (endpoint: string) => apiClientMock(endpoint),
  API_BASE: 'http://t/api/v1',
  mediaUrl: (p: string) => p,
}));

const listZonesMock = vi.fn();
vi.mock('../directory', () => ({
  listZonesApi: () => listZonesMock(),
}));

const myShiftMock = vi.fn();
vi.mock('../shift', () => ({
  getMyShiftApi: () => myShiftMock(),
}));

const unreadMock = vi.fn();
vi.mock('../notifications', () => ({
  unreadCountApi: () => unreadMock(),
}));

import { readStaticZones } from '../bootstrap';

const BOOT = {
  ref_version: 'v-abc',
  user: { user_uid: 'u1' },
  company: { company_uid: 'c1', company_name: 'Co' },
  zones: { items: [{ zone_uid: 'z1', name: 'Z1' }] },
  shift: { shift_uid: 's1' },
  unread_count: { unread: 3 },
  errors: {},
};

const load = async () => {
  vi.resetModules();
  vi.stubEnv('VITE_BOOTSTRAP', '1');
  return import('../bootstrap');
};

beforeEach(() => {
  mem.clear();
  apiClientMock.mockReset();
  listZonesMock.mockReset();
  myShiftMock.mockReset();
  unreadMock.mockReset();
  vi.unstubAllEnvs();
});

describe('bootstrap client path', () => {
  it('flag OFF (default) — warmStaticCache is a complete no-op', async () => {
    vi.stubEnv('VITE_BOOTSTRAP', '0');
    vi.resetModules();
    const mod = await import('../bootstrap');
    expect(mod.BOOTSTRAP_ENABLED).toBe(false);
    await mod.warmStaticCache('u1', null);
    expect(apiClientMock).not.toHaveBeenCalled();
    expect(mem.size).toBe(0);
  });

  it('flag ON — all sections healthy: writes static cache, no legacy calls', async () => {
    apiClientMock.mockResolvedValue(BOOT);
    const mod = await load();
    await mod.warmStaticCache('u1', null);
    expect(await readStaticZones('u1')).toEqual([
      { zone_uid: 'z1', name: 'Z1' },
    ]);
    expect(listZonesMock).not.toHaveBeenCalled();
    expect(myShiftMock).not.toHaveBeenCalled();
    expect(unreadMock).not.toHaveBeenCalled();
  });

  it('per-section failure → legacy fallback for ONLY that section', async () => {
    apiClientMock.mockResolvedValue({
      ...BOOT,
      zones: null,
      shift: null,
      errors: { zones: 'ZONE_QUERY_FAILED', shift: 'SHIFT_FAILED' },
    });
    listZonesMock.mockResolvedValue({
      items: [{ zone_uid: 'z-legacy' }],
    });
    myShiftMock.mockResolvedValue({ shift_uid: 's-legacy' });
    const mod = await load();
    await mod.warmStaticCache('u1', null);
    expect(listZonesMock).toHaveBeenCalledTimes(1);
    expect(myShiftMock).toHaveBeenCalledTimes(1);
    expect(await readStaticZones('u1')).toEqual([
      { zone_uid: 'z-legacy' },
    ]);
  });

  it('endpoint 404/error → full legacy fallback still fills zones', async () => {
    apiClientMock.mockRejectedValue({ status: 404 });
    listZonesMock.mockResolvedValue({ items: [{ zone_uid: 'z-off' }] });
    const mod = await load();
    await mod.warmStaticCache('u1', null);
    expect(await readStaticZones('u1')).toEqual([{ zone_uid: 'z-off' }]);
  });
});
