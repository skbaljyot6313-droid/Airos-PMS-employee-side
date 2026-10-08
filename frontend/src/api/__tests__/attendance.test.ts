import { describe, it, expect } from 'vitest';
import {
  LEAVE_TYPE_LABELS,
  REQUEST_STATUS_LABELS,
  businessDate,
  coveredDates,
  emptyWorkday,
  isNotImplemented,
  mapAttendanceDay,
  mapDayOffRequest,
  mapWorkday,
  monthKey,
  nextWorkdayState,
  requestCoversDate,
  requestTypeLabel,
} from '../attendance';
import { AttendanceDayWire, AttendanceRequestWire, WorkdayWire } from '../wire';
import { Workday } from '../../types';

const workdayWire = (over: Partial<WorkdayWire> = {}): WorkdayWire => ({
  state: 'working',
  date: '2026-10-12',
  started_at: '2026-10-12T04:00:00Z',
  break_started_at: null,
  ended_at: null,
  ...over,
});

describe('mapWorkday', () => {
  it('maps wire fields straight through, null-safe on timestamps', () => {
    const w = mapWorkday(workdayWire({ break_started_at: '2026-10-12T08:00:00Z' }));
    expect(w).toEqual({
      state: 'working',
      date: '2026-10-12',
      started_at: '2026-10-12T04:00:00Z',
      break_started_at: '2026-10-12T08:00:00Z',
      ended_at: null,
    });
  });

  it('maps a completed workday', () => {
    const w = mapWorkday(
      workdayWire({ state: 'completed', ended_at: '2026-10-12T13:00:00Z' })
    );
    expect(w.state).toBe('completed');
    expect(w.ended_at).toBe('2026-10-12T13:00:00Z');
  });
});

describe('mapAttendanceDay / mapDayOffRequest', () => {
  it('maps a calendar day incl. the leave status', () => {
    const wire: AttendanceDayWire = { date: '2026-10-05', status: 'leave' };
    expect(mapAttendanceDay(wire)).toEqual({
      date: '2026-10-05',
      status: 'leave',
    });
  });

  it('maps a range request: request_uid → id, null-safe fields', () => {
    const wire: AttendanceRequestWire = {
      request_uid: 'req-1',
      from_date: '2026-10-20',
      to_date: '2026-10-22',
      request_type: 'leave',
      leave_type: 'casual_leave',
      requested_days: 3,
      status: 'pending',
      reason: null,
      review_comment: null,
      reviewed_by_name: null,
      reviewed_at: null,
      employee_uid: 'emp-1',
      employee_name: 'Worker One',
      created_at: '2026-10-12T05:00:00Z',
    };
    expect(mapDayOffRequest(wire)).toEqual({
      id: 'req-1',
      from_date: '2026-10-20',
      to_date: '2026-10-22',
      request_type: 'leave',
      leave_type: 'casual_leave',
      requested_days: 3,
      status: 'pending',
      reason: null,
      created_at: '2026-10-12T05:00:00Z',
    });
  });

  it('maps a week_off request with null leave_type', () => {
    const wire: AttendanceRequestWire = {
      request_uid: 'req-2',
      from_date: '2026-10-25',
      to_date: '2026-10-25',
      request_type: 'week_off',
      leave_type: null,
      requested_days: 1,
      status: 'approved',
      reason: null,
      review_comment: 'ok',
      reviewed_by_name: 'PM',
      reviewed_at: '2026-10-13T05:00:00Z',
      employee_uid: 'emp-1',
      employee_name: 'Worker One',
      created_at: '2026-10-12T05:00:00Z',
    };
    const r = mapDayOffRequest(wire);
    expect(r.request_type).toBe('week_off');
    expect(r.leave_type).toBeNull();
    expect(r.requested_days).toBe(1);
  });
});

describe('request display labels', () => {
  it('requestTypeLabel resolves leave types and week_off', () => {
    expect(
      requestTypeLabel({ request_type: 'leave', leave_type: 'casual_leave' })
    ).toBe('Casual Leave');
    expect(
      requestTypeLabel({ request_type: 'leave', leave_type: 'sick_leave' })
    ).toBe('Sick Leave');
    expect(requestTypeLabel({ request_type: 'week_off', leave_type: null })).toBe(
      'Week Off'
    );
    // null leave_type on a leave request falls back to 'Other'
    expect(requestTypeLabel({ request_type: 'leave', leave_type: null })).toBe(
      'Other'
    );
    expect(LEAVE_TYPE_LABELS.paid_leave).toBe('Paid Leave');
  });

  it('REQUEST_STATUS_LABELS map pending → Requested (history kept)', () => {
    expect(REQUEST_STATUS_LABELS).toEqual({
      pending: 'Requested',
      approved: 'Approved',
      rejected: 'Rejected',
      cancelled: 'Cancelled',
    });
  });
});

