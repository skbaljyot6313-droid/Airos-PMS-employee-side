import { describe, it, expect, beforeEach, vi } from 'vitest';

// --- Mocks -----------------------------------------------------------------

const { connectMock, disconnectMock, subscribeMock, unsubscribeMock, pubHandlers } =
  vi.hoisted(() => ({
    connectMock: vi.fn(),
    disconnectMock: vi.fn(),
    subscribeMock: vi.fn(),
    unsubscribeMock: vi.fn(),
    pubHandlers: [] as ((ctx: { data?: unknown }) => void)[],
  }));

class FakeSubscription {
  handlers = new Map<string, (ctx: { data?: unknown }) => void>();
  constructor(public channel: string, public opts: unknown) {}
  on(ev: string, cb: (ctx: { data?: unknown }) => void) {
    this.handlers.set(ev, cb);
    pubHandlers.push(cb);
  }
  subscribe() {
    subscribeMock(this.channel);
  }
  unsubscribe() {
    unsubscribeMock(this.channel);
  }
  emitPub(data: unknown) {
    this.handlers.get('publication')?.({ data });
  }
  emitEvent(ev: string, ctx: unknown) {
    this.handlers.get(ev)?.(ctx as { data?: unknown });
  }
}

const lastSub = { current: null as FakeSubscription | null };

vi.mock('centrifuge', () => ({
  Centrifuge: class {
    constructor(public url: string, public opts: unknown) {}
    connect = connectMock;
    disconnect = disconnectMock;
    newSubscription = (channel: string, opts: unknown) => {
      const s = new FakeSubscription(channel, opts);
      lastSub.current = s;
      return s;
    };
  },
}));

const apiMock = vi.fn();
vi.mock('../../api/client', () => ({
  apiClient: (...args: unknown[]) => apiMock(...args),
}));

const pollMock = vi.fn();
vi.mock('../notificationService', () => ({
  pollNotificationsNow: () => pollMock(),
}));

import { swr, cachePeek, cacheInvalidateAll, setCacheScope } from '../dataCache';

import {
  startRealtime,
  stopRealtime,
  subscribeRealtime,
  subscribeRealtimeEvents,
  realtimeResume,
} from '../realtime';

const EMP = '11111111-2222-3333-4444-555555555555';
const CHANNEL = `priv:emp:${EMP}`;

beforeEach(() => {
  vi.useRealTimers();
  cacheInvalidateAll();
  setCacheScope(null);
  apiMock.mockReset();
  pollMock.mockReset();
  connectMock.mockReset();
  disconnectMock.mockReset();
  subscribeMock.mockReset();
  unsubscribeMock.mockReset();
  pubHandlers.length = 0;
  lastSub.current = null;
  stopRealtime();
});

const okToken = () => ({
  token: 'conn-jwt',
  expires_at: Math.floor(Date.now() / 1000) + 300,
  ws_url: 'wss://rt.test/connection/websocket',
});

const flush = () => new Promise((r) => setTimeout(r, 0));

// --- Tests -----------------------------------------------------------------

