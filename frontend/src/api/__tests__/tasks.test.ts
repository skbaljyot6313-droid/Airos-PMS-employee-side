import { describe, it, expect } from 'vitest';
import { mapTask, taskBucket, hasClockTime } from '../tasks';
import { TaskWire, TaskCompletionImageWire, TaskCompletionSubmissionWire } from '../wire';

const baseWire = (over: Partial<TaskWire> = {}): TaskWire => ({
  task_uid: 'task-1',
  ticket_number: 'TASK-2026-00001',
  property_uid: 'prop-1',
  zone_uid: 'zone-1',
  area_uid: null,
  room_uid: 'room-1',
  room_number: '204',
  dorm_uid: null,
  dorm_name: null,
  bed_uids: null,
  washroom_uid: null,
  washroom_name: null,
  washroom_fixture_uid: null,
  washroom_fixture_label: null,
  supervisor_uid: null,
  supervisor_name: 'Sam Sup',
  employee_uid: 'emp-1',
  assigned_to_name: 'Alice',
  allocation_batch_id: null,
  allocation_status: 'auto_assigned',
  allocation_method: null,
  allocation_reason: null,
  title: 'Clean room 204',
  description: 'Deep clean',
  task_type: 'fixed',
  work_type: 'cleaning',
  origin: 'manual',
  status: 'assigned',
  priority: 'high',
  due_date: null,
  due_time: null,
  start_time: null,
  recurrence_start_date: null,
  recurrence_end_date: null,
  recurrence_window_end: null,
  created_by_name: null,
  recurrence: null,
  recurrence_interval_days: null,
  series_id: null,
  scheduled_for: null,
  expires_at: null,
  template_id: null,
  abandoned_at: null,
  abandoned_reason: null,
  abandoned_from_status: null,
  automation_rule: null,
  history: [],
  completion_images: [],
  completion_submissions: [],
  submitted_at: null,
  completed_at: null,
  created_at: '2026-01-01T00:00:00Z',
  checklist: null,
  verification: null,
  ...over,
});

const zones = new Map([['zone-1', 'North Wing']]);

const imageWire = (
  image_uid: string,
  url: string,
  submission_uid: string | null = null
): TaskCompletionImageWire => ({
  image_uid,
  task_uid: 'task-1',
  event_uid: 'ev-1',
  submission_uid,
  url,
  file_name: url.split('/').pop() ?? null,
  created_by_name: 'Alice',
  created_at: '2026-01-02T09:00:00Z',
});

const submissionWire = (
  over: Partial<TaskCompletionSubmissionWire> = {}
): TaskCompletionSubmissionWire => ({
  submission_uid: 'sub-1',
  task_uid: 'task-1',
  event_uid: 'ev-1',
  attempt_number: 1,
  employee_uid: 'emp-1',
  employee_name: 'Alice',
  submitted_at: '2026-01-02T09:00:00Z',
  status: 'pending',
  reviewed_at: null,
  reviewer_uid: null,
  reviewed_by_name: null,
  review_comment: null,
  images: [],
  ...over,
});