describe('requestCoversDate / coveredDates', () => {
  const range = { from_date: '2026-10-10', to_date: '2026-10-15' };

  it('boundaries are inclusive', () => {
    expect(requestCoversDate(range, '2026-10-10')).toBe(true);
    expect(requestCoversDate(range, '2026-10-15')).toBe(true);
    expect(requestCoversDate(range, '2026-10-09')).toBe(false);
    expect(requestCoversDate(range, '2026-10-16')).toBe(false);
  });

  it('covers single-day ranges', () => {
    const single = { from_date: '2026-10-10', to_date: '2026-10-10' };
    expect(requestCoversDate(single, '2026-10-10')).toBe(true);
    expect(requestCoversDate(single, '2026-10-11')).toBe(false);
  });

  it('expands every date in the inclusive range', () => {
    expect(coveredDates('2026-10-13', '2026-10-16')).toEqual([
      '2026-10-13',
      '2026-10-14',
      '2026-10-15',
      '2026-10-16',
    ]);
  });

  it('spans month boundaries', () => {
    expect(coveredDates('2026-10-30', '2026-11-02')).toEqual([
      '2026-10-30',
      '2026-10-31',
      '2026-11-01',
      '2026-11-02',
    ]);
  });
});

describe('isNotImplemented', () => {
  it.each([404, 501])('true for status %s', (status) =>
    expect(isNotImplemented({ status, message: 'x' })).toBe(true)
  );

  it.each([0, 400, 401, 403, 409, 422, 500, 503])(
    'false for status %s',
    (status) => expect(isNotImplemented({ status, message: 'x' })).toBe(false)
  );

  it('false for non-ApiError values', () => {
    expect(isNotImplemented(null)).toBe(false);
    expect(isNotImplemented(undefined)).toBe(false);
    expect(isNotImplemented('not found')).toBe(false);
    expect(isNotImplemented({})).toBe(false);
  });
});

describe('nextWorkdayState', () => {
  const at = '2026-10-12T05:30:00Z';
  const day = (state: Workday['state'], over: Partial<Workday> = {}): Workday => ({
    ...emptyWorkday('2026-10-12'),
    state,
    ...over,
  });

  it('not_started + start → working with started_at', () => {
    const next = nextWorkdayState(day('not_started'), 'start', at);
    expect(next.state).toBe('working');
    expect(next.started_at).toBe(at);
  });

  it('working + break → on_break with break_started_at', () => {
    const next = nextWorkdayState(
      day('working', { started_at: '2026-10-12T04:00:00Z' }),
      'break',
      at
    );
    expect(next.state).toBe('on_break');
    expect(next.break_started_at).toBe(at);
    expect(next.started_at).toBe('2026-10-12T04:00:00Z');
  });

  it('on_break + resume → working and clears break_started_at', () => {
    const next = nextWorkdayState(
      day('on_break', { break_started_at: '2026-10-12T08:00:00Z' }),
      'resume',
      at
    );
    expect(next.state).toBe('working');
    expect(next.break_started_at).toBeNull();
  });

  it('working + end → completed with ended_at', () => {
    const next = nextWorkdayState(day('working'), 'end', at);
    expect(next.state).toBe('completed');
    expect(next.ended_at).toBe(at);
  });

  it.each<[Workday['state'], Parameters<typeof nextWorkdayState>[1]]>([
    ['not_started', 'break'],
    ['not_started', 'resume'],
    ['not_started', 'end'],
    ['working', 'start'],
    ['working', 'resume'],
    ['on_break', 'start'],
    ['on_break', 'break'],
    ['on_break', 'end'],
    ['completed', 'start'],
    ['completed', 'break'],
    ['completed', 'resume'],
    ['completed', 'end'],
  ])('%s + %s is a no-op (same object)', (state, action) => {
    const d = day(state);
    expect(nextWorkdayState(d, action, at)).toBe(d);
  });

  it('does not mutate the input workday', () => {
    const d = day('not_started');
    const next = nextWorkdayState(d, 'start', at);
    expect(d.state).toBe('not_started');
    expect(next).not.toBe(d);
  });
});

describe('businessDate / monthKey', () => {
  it('formats YYYY-MM-DD from local parts with zero padding', () => {
    expect(businessDate(new Date(2026, 9, 12))).toBe('2026-10-12');
    expect(businessDate(new Date(2026, 0, 5))).toBe('2026-01-05');
    expect(businessDate(new Date(2026, 11, 31))).toBe('2026-12-31');
  });

  it('formats YYYY-MM month keys', () => {
    expect(monthKey(new Date(2026, 9, 1))).toBe('2026-10');
    expect(monthKey(new Date(2026, 0, 28))).toBe('2026-01');
    expect(monthKey(new Date(2025, 11, 15))).toBe('2025-12');
  });
});
