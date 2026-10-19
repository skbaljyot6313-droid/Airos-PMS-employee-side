import { describe, it, expect, beforeEach, vi } from 'vitest';

// --- Mocks -----------------------------------------------------------------

const listMock = vi.fn();
vi.mock('../../api/notifications', () => ({
  listNotificationsApi: () => listMock(),
  markNotificationReadApi: vi.fn(),
}));

vi.mock('@capacitor/core', () => ({
  Capacitor: { isNativePlatform: () => false },
}));
vi.mock('@capacitor/app', () => ({
  App: { addListener: vi.fn(() => Promise.resolve({ remove: vi.fn() })) },
}));

import {
  startNotificationPolling,
  pollNotificationsNow,
} from '../notificationService';

beforeEach(() => {
  vi.useRealTimers();
  // vitest runs in node — startNotificationPolling touches document.
  vi.stubGlobal('document', {
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    visibilityState: 'visible',
  });
  listMock.mockReset();
  listMock.mockResolvedValue([]);
});

describe('pollNotificationsNow', () => {
  it('coalesces a burst of realtime nudges into one feed poll', async () => {
    vi.useFakeTimers();
    const stop = startNotificationPolling();
    await vi.advanceTimersByTimeAsync(0); // immediate baseline poll
    expect(listMock).toHaveBeenCalledTimes(1);

    pollNotificationsNow();
    pollNotificationsNow();
    pollNotificationsNow();
    await vi.advanceTimersByTimeAsync(500); // > 400ms debounce window
    expect(listMock).toHaveBeenCalledTimes(2);
    stop();
  });

  it('no-ops safely when no poll loop is running', async () => {
    vi.useFakeTimers();
    pollNotificationsNow();
    await vi.advanceTimersByTimeAsync(1000);
    expect(listMock).not.toHaveBeenCalled();
  });
});
