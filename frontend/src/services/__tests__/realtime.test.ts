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
