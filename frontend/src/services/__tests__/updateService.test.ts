import { describe, it, expect, beforeEach, vi } from 'vitest';

// Minimal localStorage stub — vitest runs in node, not jsdom.
const store = new Map<string, string>();
vi.stubGlobal('localStorage', {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => void store.set(k, v),
  removeItem: (k: string) => void store.delete(k),
  clear: () => store.clear(),
});

vi.mock('@capacitor/core', () => ({
  Capacitor: { isNativePlatform: () => true },
}));
vi.mock('@capacitor/app', () => ({
  App: { getInfo: vi.fn() },
}));
vi.mock('../../api/mobile', () => ({
  getMobileVersion: vi.fn(),
}));

import { App } from '@capacitor/app';
import { getMobileVersion, MobileVersionInfo } from '../../api/mobile';
import {
  checkForUpdates,
  evaluateUpdate,
  getUpdateState,
  resetUpdateState,
  shouldCheckNow,
} from '../updateService';

const release = (over: Partial<MobileVersionInfo> = {}): MobileVersionInfo => ({
  platform: 'android',
  latest_version: '1.0.1',
  latest_version_code: 2,
  minimum_version: '1.0.0',
  minimum_version_code: 1,
  download_url: 'https://expo.dev/artifacts/eas/x.apk',
  release_notes: null,
  force_update: false,
  ...over,
});

const installed = (code: number) => {
  vi.mocked(App.getInfo).mockResolvedValue({
    build: String(code),
  } as Awaited<ReturnType<typeof App.getInfo>>);
};

beforeEach(() => {
  resetUpdateState();
  localStorage.clear();
  vi.clearAllMocks();
});

describe('evaluateUpdate — versionCode is the authority', () => {
  it('no update when installed code equals latest', () => {
    expect(evaluateUpdate(2, release()).kind).toBe('none');
  });

  it('optional update when installed code is behind latest', () => {
    const s = evaluateUpdate(1, release());
    expect(s.kind).toBe('optional');
    expect(s.info?.latest_version).toBe('1.0.1');
  });

  it('required when installed code is below minimum', () => {
    const s = evaluateUpdate(
      1,
      release({ minimum_version_code: 2 }),
    );
    expect(s.kind).toBe('required');
  });

  it('required when backend flags force_update', () => {
    expect(evaluateUpdate(5, release({ force_update: true })).kind).toBe(
      'required',
    );
  });

  it('integer compare — code 10 beats code 9 (1.0.10 > 1.0.9)', () => {
    const s = evaluateUpdate(
      9,
      release({ latest_version: '1.0.10', latest_version_code: 10 }),
    );
    expect(s.kind).toBe('optional');
    expect(
      evaluateUpdate(
        10,
        release({ latest_version: '1.0.10', latest_version_code: 10 }),
      ).kind,
    ).toBe('none');
  });
});

describe('checkForUpdates', () => {
  it('emits optional update for an older install', async () => {
    installed(1);
    vi.mocked(getMobileVersion).mockResolvedValue(release());
    const s = await checkForUpdates(true);
    expect(s.kind).toBe('optional');
    expect(getUpdateState().info?.download_url).toContain('.apk');
  });

  it('survives endpoint failure without changing state', async () => {
    installed(1);
    vi.mocked(getMobileVersion).mockRejectedValue(new Error('offline'));
    const s = await checkForUpdates(true);
    expect(s.kind).toBe('none');
  });

  it('skips the network call inside the 24h throttle window', async () => {
    installed(1);
    vi.mocked(getMobileVersion).mockResolvedValue(release());
    await checkForUpdates(true);
    expect(getMobileVersion).toHaveBeenCalledTimes(1);
    await checkForUpdates(); // throttled
    expect(getMobileVersion).toHaveBeenCalledTimes(1);
    await checkForUpdates(true); // forced bypasses throttle
    expect(getMobileVersion).toHaveBeenCalledTimes(2);
  });

  it('re-checks a required gate even inside the throttle window', async () => {
    installed(1);
    vi.mocked(getMobileVersion).mockResolvedValue(
      release({ minimum_version_code: 2 }),
    );
    await checkForUpdates(true);
    expect(getUpdateState().kind).toBe('required');
    expect(shouldCheckNow(false)).toBe(true);
  });
});