describe('startRealtime', () => {
  it('connects and subscribes to the own-employee channel', async () => {
    apiMock.mockImplementation((path: string) =>
      path === '/realtime/token'
        ? Promise.resolve(okToken())
        : Promise.resolve({ tokens: { [CHANNEL]: 'sub-jwt' }, expires_at: 0 }),
    );
    startRealtime(EMP);
    await flush();
    await flush();
    expect(connectMock).toHaveBeenCalled();
    expect(subscribeMock).toHaveBeenCalledWith(CHANNEL);
  });

  it('refreshes connection and subscription tokens via the backend', async () => {
    apiMock.mockImplementation((path: string) =>
      path === '/realtime/token'
        ? Promise.resolve(okToken())
        : Promise.resolve({ tokens: { [CHANNEL]: 'sub-jwt' } }),
    );
    startRealtime(EMP);
    await flush();
    await flush();
    const sub = lastSub.current!;
    const opts = sub.opts as { token: string; getToken: () => Promise<string> };
    expect(opts.token).toBe('sub-jwt');
    apiMock.mockResolvedValueOnce({ tokens: { [CHANNEL]: 'sub-jwt-2' } });
    await expect(opts.getToken()).resolves.toBe('sub-jwt-2');
  });

  it('forwards publications to listeners and polls the feed', async () => {
    apiMock.mockImplementation((path: string) =>
      path === '/realtime/token'
        ? Promise.resolve(okToken())
        : Promise.resolve({ tokens: { [CHANNEL]: 's' } }),
    );
    const seen: unknown[] = [];
    const un = subscribeRealtime((e) => seen.push(e));
    startRealtime(EMP);
    await flush();
    await flush();
    lastSub.current!.emitPub({ type: 'task.updated', data: { task_uid: 'x' } });
    expect(seen).toEqual([{ type: 'task.updated', data: { task_uid: 'x' } }]);
    expect(pollMock).toHaveBeenCalled();
    un();
  });

  it('marks realtime unavailable on 503 and no-ops until cooldown', async () => {
    apiMock.mockRejectedValue({ status: 503 });
    const stop1 = startRealtime(EMP);
    await flush();
    await flush();
    expect(connectMock).not.toHaveBeenCalled();
    // Within cooldown → no-op without another API call
    const calls = apiMock.mock.calls.length;
    startRealtime(EMP);
    await flush();
    expect(apiMock.mock.calls.length).toBe(calls);
    stop1();
  });

  it('non-503 errors do not mark realtime unavailable', async () => {
    apiMock.mockRejectedValueOnce({ status: 500 });
    startRealtime(EMP);
    await flush();
    await flush();
    apiMock.mockImplementation((path: string) =>
      path === '/realtime/token'
        ? Promise.resolve(okToken())
        : Promise.resolve({ tokens: { [CHANNEL]: 's' } }),
    );
    startRealtime(EMP);
    await flush();
    await flush();
    expect(connectMock).toHaveBeenCalled();
  });

  it('unsubscribes on stop and survives late resolution', async () => {
    apiMock.mockImplementation((path: string) =>
      path === '/realtime/token'
        ? Promise.resolve(okToken())
        : Promise.resolve({ tokens: { [CHANNEL]: 's' } }),
    );
    const stop = startRealtime(EMP);
    stop(); // stop before async subscription resolves
    await flush();
    await flush();
    expect(subscribeMock).toHaveBeenCalledWith(CHANNEL);
    expect(unsubscribeMock).toHaveBeenCalledWith(CHANNEL);
  });
});

describe('stopRealtime', () => {
  it('disconnects the socket and clears the unavailable flag', async () => {
    apiMock.mockRejectedValue({ status: 503 });
    startRealtime(EMP);
    await flush();
    await flush();
    stopRealtime();
    apiMock.mockImplementation((path: string) =>
      path === '/realtime/token'
        ? Promise.resolve(okToken())
        : Promise.resolve({ tokens: { [CHANNEL]: 's' } }),
    );
    startRealtime(EMP);
    await flush();
    await flush();
    expect(connectMock).toHaveBeenCalled();
  });
});

describe('subscribeRealtimeEvents', () => {
  it('debounces matching events and ignores others', async () => {
    vi.useFakeTimers();
    apiMock.mockImplementation((path: string) =>
      path === '/realtime/token'
        ? Promise.resolve(okToken())
        : Promise.resolve({ tokens: { [CHANNEL]: 's' } }),
    );
    startRealtime(EMP);
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(0);

    const cb = vi.fn();
    const un = subscribeRealtimeEvents(['task.'], cb, 300);
    lastSub.current!.emitPub({ type: 'attendance.checked_in' });
    lastSub.current!.emitPub({ type: 'task.updated' });
    lastSub.current!.emitPub({ type: 'task.updated' });
    vi.advanceTimersByTime(300);
    expect(cb).toHaveBeenCalledTimes(1);
    un();
  });
});

