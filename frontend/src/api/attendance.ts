/**
 * Attendance API — contract over /attendance.
 *
 * Every call degrades gracefully: screens branch on isNotImplemented()
 * and keep local-only state instead of breaking.
 *
 * Endpoints (wire DTOs in src/api/wire.ts §Attendance):
 *   GET  /attendance/today                  → WorkdayWire
 *   POST /attendance/start                  → WorkdayWire
 *   POST /attendance/break                  → WorkdayWire
 *   POST /attendance/resume                 → WorkdayWire
 *   POST /attendance/end                    → WorkdayWire
 *   GET  /attendance/calendar?month=YYYY-MM → AttendanceMonthWire
 *   POST /attendance/requests               → AttendanceRequestWire
 *        body { from_date, to_date, request_type, leave_type?, reason? }
 *
 * Requests are inclusive DATE RANGES — the calendar ships the raw
 * [from_date..to_date] span in the same response; the screen lists them
 * in a table below the grid (no extra API calls). Only real
 * attendance_days paint day markers — pending requests never do.
 */

import { apiClient } from './client';
import {
  AttendanceDayWire,
  AttendanceMonthWire,
  AttendanceRequestWire,
  LeaveTypeWire,
  RequestTypeWire,
  WorkdayWire,
} from './wire';
import {
  AttendanceDay,
  DayOffRequest,
  LeaveType,
  RequestStatus,
  Workday,
} from '../types';

// ---------------------------------------------------------------------------
// Business dates — attendance keys are 'YYYY-MM-DD' built from LOCAL date
// parts. Never slice toISOString() (UTC): the backend compares against its
// IST wall-clock convention, and a UTC slice off-by-ones the calendar day
// around local midnight.
// ---------------------------------------------------------------------------

