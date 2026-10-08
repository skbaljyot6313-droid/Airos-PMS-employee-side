import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { apiClient, secureStorage } from '../client';
import { ApiError } from '../../types';

const store = new Map<string, string>();
const dispatched: string[] = [];

const localStorageShim = {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => void store.set(k, String(v)),
  removeItem: (k: string) => void store.delete(k),
};

beforeEach(() => {
  store.clear();
  dispatched.length = 0;
  vi.stubGlobal('localStorage', localStorageShim);
  vi.stubGlobal('window', {
    dispatchEvent: (e: { type: string }) => (dispatched.push(e.type), true),
    addEventListener: () => {},
    removeEventListener: () => {},
  });
  if (typeof globalThis.CustomEvent === 'undefined') {
    vi.stubGlobal(
      'CustomEvent',
      class CustomEvent extends Event {
        constructor(type: string, init?: EventInit) {
          super(type, init);
        }
      }
    );
  }
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const jsonRes = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

describe('apiClient refresh flow', () => {
  it('401 triggers a single shared refresh for concurrent calls, then retries', async () => {
    secureStorage.setTokens('old-access', 'refresh-tok');
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/auth/refresh')) {
        return jsonRes(200, { access_token: 'new-access', token_type: 'bearer' });
      }
      const auth = new Headers(init?.headers).get('Authorization');
      return auth === 'Bearer new-access'
        ? jsonRes(200, { ok: true })
        : jsonRes(401, { detail: { message: 'expired', code: 'UNAUTHENTICATED' } });
    });
    vi.stubGlobal('fetch', fetchMock);

    const [a, b] = await Promise.all([
      apiClient<{ ok: boolean }>('/tasks'),
      apiClient<{ ok: boolean }>('/zones'),
    ]);
    expect(a.ok).toBe(true);
    expect(b.ok).toBe(true);

    const refreshCalls = fetchMock.mock.calls.filter(([i]) => String(i).endsWith('/auth/refresh'));
    expect(refreshCalls).toHaveLength(1);
    expect(secureStorage.getToken()).toBe('new-access');
    expect(dispatched).not.toContain('airos_unauthorized');
  });

  it('refresh failure clears tokens and dispatches airos_unauthorized', async () => {
    secureStorage.setTokens('old-access', 'refresh-tok');
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/auth/refresh')) {
        return jsonRes(401, { detail: { message: 'bad refresh', code: 'INVALID_REFRESH_TOKEN' } });
      }
      return jsonRes(401, { detail: { message: 'expired', code: 'UNAUTHENTICATED' } });
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(apiClient('/tasks')).rejects.toMatchObject({ status: 401 } satisfies Partial<ApiError>);
    expect(secureStorage.getToken()).toBeNull();
    expect(secureStorage.getRefreshToken()).toBeNull();
    expect(dispatched).toContain('airos_unauthorized');
  });

  it('returns undefined for 204 responses', async () => {
    secureStorage.setTokens('access', 'refresh-tok');
    vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 204 })));
    await expect(apiClient('/auth/logout', { method: 'POST' })).resolves.toBeUndefined();
  });
});
