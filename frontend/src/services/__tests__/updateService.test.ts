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
vi.mock('../updateInstaller', () => ({
  NativeUpdate: {
    downloadApk: vi.fn(),
    getPendingApk: vi.fn(),
    installApk: vi.fn(),
    canRequestPackageInstalls: vi.fn(),
    openInstallPermissionSettings: vi.fn(),
    deletePendingApk: vi.fn(),
    addListener: vi.fn().mockResolvedValue({ remove: vi.fn() }),
  },
}));

import { App } from '@capacitor/app';
import { API_ORIGIN } from '../../api/client';
import { getMobileVersion, MobileVersionInfo } from '../../api/mobile';
import { NativeUpdate } from '../updateInstaller';
import {
  beginUpdate,
  checkForUpdates,
  evaluateUpdate,
  getUpdateFlow,
  getUpdateState,
  pendingMatches,
  reconcilePending,
  resetUpdateFlow,
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
  resetUpdateFlow();
  localStorage.clear();
  vi.clearAllMocks();
  vi.mocked(NativeUpdate.getPendingApk).mockResolvedValue({ exists: false });
  vi.mocked(NativeUpdate.canRequestPackageInstalls).mockResolvedValue({ allowed: true });
  vi.mocked(NativeUpdate.downloadApk).mockResolvedValue({
    versionCode: 3, versionName: '1.0.2', sizeBytes: 6_000_000,
  });
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

  it('concurrent checks share a single in-flight request', async () => {
    installed(2);
    vi.mocked(getMobileVersion).mockResolvedValue(release());
    await Promise.all([checkForUpdates(true), checkForUpdates(true), checkForUpdates(true)]);
    expect(getMobileVersion).toHaveBeenCalledTimes(1);
  });

  it('installed newer than latest produces no update', () => {
    expect(evaluateUpdate(4, release()).kind).toBe('none');
  });
});

describe('download/install flow', () => {
  const info = release({ latest_version: '1.0.2', latest_version_code: 3 });

  it('downloads once then hands off to the installer', async () => {
    await beginUpdate(info);
    expect(NativeUpdate.downloadApk).toHaveBeenCalledTimes(1);
    expect(NativeUpdate.downloadApk).toHaveBeenCalledWith({
      url: info.download_url,
      expectedVersionCode: info.latest_version_code,
    });
    expect(NativeUpdate.installApk).toHaveBeenCalledTimes(1);
    expect(getUpdateFlow().phase).toBe('installing');
  });

  it('absolutizes an API-relative proxy download_url for the native downloader', async () => {
    const proxied = release({
      download_url: '/api/v1/mobile/apk?platform=android',
      latest_version_code: 3,
    });
    await beginUpdate(proxied);
    expect(NativeUpdate.downloadApk).toHaveBeenCalledWith({
      url: `${API_ORIGIN}/api/v1/mobile/apk?platform=android`,
      expectedVersionCode: 3,
    });
  });

  it('a second tap while downloading starts no second download', async () => {
    let releaseDl!: () => void;
    vi.mocked(NativeUpdate.downloadApk).mockImplementation(
      () => new Promise((r) => { releaseDl = () => r({ versionCode: 3, versionName: '1.0.2', sizeBytes: 1 }); }),
    );
    const first = beginUpdate(info);
    await vi.waitFor(() => expect(NativeUpdate.downloadApk).toHaveBeenCalledTimes(1));
    const second = beginUpdate(info); // must be a no-op
    releaseDl();
    await Promise.all([first, second]);
    expect(NativeUpdate.downloadApk).toHaveBeenCalledTimes(1);
  });

  it('reuses a pending APK for the same release instead of re-downloading', async () => {
    vi.mocked(NativeUpdate.getPendingApk).mockResolvedValue({
      exists: true, versionCode: 3, versionName: '1.0.2',
    });
    await beginUpdate(info);
    expect(NativeUpdate.downloadApk).not.toHaveBeenCalled();
    expect(NativeUpdate.installApk).toHaveBeenCalledTimes(1);
  });

  it('surfaces an error state when the download rejects', async () => {
    vi.mocked(NativeUpdate.downloadApk).mockRejectedValue(new Error('HTTP_404'));
    await beginUpdate(info);
    expect(getUpdateFlow().phase).toBe('error');
    expect(getUpdateFlow().error).toContain('HTTP_404');
    expect(NativeUpdate.installApk).not.toHaveBeenCalled();
  });

  it('routes to needs_permission when unknown-sources is blocked', async () => {
    vi.mocked(NativeUpdate.canRequestPackageInstalls).mockResolvedValue({ allowed: false });
    await beginUpdate(info);
    expect(getUpdateFlow().phase).toBe('needs_permission');
    expect(NativeUpdate.installApk).not.toHaveBeenCalled();
  });
});

describe('pending APK lifecycle', () => {
  it('deletes the pending APK once the installed build reaches it', async () => {
    installed(3);
    vi.mocked(NativeUpdate.getPendingApk).mockResolvedValue({
      exists: true, versionCode: 3, versionName: '1.0.2',
    });
    await reconcilePending();
    expect(NativeUpdate.deletePendingApk).toHaveBeenCalledTimes(1);
  });

  it('keeps a pending APK that is still newer than the install', async () => {
    installed(2);
    vi.mocked(NativeUpdate.getPendingApk).mockResolvedValue({
      exists: true, versionCode: 3, versionName: '1.0.2',
    });
    await reconcilePending();
    expect(NativeUpdate.deletePendingApk).not.toHaveBeenCalled();
  });

  it('pendingMatches only reuses an exact versionCode match', async () => {
    vi.mocked(NativeUpdate.getPendingApk).mockResolvedValue({
      exists: true, versionCode: 3, versionName: '1.0.2',
    });
    expect(await pendingMatches(3)).toBe(true);
    expect(await pendingMatches(4)).toBe(false);
  });
});