describe('event → cache invalidation map (Phase 4)', () => {
  const start = async () => {
    apiMock.mockImplementation((path: string) =>
      path === '/realtime/token'
        ? Promise.resolve(okToken())
        : Promise.resolve({ tokens: { [CHANNEL]: 's' } }),
    );
    startRealtime(EMP);
    await flush();
    await flush();
  };

  it('task.updated invalidates tasks:* only', async () => {
    await start();
    await swr('tasks:list', async () => ['t'], { ttlMs: 60_000 });
    await swr('attendance:today', async () => 'w', { ttlMs: 60_000 });
    lastSub.current!.emitPub({ type: 'task.updated', uid: 'x' });
    expect(cachePeek('tasks:list')).toBeUndefined();
    expect(cachePeek('attendance:today')).not.toBeUndefined();
  });

  it('maintenance.updated invalidates both maintenance: and tasks:', async () => {
    await start();
    await swr('maintenance:list', async () => ['m'], { ttlMs: 60_000 });
    await swr('tasks:list', async () => ['t'], { ttlMs: 60_000 });
    lastSub.current!.emitPub({ type: 'maintenance.updated', uid: 'x' });
    expect(cachePeek('maintenance:list')).toBeUndefined();
    expect(cachePeek('tasks:list')).toBeUndefined();
  });

  it('unrecovered resubscribe wipes caches and fires UNRECOVERED_EVENT', async () => {
    await start();
    await swr('tasks:list', async () => ['t'], { ttlMs: 60_000 });
    const seen: unknown[] = [];
    const un = subscribeRealtime((e) => seen.push(e));
    const sub = lastSub.current!;
    // wasRecovering && !recovered → silent gap → full invalidate
    sub.emitEvent('subscribed', {
      wasRecovering: true, recovered: false,
    });
    expect(cachePeek('tasks:list')).toBeUndefined();
    expect(seen).toEqual([{ type: 'realtime.unrecovered' }]);
    expect(pollMock).toHaveBeenCalled();
    un();
  });

  it('initial subscribe (wasRecovering=false) does NOT purge caches', async () => {
    await start();
    await swr('tasks:list', async () => ['t'], { ttlMs: 60_000 });
    lastSub.current!.emitEvent('subscribed', {
      wasRecovering: false, recovered: false,
    });
    expect(cachePeek('tasks:list')).not.toBeUndefined();
  });

  it('screens reconcile on unrecovered events via subscribeRealtimeEvents', async () => {
    await start();
    const cb = vi.fn();
    const un = subscribeRealtimeEvents(['task.'], cb, 10);
    lastSub.current!.emitEvent('subscribed', {
      wasRecovering: true, recovered: false,
    });
    await new Promise((r) => setTimeout(r, 30));
    expect(cb).toHaveBeenCalledTimes(1);
    un();
  });

  it('burst of events coalesces to one callback (400ms debounce)', async () => {
    vi.useFakeTimers();
    apiMock.mockImplementation((path: string) =>
      path === '/realtime/token'
        ? Promise.resolve(okToken())
        : Promise.resolve({ tokens: { [CHANNEL]: 's' } }),
    );
    startRealtime(EMP);
    // flush() uses setTimeout — drive it via fake timers here.
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(0);
    const cb = vi.fn();
    const un = subscribeRealtimeEvents(['task.'], cb, 400);
    for (let i = 0; i < 8; i += 1) {
      lastSub.current!.emitPub({ type: 'task.updated', uid: String(i) });
    }
    vi.advanceTimersByTime(400);
    expect(cb).toHaveBeenCalledTimes(1);
    un();
  });
});

describe('realtimeResume', () => {
  it('reconnects the socket and reconciles the feed', async () => {
    apiMock.mockImplementation((path: string) =>
      path === '/realtime/token'
        ? Promise.resolve(okToken())
        : Promise.resolve({ tokens: { [CHANNEL]: 's' } }),
    );
    startRealtime(EMP);
    await flush();
    await flush();
    connectMock.mockClear();
    realtimeResume();
    expect(connectMock).toHaveBeenCalled();
    expect(pollMock).toHaveBeenCalled();
  });

  it('no-ops safely when never started', () => {
    expect(() => realtimeResume()).not.toThrow();
    expect(pollMock).toHaveBeenCalled();
  });
});
