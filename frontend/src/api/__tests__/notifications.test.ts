import { describe, it, expect } from 'vitest';
import { mapNotification } from '../notifications';
import { NotificationWire } from '../wire';
import { diffNewNotifications } from '../../services/notificationService';
import { StaffNotification } from '../../types';

const wire = (over: Partial<NotificationWire> = {}): NotificationWire => ({
  notification_uid: 'n-1',
  type: 'task_assigned',
  title: 'New Task Assigned',
  body: 'Mop lobby',
  task_uid: 'task-1',
  ticket_uid: null,
  is_read: false,
  read_at: null,
  created_at: '2026-10-09T10:00:00Z',
  ...over,
});

const display = (id: string, createdAt = '2026-10-09T10:00:00Z'): StaffNotification => ({
  id, type: 'task_assigned', title: 't', body: 'b',
  taskId: 'x', ticketId: null, isRead: false, createdAt,
});

describe('mapNotification', () => {
  it('maps wire fields to the display shape', () => {
    const n = mapNotification(wire());
    expect(n.id).toBe('n-1');
    expect(n.type).toBe('task_assigned');
    expect(n.taskId).toBe('task-1');
    expect(n.ticketId).toBeNull();
    expect(n.isRead).toBe(false);
  });

  it('carries ticket links and read state', () => {
    const n = mapNotification(wire({
      type: 'ticket_assigned', task_uid: null, ticket_uid: 'tk-9',
      is_read: true, read_at: '2026-10-09T11:00:00Z',
    }));
    expect(n.ticketId).toBe('tk-9');
    expect(n.taskId).toBeNull();
    expect(n.isRead).toBe(true);
  });
});

describe('diffNewNotifications', () => {
  it('returns only unseen ids, oldest first', () => {
    const items = [
      display('c', '2026-10-09T12:00:00Z'),
      display('a', '2026-10-09T10:00:00Z'),
      display('b', '2026-10-09T11:00:00Z'),
    ];
    const known = new Set(['a']);
    const fresh = diffNewNotifications(items, known);
    expect(fresh.map((n) => n.id)).toEqual(['b', 'c']);
  });

  it('returns nothing when everything is known', () => {
    const items = [display('a'), display('b')];
    expect(diffNewNotifications(items, new Set(['a', 'b']))).toEqual([]);
  });
});
