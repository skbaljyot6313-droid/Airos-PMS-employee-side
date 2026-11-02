import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { apiClient } from '../client';

const busy = () => new Response(JSON.stringify({
  error: { code: 'DATABASE_BUSY', message: 'The service is temporarily busy. Please try again shortly.' },
}), { status: 503 });

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal('localStorage', { getItem: () => null });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('bounded database capacity retries', () => {
  it('recovers an eligible GET with jitter after a temporary rejection', async () => {
    vi.spyOn(Math, 'random').mockReturnValue(0.5);
    const fetch = vi.fn().mockResolvedValueOnce(busy())
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [] }), { status: 200 }));
    vi.stubGlobal('fetch', fetch);
    const result = apiClient('/tasks');
    await vi.advanceTimersByTimeAsync(1124);
    expect(fetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    await expect(result).resolves.toEqual({ items: [] });
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it('stops after two retries and keeps the meaningful error', async () => {
    const fetch = vi.fn().mockImplementation(async () => busy());
    vi.stubGlobal('fetch', fetch);
    const result = expect(apiClient('/tasks')).rejects.toMatchObject({ status: 503, code: 'DATABASE_BUSY' });
    await vi.runAllTimersAsync();
    await result;
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it.each([
    ['/tasks/1/start', 'POST', 503, 'DATABASE_BUSY'],
    ['/auth/me', 'GET', 503, 'DATABASE_BUSY'],
    ['/tasks', 'GET', 503, 'DATABASE_ERROR'],
    ['/tasks', 'GET', 403, 'FORBIDDEN'],
    ['/auth/login', 'POST', 401, 'UNAUTHENTICATED'],
  ])('does not retry %s %s status %s code %s', async (path, method, status, code) => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({ error: { code, message: 'failure' } }), { status }));
    vi.stubGlobal('fetch', fetch);
    await expect(apiClient(path, { method, auth: false })).rejects.toMatchObject({ status, code });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('does not replay a write after a network failure', async () => {
    const fetch = vi.fn().mockRejectedValue(new TypeError('network'));
    vi.stubGlobal('fetch', fetch);
    await expect(apiClient('/attendance/start', { method: 'POST' }))
      .rejects.toMatchObject({ code: 'NETWORK_ERROR' });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
