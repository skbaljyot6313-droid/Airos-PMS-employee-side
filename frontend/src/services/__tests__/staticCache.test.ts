import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock @capacitor/preferences with an in-memory store — the web impl of
// the plugin needs a DOM, so the module boundary is the testable seam.
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

import {
  staticGet,
  staticSet,
  staticRemove,
  purgeStaticCaches,
  purgeStaticUser,
  STATIC_SCHEMA_VERSION,
} from '../staticCache';

beforeEach(() => mem.clear());

describe('staticCache', () => {
  it('stores and reads whitelisted entries, namespaced by user', async () => {
    await staticSet('u1', 'zones', [{ zone_uid: 'z1' }]);
    await staticSet('u2', 'zones', [{ zone_uid: 'z2' }]);
    expect(await staticGet('u1', 'zones')).toEqual([{ zone_uid: 'z1' }]);
    expect(await staticGet('u2', 'zones')).toEqual([{ zone_uid: 'z2' }]);
    expect(await staticGet('u1', 'shift')).toBeUndefined();
  });

  it('rejects non-whitelisted keys — no tokens/GPS ever lands here', async () => {
    await expect(
      staticSet('u1', 'access_token' as never, 'secret'),
    ).rejects.toThrow(/whitelist/);
    await expect(
      staticSet('u1', 'gps_fixes' as never, []),
    ).rejects.toThrow(/whitelist/);
    expect(mem.size).toBe(0);
  });

  it('keys are versioned — a schema bump orphans old data', async () => {
    await staticSet('u1', 'zones', ['x']);
    const [stored] = [...mem.keys()];
    expect(stored).toBe(`airos:static:v${STATIC_SCHEMA_VERSION}:u1:zones`);
  });

  it('purgeStaticCaches removes every namespaced entry', async () => {
    await staticSet('u1', 'zones', [1]);
    await staticSet('u2', 'company', { name: 'C' });
    mem.set('unrelated:key', 'keep');
    await purgeStaticCaches();
    expect(await staticGet('u1', 'zones')).toBeUndefined();
    expect(mem.get('unrelated:key')).toBe('keep');
  });

  it('purgeStaticUser removes only that user — account switch safety', async () => {
    await staticSet('u1', 'zones', [1]);
    await staticSet('u2', 'zones', [2]);
    await purgeStaticUser('u1');
    expect(await staticGet('u1', 'zones')).toBeUndefined();
    expect(await staticGet('u2', 'zones')).toEqual([2]);
  });

  it('staticRemove drops one entry; corrupt JSON reads as undefined', async () => {
    await staticSet('u1', 'zones', [1]);
    await staticRemove('u1', 'zones');
    expect(await staticGet('u1', 'zones')).toBeUndefined();
    mem.set(`airos:static:v${STATIC_SCHEMA_VERSION}:u1:company`, '{bad');
    expect(await staticGet('u1', 'company')).toBeUndefined();
  });
});
