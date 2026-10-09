/**
 * Notifications API — the employee's own feed.
 *
 *   GET  /notifications            → { items: NotificationWire[] }
 *   GET  /notifications/unread-count → { unread: number }
 *   POST /notifications/{uid}/read → NotificationWire
 *
 * The backend materializes allocation notifications on read — task and
 * ticket assignments are written to the shared ledger by the Super Admin
 * backend, and the feed synthesizes rows from it when the app polls.
 * Polling the list therefore both delivers and fetches new events.
 */

import { apiClient } from './client';
import { NotificationWire, UnreadCountWire } from './wire';
import { StaffNotification } from '../types';

export const mapNotification = (w: NotificationWire): StaffNotification => ({
  id: w.notification_uid,
  type: w.type,
  title: w.title,
  body: w.body,
  taskId: w.task_uid,
  ticketId: w.ticket_uid,
  isRead: w.is_read,
  createdAt: w.created_at,
});

/** The caller's own feed, newest first. This GET is also the sync
 *  trigger — each call materializes any new SA-side assignments. */
export async function listNotificationsApi(
  unreadOnly = false,
): Promise<StaffNotification[]> {
  const res = await apiClient<{ items: NotificationWire[] }>(
    `/notifications${unreadOnly ? '?unread_only=true' : ''}`,
  );
  return (res?.items ?? []).map(mapNotification);
}

export async function unreadCountApi(): Promise<number> {
  const res = await apiClient<UnreadCountWire | undefined>(
    '/notifications/unread-count',
  );
  return res?.unread ?? 0;
}

export async function markNotificationReadApi(
  uid: string,
): Promise<void> {
  await apiClient(`/notifications/${encodeURIComponent(uid)}/read`, {
    method: 'POST',
  });
}