export const businessDate = (d: Date = new Date()): string =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(
    d.getDate()
  ).padStart(2, '0')}`;

/** 'YYYY-MM' key for a calendar month — matches the ?month= query param. */
export const monthKey = (d: Date): string =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;

// ---------------------------------------------------------------------------
// Error narrowing
// ---------------------------------------------------------------------------

/** True when the backend doesn't register the attendance router yet —
 *  screens fall back to device-local state on this. */
export const isNotImplemented = (err: unknown): boolean => {
  const status = (err as { status?: unknown } | null)?.status;
  return status === 404 || status === 501;
};

// ---------------------------------------------------------------------------
// Normalizers — wire → display
// ---------------------------------------------------------------------------

export const mapWorkday = (w: WorkdayWire): Workday => ({
  state: w.state,
  date: w.date,
  started_at: w.started_at ?? null,
  break_started_at: w.break_started_at ?? null,
  ended_at: w.ended_at ?? null,
});

export const mapAttendanceDay = (d: AttendanceDayWire): AttendanceDay => ({
  date: d.date,
  status: d.status,
});

export const mapDayOffRequest = (r: AttendanceRequestWire): DayOffRequest => ({
  id: r.request_uid,
  from_date: r.from_date,
  to_date: r.to_date,
  request_type: r.request_type,
  leave_type: r.leave_type ?? null,
  requested_days: r.requested_days,
  status: r.status,
  reason: r.reason ?? null,
  created_at: r.created_at,
});

// ---------------------------------------------------------------------------
// Request display labels — shared by the calendar table + the day sheet.
// ---------------------------------------------------------------------------

export const LEAVE_TYPE_LABELS: Record<LeaveType, string> = {
  casual_leave: 'Casual Leave',
  sick_leave: 'Sick Leave',
  paid_leave: 'Paid Leave',
  unpaid_leave: 'Unpaid Leave',
  other: 'Other',
};

/** Short label for a filed request — 'Casual Leave' / 'Week Off'. */
export const requestTypeLabel = (
  r: Pick<DayOffRequest, 'request_type' | 'leave_type'>
): string =>
  r.request_type === 'week_off'
    ? 'Week Off'
    : LEAVE_TYPE_LABELS[r.leave_type ?? 'other'];

/** Status vocabulary → display labels (pending reads as 'Requested'). */
export const REQUEST_STATUS_LABELS: Record<RequestStatus, string> = {
  pending: 'Requested',
  approved: 'Approved',
  rejected: 'Rejected',
  cancelled: 'Cancelled',
};

/** Inclusive-range cover check — 'YYYY-MM-DD' strings compare lexically. */
export const requestCoversDate = (
  r: Pick<DayOffRequest, 'from_date' | 'to_date'>,
  date: string
): boolean => r.from_date <= date && date <= r.to_date;

/** Every 'YYYY-MM-DD' in the inclusive [from..to] range — handy when a
 *  caller needs the per-date expansion of a request's span. */
export const coveredDates = (from: string, to: string): string[] => {
  const [fy, fm, fd] = from.split('-').map(Number);
  const [ty, tm, td] = to.split('-').map(Number);
  const out: string[] = [];
  const cur = new Date(fy, fm - 1, fd);
  const end = new Date(ty, tm - 1, td);
  while (cur <= end) {
    out.push(businessDate(cur));
    cur.setDate(cur.getDate() + 1);
  }
  return out;
};

// ---------------------------------------------------------------------------
// Workday state machine — pure transition used as the offline fallback and
// whenever a transition POST returns an empty (204-style) body. Invalid
// transitions are no-ops (the input is returned unchanged).
// ---------------------------------------------------------------------------

export type WorkdayAction = 'start' | 'break' | 'resume' | 'end';

export const emptyWorkday = (date: string): Workday => ({
  state: 'not_started',
  date,
  started_at: null,
  break_started_at: null,
  ended_at: null,
});

export const nextWorkdayState = (
  day: Workday,
  action: WorkdayAction,
  now?: string
): Workday => {
  const at = now ?? new Date().toISOString();
  switch (action) {
    case 'start':
      if (day.state !== 'not_started') return day;
      return { ...day, state: 'working', started_at: at };
    case 'break':
      if (day.state !== 'working') return day;
      return { ...day, state: 'on_break', break_started_at: at };
    case 'resume':
      if (day.state !== 'on_break') return day;
      return { ...day, state: 'working', break_started_at: null };
    case 'end':
      if (day.state !== 'working') return day;
      return { ...day, state: 'completed', ended_at: at };
  }
};

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------

/** GET /attendance/today — null body → caller substitutes emptyWorkday(). */
export async function getWorkdayApi(): Promise<Workday | null> {
  const w = await apiClient<WorkdayWire | undefined>('/attendance/today');
  return w ? mapWorkday(w) : null;
}

const postWorkday = async (path: string): Promise<Workday | null> => {
  const w = await apiClient<WorkdayWire | undefined>(path, { method: 'POST' });
  return w ? mapWorkday(w) : null;
};

export const startDayApi = (): Promise<Workday | null> =>
  postWorkday('/attendance/start');

export const startBreakApi = (): Promise<Workday | null> =>
  postWorkday('/attendance/break');

export const resumeApi = (): Promise<Workday | null> =>
  postWorkday('/attendance/resume');

export const endDayApi = (): Promise<Workday | null> =>
  postWorkday('/attendance/end');

export interface AttendanceMonth {
  days: AttendanceDay[];
  requests: DayOffRequest[];
}

/** GET /attendance/calendar?month=YYYY-MM — tolerates a bare-day-array body
 *  as well as the { days, requests } envelope. */
export async function getMonthApi(month: string): Promise<AttendanceMonth> {
  const res = await apiClient<
    AttendanceMonthWire | AttendanceDayWire[] | undefined
  >(`/attendance/calendar?month=${encodeURIComponent(month)}`);
  const days = Array.isArray(res) ? res : res?.days ?? [];
  const requests = Array.isArray(res) ? [] : res?.requests ?? [];
  return {
    days: days.map(mapAttendanceDay),
    requests: requests.map(mapDayOffRequest),
  };
}

/** POST /attendance/requests — null body → the screen invalidates its
 *  month cache rather than fabricating a pending record. */
export async function createDayOffRequestApi(payload: {
  from_date: string; // 'YYYY-MM-DD'
  to_date: string; // 'YYYY-MM-DD'
  request_type: RequestTypeWire;
  leave_type?: LeaveTypeWire | null;
  reason?: string | null;
}): Promise<DayOffRequest | null> {
  const r = await apiClient<AttendanceRequestWire | undefined>(
    '/attendance/requests',
    { method: 'POST', body: JSON.stringify(payload) }
  );
  return r ? mapDayOffRequest(r) : null;
}
