import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { apiClient, secureStorage, isCancelledError } from '../client';
import { swr, cacheInvalidate, cacheInvalidateAll, setCacheScope } from '../../services/dataCache';

const store = new Map<string, string>();

const localStorageShim = {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => void store.set(k, String(v)),
  removeItem: (k: string) => void store.delete(k),
};

const jsonRes = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

beforeEach(() => {
  store.clear();
  cacheInvalidateAll();
  vi.stubGlobal('localStorage', localStorageShim);
  secureStorage.setTokens('access', 'refresh');
  vi.stubGlobal('window', {
    dispatchEvent: () => true,
    addEventListener: () => {},
    removeEventListener: () => {},
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('single-flight GET dedupe', () => {
  it('concurrent identical GETs share one fetch', async () => {
    const fetchMock = vi.fn(async () => jsonRes(200, { items: [] }));
    vi.stubGlobal('fetch', fetchMock);
    const [a, b, c] = await Promise.all([
      apiClient('/tasks'), apiClient('/tasks'), apiClient('/tasks'),
    ]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(a).toEqual(b);
    expect(b).toEqual(c);
  });

  it('different endpoints or sequential calls are not deduped', async () => {
    const fetchMock = vi.fn(async () => jsonRes(200, { ok: 1 }));
    vi.stubGlobal('fetch', fetchMock);
    await apiClient('/tasks');
    await apiClient('/tasks'); // resolved already → own request
    await apiClient('/zones');
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});

describe('GET retry policy', () => {
  it('retries a 5xx GET with backoff and succeeds', async () => {
    let n = 0;
    vi.stubGlobal('fetch', vi.fn(async () => {
      n += 1;
      return n < 3 ? jsonRes(503, { detail: { message: 'unavailable' } })
                   : jsonRes(200, { ok: true });
    }));
    const res = await apiClient<{ ok: boolean }>('/tasks');
    expect(res.ok).toBe(true);
    expect(n).toBe(3); // 1 initial + 2 retries max
  }, 15000);

  it('never retries a mutation — even on 503', async () => {
    const fetchMock = vi.fn(async () =>
      jsonRes(503, { detail: { message: 'down' } }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(
      apiClient('/tasks/1/start', { method: 'POST', body: '{}' }),
    ).rejects.toMatchObject({ status: 503 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('never retries a 4xx', async () => {
    const fetchMock = vi.fn(async () =>
      jsonRes(422, { detail: 'bad' }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(apiClient('/tasks')).rejects.toMatchObject({ status: 422 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('external abort throws CANCELLED and stops retries', async () => {
    const controller = new AbortController();
    vi.stubGlobal('fetch', vi.fn(async () => {
      controller.abort();
      throw Object.assign(new Error('aborted'), { name: 'AbortError' });
    }));
    await expect(
      apiClient('/tasks', { signal: controller.signal }),
    ).rejects.toMatchObject({ status: 0, code: 'CANCELLED' });
  });

  it('isCancelledError narrows the cancelled error', () => {
    expect(isCancelledError({ status: 0, code: 'CANCELLED' })).toBe(true);
    expect(isCancelledError({ status: 0, code: 'TIMEOUT' })).toBe(false);
    expect(isCancelledError(null)).toBe(false);
  });
});

describe('swr cache', () => {
  it('miss fetches and stores; fresh hit skips the network', async () => {
    let calls = 0;
    const fetcher = async () => (++calls, ['a']);
    const first = await swr('k1', fetcher, { ttlMs: 60_000 });
    const second = await swr('k1', fetcher, { ttlMs: 60_000 });
    expect(first).toEqual(['a']);
    expect(second).toEqual(['a']);
    expect(calls).toBe(1);
  });

  it('stale hit returns cache immediately and revalidates via onUpdate', async () => {
    let calls = 0;
    let payload = 'old';
    await swr('k2', async () => payload, { ttlMs: 1 });
    await new Promise((r) => setTimeout(r, 5)); // age past ttl
    payload = 'new';
    const updates: string[] = [];
    const got = await swr('k2', async () => (++calls, payload), {
      ttlMs: 1,
      onUpdate: (d: string) => updates.push(d),
    });
    expect(got).toBe('old'); // stale served
    await new Promise((r) => setTimeout(r, 20));
    expect(updates).toEqual(['new']);
    expect(calls).toBe(1);
    // now fresh — serves the revalidated value without another fetch
    const third = await swr('k2', async () => 'never', { ttlMs: 60_000 });
    expect(third).toBe('new');
  });

  it('invalidate drops the entry; invalidateAll + scope switch purge', async () => {
    await swr('tasks:list', async () => [1], { ttlMs: 60_000 });
    cacheInvalidate('tasks:');
    let calls = 0;
    await swr('tasks:list', async () => (++calls, [2]), { ttlMs: 60_000 });
    expect(calls).toBe(1);

    setCacheScope('user-A');
    await swr('x', async () => 'A-data', { ttlMs: 60_000 });
    setCacheScope('user-B'); // switch purges
    let bCalls = 0;
    const got = await swr('x', async () => (++bCalls, 'B-data'), { ttlMs: 60_000 });
    expect(got).toBe('B-data');
    expect(bCalls).toBe(1);
    setCacheScope(null);
  });
});
