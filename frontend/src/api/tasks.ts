/**
 * Tasks API — GET /tasks is employee-scoped server-side; the backend is
 * authoritative on status, checklist, verification and history.
 * Responses are normalized here into the display `Task` shape.
 */

import { apiClient } from './client';
import { getZoneNameMap } from './directory';
import { ListResponseWire, TaskCompletionImageWire, TaskWire } from './wire';
import { Task, TaskBucket, TaskStatus, EvidenceItem, TaskSubmission } from '../types';

const titleCase = (s: string): string =>
  s
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());

/** A date-only string ("2026-10-03") carries no clock time — showing one
 *  would fabricate a due hour. */
export const hasClockTime = (v?: string | null): boolean => !!v && v.includes('T');

/** Map a backend task status onto the three list buckets. */
export const taskBucket = (status: string): TaskBucket => {
  if (status === 'submitted') return 'in_review';
  if (status === 'completed' || status === 'cancelled' || status === 'abandoned') return 'done';
  // assigned, pending, in_progress, reopened, scheduled, overdue (+ unknowns)
  return 'to_do';
};

const locationName = (t: TaskWire): string => {
  if (t.room_number) return `Room ${t.room_number}`;
  if (t.dorm_name) {
    const beds = t.bed_uids?.length ? ` · ${t.bed_uids.length} bed${t.bed_uids.length > 1 ? 's' : ''}` : '';
    return `${t.dorm_name}${beds}`;
  }
  if (t.washroom_name) {
    return t.washroom_fixture_label
      ? `${t.washroom_name} · ${t.washroom_fixture_label}`
      : t.washroom_name;
  }
  return 'Common area';
};

export const mapTask = (t: TaskWire, zoneNames: Map<string, string>): Task => {
  const checklist: Task['checklist'] = (t.checklist ?? []).map((c, i) => ({
    id: `cl-${i}`,
    label: c.title ?? '',
    required: c.required !== false,
    completed: false,
    description: c.description ?? null,
  }));

  const history: Task['history'] = (t.history ?? []).map((h) => ({
    id: h.event_uid,
    event_type: h.type,
    timestamp: h.at,
    notes: h.note,
    actor_name: h.actor_name,
  }));

  const reopenEvent = [...history]
    .sort((a, b) => (a.timestamp < b.timestamp ? 1 : -1))
    .find((h) => h.event_type === 'rejected' || h.event_type === 'reopened' || h.event_type === 'redo_requested');

  const verification = t.verification ?? {};

  const toEvidence = (i: TaskCompletionImageWire, fallbackId: string): EvidenceItem => ({
    id: i.image_uid ?? fallbackId,
    // Raw backend path — submissions resend this verbatim; views resolve
    // it via mediaUrl() when rendering.
    url: i.url ?? '',
    filename: i.file_name,
    uploaded_at: i.created_at,
  });

  // Every submission attempt, oldest first — screens render these read-only
  // so returned-for-correction work stays visible next to the new attempt.
  const prior_submissions: TaskSubmission[] = [...(t.completion_submissions ?? [])]
    .sort((a, b) => a.attempt_number - b.attempt_number)
    .map((s) => ({
      attempt: s.attempt_number,
      submitted_at: s.submitted_at ?? null,
      status: s.status,
      review_comment: s.review_comment ?? null,
      reviewed_by_name: s.reviewed_by_name ?? null,
      photos: (s.images ?? []).map((i, idx) => toEvidence(i, `sub-${s.attempt_number}-ev-${idx}`)),
    }));

  // Evidence mirrors the newest attempt when submissions exist; the flat
  // completion_images list is the fallback for tasks without them.
  const latestSubmission = prior_submissions[prior_submissions.length - 1];
  const evidence: EvidenceItem[] = latestSubmission
    ? latestSubmission.photos
    : (t.completion_images ?? []).map((i, idx) => toEvidence(i, `ev-${idx}`));

  return {
    id: t.task_uid,
    ticket_number: t.ticket_number ?? null,
    title: t.title,
    category: titleCase(t.work_type || t.task_type || 'task'),
    location_name: locationName(t),
    zone_uid: t.zone_uid ?? null,
    zone_name: t.zone_uid ? zoneNames.get(t.zone_uid) ?? null : null,
    priority: t.priority as Task['priority'],
    status: t.status as TaskStatus,
    due_at: hasClockTime(t.due_date) ? t.due_date : null,
    due_date: t.due_date ?? null,
    due_time: t.due_time ?? null,
    scheduled_for: t.scheduled_for ?? null,
    expires_at: t.expires_at ?? null,
    instructions: t.description ?? null,
    checklist,
    verification_config: {
      photo_required: !!verification.photo_required,
      min_photos: verification.min_photos ?? (verification.photo_required ? 1 : 0),
      // Backend cap MAX_TASK_COMPLETION_IMAGES defaults to 10.
      max_photos: verification.max_photos ?? 10,
      checklist_required: verification.checklist_required,
      supervisor_approval: verification.supervisor_approval,
    },
    evidence,
    prior_submissions,
    reopen_reason: reopenEvent?.notes ?? null,
    history,
    assigned_to_employee_id: t.employee_uid ?? null,
    assigned_to_name: t.assigned_to_name ?? null,
    supervisor_name: t.supervisor_name ?? null,
  };
};

export async function fetchTasksApi(): Promise<Task[]> {
  const [tasksRes, zoneNames] = await Promise.all([
    apiClient<ListResponseWire<TaskWire>>('/tasks?limit=200', { method: 'GET' }),
    getZoneNameMap(),
  ]);
  return tasksRes.items.map((t) => mapTask(t, zoneNames));
}

export async function getTaskDetailApi(id: string): Promise<Task> {
  const [t, zoneNames] = await Promise.all([
    apiClient<TaskWire>(`/tasks/${encodeURIComponent(id)}`, { method: 'GET' }),
    getZoneNameMap(),
  ]);
  return mapTask(t, zoneNames);
}

export async function startTaskApi(id: string): Promise<Task> {
  const t = await apiClient<TaskWire>(`/tasks/${encodeURIComponent(id)}/start`, { method: 'POST' });
  return mapTask(t, new Map());
}

/** Employee completion path — status → submitted, awaits supervisor review.
 *  The backend accepts { note, photo_urls }; checklist state is a client-side
 *  gate only (the server validates evidence, not the checkbox list). */
export async function submitTaskApi(
  id: string,
  payload: {
    note?: string;
    photo_urls: string[];
  }
): Promise<Task> {
  const t = await apiClient<TaskWire>(`/tasks/${encodeURIComponent(id)}/submit`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return mapTask(t, new Map());
}
