/**
 * My Shift API — contract over GET /attendance/shift.
 *
 * The shift schedule is written by the Super Admin / Property Manager
 * apps into the shared shifts + employee_shift_assignments tables; the
 * employee backend resolves the assignment in force on today's IST
 * operational day. This surface is read-only — employees never edit
 * their own schedule.
 *
 * Times arrive as IST wall-clock 'HH:MM' and are rendered verbatim with
 * an IST marker — converting them to device timezone would display a
 * different window than the one admins scheduled.
 *
 * Endpoint:
 *   GET /attendance/shift → MyShiftWire { status, shift|null, date, timezone }
 */

import { apiClient } from './client';
import { isNotImplemented } from './attendance';
import { MyShiftWire, AssignedShiftWire } from './wire';
import { AssignedShift, MyShift, MyShiftStatus } from '../types';

// ---------------------------------------------------------------------------
// Normalizer — wire → display
// ---------------------------------------------------------------------------

const mapAssignedShift = (s: AssignedShiftWire): AssignedShift => ({
  shift_uid: s.shift_uid,
  shift_name: s.shift_name,
  start_time: s.start_time,
  end_time: s.end_time,
  overnight: s.overnight,
  working_days: s.working_days,
  is_working_today: s.is_working_today,
  effective_from: s.effective_from,
  effective_until: s.effective_until,
});

export const mapMyShift = (w: MyShiftWire): MyShift => ({
  status: w.status,
  shift: w.shift ? mapAssignedShift(w.shift) : null,
  date: w.date,
  timezone: w.timezone,
});

// ---------------------------------------------------------------------------
// Display helpers — pure, unit-tested
// ---------------------------------------------------------------------------

export const MY_SHIFT_STATUS_LABELS: Record<MyShiftStatus, string> = {
  scheduled: 'Scheduled',
  inactive: 'Inactive',
  not_assigned: 'No shift assigned',
};

/** 'HH:MM' → '9:00 AM' / '6:00 PM' / '10:00 PM'. Malformed → raw string. */
export const formatShiftTime = (hhmm: string): string => {
  const m = /^(\d{1,2}):(\d{2})$/.exec(hhmm ?? '');
  if (!m) return hhmm;
  const h = Number(m[1]);
  const suffix = h < 12 ? 'AM' : 'PM';
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}:${m[2]} ${suffix}`;
};

const DAY_NAMES = [
  'Monday', 'Tuesday', 'Wednesday', 'Thursday',
  'Friday', 'Saturday', 'Sunday',
];

/** 7-char Monday-first bitmap → 'Every day' / 'Monday – Saturday' /
 *  'Monday, Wednesday, Friday' / 'Saturdays'. Malformed → '—'. */
export const workingDaysLabel = (bitmap: string): string => {
  if (!bitmap || bitmap.length !== 7 || /[^01]/.test(bitmap)) return '—';
  const days = DAY_NAMES.filter((_, i) => bitmap[i] === '1');
  if (days.length === 0) return '—';
  if (days.length === 7) return 'Every day';
  if (days.length === 1) return `${days[0]}s`;
  const first = bitmap.indexOf('1');
  const last = bitmap.lastIndexOf('1');
  const contiguous = bitmap.slice(first, last + 1).indexOf('0') === -1;
  if (contiguous) return `${DAY_NAMES[first]} – ${DAY_NAMES[last]}`;
  return days.join(', ');
};

/** 'YYYY-MM-DD' op-day key → '1 October 2026'. Malformed → raw string. */
export const formatOpDate = (ymd: string): string => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(ymd ?? '');
  if (!m) return ymd;
  const MONTHS = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
  ];
  const month = Number(m[2]);
  if (month < 1 || month > 12) return ymd;
  return `${Number(m[3])} ${MONTHS[month - 1]} ${m[1]}`;
};

// ---------------------------------------------------------------------------
// Endpoint
// ---------------------------------------------------------------------------

/** GET /attendance/shift — the caller's assignment in force today.
 *  A 404/501 (older backend build) degrades to 'not_assigned' rather
 *  than surfacing an error in the profile. */
export async function getMyShiftApi(): Promise<MyShift> {
  try {
    const w = await apiClient<MyShiftWire | undefined>('/attendance/shift');
    if (!w) {
      return { status: 'not_assigned', shift: null, date: '', timezone: '' };
    }
    return mapMyShift(w);
  } catch (err) {
    if (isNotImplemented(err)) {
      return { status: 'not_assigned', shift: null, date: '', timezone: '' };
    }
    throw err;
  }
}
