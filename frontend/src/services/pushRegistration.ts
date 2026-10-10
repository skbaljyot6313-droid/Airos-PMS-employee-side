/**
 * FCM push registration — Capacitor PushNotifications bridge.
 *
 * Real server-triggered delivery (FCM), independent of the app process:
 * the OS shows notification messages when the app is backgrounded or
 * killed; the FirebaseMessagingService wakes the app for data. The
 * 45s feed poll in notificationService remains the in-app fallback.
 *
 * Token lifecycle: register() hands us the FCM token → POST
 * /devices/register (upsert on employee+device). 'registration' fires
 * again whenever FCM rotates the token, so re-POST on every event.
 * Logout path calls unregisterPushDevice() → POST /devices/unregister.
 *
 * Force-stop caveat: Android's force-stop (Settings → Apps) blocks FCM
 * delivery until the next manual launch — an OS restriction no
 * notification channel can bypass.
 */

import { Capacitor } from '@capacitor/core';
import { App as CapacitorApp } from '@capacitor/app';
import {
  PushNotifications,
  PushNotificationSchema,
  ActionPerformed,
  Token,
} from '@capacitor/push-notifications';

import { registerDeviceApi, unregisterDeviceApi } from '../api/notifications';
import { StaffNotification } from '../types';

const APP_VERSION = '1.0.9'; // keep in sync with app.json expo.version
const DEVICE_ID_KEY = 'airos_device_id';

export type PushTap = { taskId?: string; ticketId?: string };
type TapHandler = (t: PushTap) => void;

const foregroundListeners = new Set<(n: StaffNotification) => void>();
let onTap: TapHandler | null = null;
let cachedDeviceId: string | null = null;

/** Stable per-install device id — survives token rotation. */
function deviceId(): string {
  if (!cachedDeviceId) {
    cachedDeviceId = localStorage.getItem(DEVICE_ID_KEY);
    if (!cachedDeviceId) {
      cachedDeviceId =
        crypto.randomUUID?.() ??
        `d-${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
      localStorage.setItem(DEVICE_ID_KEY, cachedDeviceId);
    }
  }
  return cachedDeviceId;
}

async function uploadToken(token: string): Promise<void> {
  await registerDeviceApi({
    deviceId: deviceId(),
    pushToken: token,
    platform: 'android',
    appVersion: APP_VERSION,
  });
}

/** Foreground pushes surface through the same popup queue the feed
 *  poller drives — subscribe in App alongside subscribeNotifications. */
export function subscribeForegroundPush(
  l: (n: StaffNotification) => void,
): () => void {
  foregroundListeners.add(l);
  return () => foregroundListeners.delete(l);
}

function emitForeground(n: PushNotificationSchema): void {
  const data = (n.data ?? {}) as Record<string, string>;
  const item: StaffNotification = {
    id: data.notification_uid || `fcm-${Date.now()}`,
    type: data.type || 'push',
    title: n.title ?? 'New work assigned',
    body: n.body ?? 'You have been assigned new work.',
    taskId: data.task_uid ?? null,
    ticketId: data.ticket_uid ?? null,
    isRead: false,
    createdAt: new Date().toISOString(),
  };
  foregroundListeners.forEach((l) => l(item));
}

/** Called once per auth'd session from App. Registers listeners,
 *  requests permission (Android 13+), uploads the FCM token. Safe to
 *  re-call after logout/login. Returns a teardown. */
export function initPushNotifications(tapHandler: TapHandler): () => void {
  onTap = tapHandler;
  if (!Capacitor.isNativePlatform()) return () => {};

  let cancelled = false;
  const handles: { remove: () => void }[] = [];

  void PushNotifications.addListener('registration', (t: Token) => {
    void uploadToken(t.value).catch(() => undefined);
  }).then((h) => handles.push(h));

  void PushNotifications.addListener('registrationError', (e) => {
    console.warn('push registration failed', e.error);
  }).then((h) => handles.push(h));

  void PushNotifications.addListener(
    'pushNotificationReceived',
    (n: PushNotificationSchema) => emitForeground(n),
  ).then((h) => handles.push(h));

  void PushNotifications.addListener(
    'pushNotificationActionPerformed',
    (a: ActionPerformed) => {
      const data = (a.notification.data ?? {}) as Record<string, string>;
      onTap?.({ taskId: data.task_uid, ticketId: data.ticket_uid });
    },
  ).then((h) => handles.push(h));

  void (async () => {
    const perm = await PushNotifications.requestPermissions();
    if (perm.receive !== 'granted' || cancelled) return;
    await PushNotifications.register().catch(() => undefined);
  })();

  // Re-register on resume so a rotated token never sits stale.
  let appState: { remove: () => void } | null = null;
  void CapacitorApp.addListener('appStateChange', ({ isActive }) => {
    if (isActive) void PushNotifications.register().catch(() => undefined);
  }).then((h) => {
    appState = h;
  });

  return () => {
    cancelled = true;
    onTap = null;
    handles.forEach((h) => h.remove());
    appState?.remove();
  };
}

/** Logout teardown — deactivate this device's token server-side. */
export async function unregisterPushDevice(): Promise<void> {
  if (!Capacitor.isNativePlatform()) return;
  try {
    await unregisterDeviceApi(deviceId());
  } catch {
    /* logout must never fail on push cleanup */
  }
}
