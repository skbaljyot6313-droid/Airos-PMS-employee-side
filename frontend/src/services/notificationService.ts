/**
 * Notification polling — drives the in-app popup for work allocation.
 *
 * The backend materializes task/ticket assignments on `GET /notifications`
 * (the Super Admin backend writes the shared ledger; this app's service
 * layer never sees those events), so polling the feed is both the sync
 * trigger and the delivery channel.
 *
 * Semantics:
 *  - The first successful poll only seeds the known-id baseline —
 *    pre-existing notifications never pop up (app launch would otherwise
 *    re-toast the whole history).
 *  - Every later poll emits items whose ids weren't in the baseline,
 *    oldest first.
 *  - Failures are silent — the next tick retries; the feed is
 *    best-effort UI, never a crash surface.
 */

import { Capacitor } from '@capacitor/core';
import { App as CapacitorApp } from '@capacitor/app';
import { listNotificationsApi } from '../api/notifications';
import { StaffNotification } from '../types';

const POLL_MS = 45_000;

const listeners = new Set<(n: StaffNotification) => void>();

export function subscribeNotifications(
  listener: (n: StaffNotification) => void,
): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function emit(n: StaffNotification): void {
  listeners.forEach((l) => l(n));
}

/** Diff a fetched feed against known ids — pure, unit-tested. Returns
 *  the unseen items in oldest-first order (popup order). */
export function diffNewNotifications(
  items: StaffNotification[],
  known: ReadonlySet<string>,
): StaffNotification[] {
  return items
    .filter((n) => !known.has(n.id))
    .sort((a, b) => a.createdAt.localeCompare(b.createdAt));
}

/**
 * Start the poll loop; returns a stop function. Polls immediately, then
 * every POLL_MS, plus on app resume (native) and tab re-focus (web).
 */
export function startNotificationPolling(): () => void {
  const known = new Set<string>();
  let seeded = false;
  let inFlight: Promise<void> | null = null;
  let stopped = false;

  const poll = (): void => {
    if (stopped || inFlight) return;
    inFlight = listNotificationsApi()
      .then((items) => {
        if (!seeded) {
          items.forEach((n) => known.add(n.id));
          seeded = true;
          return;
        }
        for (const n of diffNewNotifications(items, known)) {
          known.add(n.id);
          emit(n);
        }
      })
      .catch(() => {
        /* silent — next tick retries */
      })
      .finally(() => {
        inFlight = null;
      });
  };

  poll();
  const timer = setInterval(poll, POLL_MS);

  const onVisibility = () => {
    if (document.visibilityState === 'visible') poll();
  };
  document.addEventListener('visibilitychange', onVisibility);

  let appStateHandle: { remove: () => void } | null = null;
  if (Capacitor.isNativePlatform()) {
    void CapacitorApp.addListener('appStateChange', ({ isActive }) => {
      if (isActive) poll();
    }).then((h) => {
      appStateHandle = h;
    });
  }

  return () => {
    stopped = true;
    clearInterval(timer);
    document.removeEventListener('visibilitychange', onVisibility);
    appStateHandle?.remove();
  };
}
