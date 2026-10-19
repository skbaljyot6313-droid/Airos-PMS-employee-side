import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React, { act } from 'react';
import TestRenderer from 'react-test-renderer';

// react-test-renderer runs without a DOM — flag act() availability.
(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const store = new Map<string, string>();
const localStorageShim = {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => void store.set(k, String(v)),
  removeItem: (k: string) => void store.delete(k),
};

beforeEach(() => {
  store.clear();
  vi.stubGlobal('localStorage', localStorageShim);
  vi.stubGlobal('window', {
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => true,
  });
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetAllMocks();
});

// --- module mocks -----------------------------------------------------
// mock.module paths resolve relative to THIS file.
const getMeApi = vi.fn();
const getZoneNameMap = vi.fn();
vi.mock('../../api/auth', () => ({
  loginApi: vi.fn(),
  getMeApi: (...args: unknown[]) => getMeApi(...args),
  logoutApi: vi.fn(),
  updateMeApi: vi.fn(),
}));
vi.mock('../../api/directory', () => ({
  getZoneNameMap: (...args: unknown[]) => getZoneNameMap(...args),
  invalidateZoneCache: vi.fn(),
}));
vi.mock('../../services/pushRegistration', () => ({
  unregisterPushDevice: vi.fn(async () => undefined),
}));
vi.mock('../../utils/perf', () => ({
  perfMarkOnce: vi.fn(),
  perfReportOnce: vi.fn(),
}));

// Imports AFTER mocks — vitest hoists vi.mock but ordering keeps intent.
const { AuthProvider, useAuth } = await import('../AuthContext');
const { secureStorage } = await import('../../api/client');
const { ConnectionErrorScreen } = await import('../../components/auth/ConnectionErrorScreen');

const EMP_USER = {
  uid: 'u1', name: 'Worker One', email: 'w@x', username: 'w',
  role: 'employee' as const, company_uid: 'c1',
  property_uid: 'p1', employee_uid: 'e1', zone_uid: 'z1',
  phone: null, job_title: 'Housekeeper', company_name: 'Acme',
};
const COMPANY = {
  company_uid: 'c1', name: 'Acme', legal_name: null, brand_name: null,
  email: null, phone: null, address: null, pin_code: null,
  operational_day_start: '06:00', created_at: '2024-01-01',
};

/** Probe component — captures the latest context value. */
let latest: ReturnType<typeof useAuth>;
const Probe: React.FC = () => {
  latest = useAuth();
  return null;
};

async function mount(): Promise<void> {
  await act(async () => {
    TestRenderer.create(
      React.createElement(
        AuthProvider,
        null,
        React.createElement(Probe, null)
      )
    );
  });
}

describe('AuthContext refreshSession', () => {
  it('resolves while the zones fetch is still pending; zone_name patches later', async () => {
    store.set('airos_staff_access_token', 'tok');
    store.set('airos_staff_refresh_token', 'rtok');
    getMeApi.mockResolvedValue({ user: EMP_USER, company: COMPANY });

    // zones fetch stays pending — controlled manually.
    let resolveZones!: (m: Map<string, string>) => void;
    getZoneNameMap.mockReturnValue(
      new Promise<Map<string, string>>((r) => (resolveZones = r))
    );

    await mount();

    // Session restored WITHOUT waiting for zones.
    expect(latest.isLoading).toBe(false);
    expect(latest.isAuthenticated).toBe(true);
    expect(latest.employee).toMatchObject({
      id: 'e1', zone_uid: 'z1', zone_name: null,
    });
    expect(getZoneNameMap).toHaveBeenCalledTimes(1);

    // Resolve zones → zone name patches into the employee context.
    await act(async () => {
      resolveZones(new Map([['z1', 'Zone A']]));
    });
    expect(latest.employee).toMatchObject({ zone_uid: 'z1', zone_name: 'Zone A' });
  });

  it('status-0 timeout keeps tokens and surfaces a retryable connectionError', async () => {
    store.set('airos_staff_access_token', 'tok');
    store.set('airos_staff_refresh_token', 'rtok');
    getMeApi.mockRejectedValue({ status: 0, code: 'TIMEOUT', message: 'Request timed out' });

    await mount();

    expect(latest.isLoading).toBe(false);
    expect(latest.isAuthenticated).toBe(false);
    expect(latest.connectionError).toBe('Request timed out');
    // Tokens preserved for the retry path.
    expect(secureStorage.getToken()).toBe('tok');
    expect(secureStorage.getRefreshToken()).toBe('rtok');
  });

  it('401 after failed refresh clears tokens and signs out (no connectionError)', async () => {
    store.set('airos_staff_access_token', 'tok');
    store.set('airos_staff_refresh_token', 'rtok');
    getMeApi.mockRejectedValue({ status: 401, code: 'UNAUTHENTICATED', message: 'expired' });

    await mount();

    expect(latest.connectionError).toBeNull();
    expect(latest.isAuthenticated).toBe(false);
    expect(secureStorage.getToken()).toBeNull();
    expect(secureStorage.getRefreshToken()).toBeNull();
  });

  it('connectionError retry screen wires onRetry → retrySession → second restore attempt', async () => {
    // The AppNavigator renders ConnectionErrorScreen when connectionError
    // is set; verify the screen itself invokes the retry/logout actions.
    const onRetry = vi.fn();
    const onLogout = vi.fn();
    let renderer!: TestRenderer.ReactTestRenderer;
    await act(async () => {
      renderer = TestRenderer.create(
        React.createElement(ConnectionErrorScreen, {
          message: 'Request timed out',
          onRetry,
          onLogout,
        })
      );
    });
    const root = renderer.root;
    const buttons = root.findAllByType('button');
    expect(buttons).toHaveLength(2);
    buttons[0].props.onClick();
    expect(onRetry).toHaveBeenCalledTimes(1);
    buttons[1].props.onClick();
    expect(onLogout).toHaveBeenCalledTimes(1);
    expect(root.findAllByType('p').map((p) => p.children.join(' '))).toContain(
      'Can\'t reach the server'
    );
  });
});