describe('mapTask', () => {
  it('keeps due_at null for date-only due_date', () => {
    const t = mapTask(baseWire({ due_date: '2026-10-03' }), zones);
    expect(t.due_at).toBeNull();
    expect(t.due_date).toBe('2026-10-03');
  });

  it('sets due_at when due_date carries a clock time', () => {
    const iso = '2026-10-03T14:30:00';
    const t = mapTask(baseWire({ due_date: iso }), zones);
    expect(t.due_at).toBe(iso);
  });

  it('keeps evidence urls raw (no origin prefix)', () => {
    const t = mapTask(
      baseWire({
        completion_images: [
          {
            image_uid: 'img-1',
            task_uid: 'task-1',
            event_uid: 'ev-1',
            submission_uid: 'sub-1',
            url: '/uploads/a.jpg',
            file_name: 'a.jpg',
            created_by_name: 'Alice',
            created_at: '2026-01-02T00:00:00Z',
          },
        ],
      }),
      zones
    );
    expect(t.evidence[0].url).toBe('/uploads/a.jpg');
  });

  it('derives reopen_reason from the latest rejected/reopened/redo_requested event', () => {
    const t = mapTask(
      baseWire({
        status: 'reopened',
        history: [
          { event_uid: 'e1', type: 'submitted', at: '2026-01-01T10:00:00Z', actor_name: 'A', note: 'done', photos: [] },
          { event_uid: 'e2', type: 'rejected', at: '2026-01-02T10:00:00Z', actor_name: 'Sup', note: 'redo the sink', photos: [] },
          { event_uid: 'e3', type: 'reopened', at: '2026-01-03T10:00:00Z', actor_name: 'Sup', note: 'newer note', photos: [] },
        ],
      }),
      zones
    );
    expect(t.reopen_reason).toBe('newer note');
  });

  it('applies verification defaults (min from photo_required, max 10)', () => {
    const noReq = mapTask(baseWire({ verification: { photo_required: false } }), zones);
    expect(noReq.verification_config).toMatchObject({ photo_required: false, min_photos: 0, max_photos: 10 });

    const req = mapTask(baseWire({ verification: { photo_required: true } }), zones);
    expect(req.verification_config.min_photos).toBe(1);

    const explicit = mapTask(
      baseWire({ verification: { photo_required: true, min_photos: 3, max_photos: 6 } }),
      zones
    );
    expect(explicit.verification_config).toMatchObject({ min_photos: 3, max_photos: 6 });
  });

  it('maps checklist items with required defaulting true', () => {
    const t = mapTask(
      baseWire({ checklist: [{ title: 'Strip bed' }, { title: 'Mop', required: false, description: 'carefully' }] }),
      zones
    );
    expect(t.checklist).toHaveLength(2);
    expect(t.checklist[0]).toMatchObject({ label: 'Strip bed', required: true, completed: false });
    expect(t.checklist[1]).toMatchObject({ label: 'Mop', required: false, description: 'carefully' });
  });

  it('resolves zone_name and location_name', () => {
    const t = mapTask(baseWire(), zones);
    expect(t.zone_name).toBe('North Wing');
    expect(t.location_name).toBe('Room 204');
  });

  it('groups completion_submissions into prior_submissions and uses the latest for evidence', () => {
    const t = mapTask(
      baseWire({
        status: 'submitted',
        // Deliberately unordered + a flat list that overlaps attempt 1 —
        // the mapper must group by submission and pick the highest attempt.
        completion_submissions: [
          submissionWire({
            submission_uid: 'sub-2',
            attempt_number: 2,
            submitted_at: '2026-01-03T09:00:00Z',
            status: 'pending',
            images: [imageWire('img-3', '/uploads/c.jpg', 'sub-2')],
          }),
          submissionWire({
            submission_uid: 'sub-1',
            attempt_number: 1,
            submitted_at: '2026-01-02T09:00:00Z',
            status: 'disapproved',
            reviewed_at: '2026-01-02T12:00:00Z',
            reviewer_uid: 'sup-1',
            reviewed_by_name: 'Sam Sup',
            review_comment: 'redo the sink',
            images: [
              imageWire('img-1', '/uploads/a.jpg', 'sub-1'),
              imageWire('img-2', '/uploads/b.jpg', 'sub-1'),
            ],
          }),
        ],
        completion_images: [
          imageWire('img-1', '/uploads/a.jpg', 'sub-1'),
          imageWire('img-2', '/uploads/b.jpg', 'sub-1'),
          imageWire('img-3', '/uploads/c.jpg', 'sub-2'),
        ],
      }),
      zones
    );

    // Sorted ascending by attempt_number, each carrying its own photos.
    expect(t.prior_submissions.map((s) => s.attempt)).toEqual([1, 2]);
    expect(t.prior_submissions[0]).toMatchObject({
      status: 'disapproved',
      submitted_at: '2026-01-02T09:00:00Z',
      review_comment: 'redo the sink',
      reviewed_by_name: 'Sam Sup',
    });
    expect(t.prior_submissions[0].photos.map((p) => p.url)).toEqual([
      '/uploads/a.jpg',
      '/uploads/b.jpg',
    ]);
    expect(t.prior_submissions[1].photos.map((p) => p.url)).toEqual(['/uploads/c.jpg']);

    // Evidence mirrors the newest attempt, not the flat image list.
    expect(t.evidence.map((p) => p.url)).toEqual(['/uploads/c.jpg']);
  });

  it('exposes prior_submissions on reopened tasks so old photos stay separate', () => {
    const t = mapTask(
      baseWire({
        status: 'reopened',
        completion_submissions: [
          submissionWire({
            status: 'disapproved',
            reviewed_by_name: 'Sam Sup',
            review_comment: 'redo the sink',
            images: [imageWire('img-1', '/uploads/a.jpg', 'sub-1')],
          }),
        ],
        completion_images: [imageWire('img-1', '/uploads/a.jpg', 'sub-1')],
      }),
      zones
    );

    expect(t.status).toBe('reopened');
    expect(t.prior_submissions).toHaveLength(1);
    expect(t.prior_submissions[0].attempt).toBe(1);
    expect(t.prior_submissions[0].photos.map((p) => p.url)).toEqual(['/uploads/a.jpg']);
    // Latest submission's photos — the screen clears these for the new attempt.
    expect(t.evidence.map((p) => p.url)).toEqual(['/uploads/a.jpg']);
  });

  it('falls back to flat completion_images when there are no submissions', () => {
    const t = mapTask(
      baseWire({ completion_images: [imageWire('img-1', '/uploads/a.jpg')] }),
      zones
    );
    expect(t.prior_submissions).toEqual([]);
    expect(t.evidence.map((p) => p.url)).toEqual(['/uploads/a.jpg']);
  });
});

describe('taskBucket', () => {
  it.each(['assigned', 'pending', 'in_progress', 'reopened', 'scheduled', 'overdue'])(
    'to_do: %s',
    (s) => expect(taskBucket(s)).toBe('to_do')
  );
  it('submitted → in_review', () => expect(taskBucket('submitted')).toBe('in_review'));
  it.each(['completed', 'cancelled', 'abandoned'])('done: %s', (s) =>
    expect(taskBucket(s)).toBe('done')
  );
});

describe('hasClockTime', () => {
  it('detects ISO datetimes only', () => {
    expect(hasClockTime('2026-10-03T10:00:00')).toBe(true);
    expect(hasClockTime('2026-10-03')).toBe(false);
    expect(hasClockTime(null)).toBe(false);
  });
});
