import { describe, it, expect } from 'vitest';
import {
  formatOpDate,
  formatShiftTime,
  mapMyShift,
  MY_SHIFT_STATUS_LABELS,
  workingDaysLabel,
} from '../shift';
import { MyShiftWire } from '../wire';

const shiftWire = (over: Record<string, unknown> = {}) => ({
  shift_uid: 's-1',
  shift_name: 'Day Shift',
  start_time: '09:00',
  end_time: '18:00',
  overnight: false,
  working_days: '1111111',
  is_working_today: true,
  effective_from: '2026-10-01',
  effective_until: null,
  ...over,
});

const wire = (over: Partial<MyShiftWire> = {}): MyShiftWire => ({
  status: 'scheduled',
  shift: shiftWire(),
  date: '2026-10-09',
  timezone: 'Asia/Kolkata',
  ...over,
});

describe('mapMyShift', () => {
  it('maps a scheduled assignment straight through', () => {
    const m = mapMyShift(wire());
    expect(m.status).toBe('scheduled');
    expect(m.shift?.shift_name).toBe('Day Shift');
    expect(m.shift?.overnight).toBe(false);
    expect(m.date).toBe('2026-10-09');
  });

  it('maps not_assigned / inactive with a null-or-present shift', () => {
    const none = mapMyShift(wire({ status: 'not_assigned', shift: null }));
    expect(none.shift).toBeNull();
    const inact = mapMyShift(wire({ status: 'inactive' }));
    expect(inact.status).toBe('inactive');
    expect(inact.shift).not.toBeNull();
  });
});

describe('formatShiftTime', () => {
  it('renders 12h times with AM/PM', () => {
    expect(formatShiftTime('09:00')).toBe('9:00 AM');
    expect(formatShiftTime('18:00')).toBe('6:00 PM');
    expect(formatShiftTime('22:30')).toBe('10:30 PM');
    expect(formatShiftTime('00:15')).toBe('12:15 AM');
    expect(formatShiftTime('12:00')).toBe('12:00 PM');
  });

  it('passes malformed input through unchanged', () => {
    expect(formatShiftTime('9am')).toBe('9am');
  });
});

describe('workingDaysLabel', () => {
  it('collapses the all-week bitmap', () => {
    expect(workingDaysLabel('1111111')).toBe('Every day');
  });

  it('renders contiguous ranges with an en-dash', () => {
    expect(workingDaysLabel('1111100')).toBe('Monday – Friday');
    expect(workingDaysLabel('1111110')).toBe('Monday – Saturday');
    expect(workingDaysLabel('0111110')).toBe('Tuesday – Saturday');
  });

  it('lists non-contiguous days', () => {
    expect(workingDaysLabel('1010100')).toBe('Monday, Wednesday, Friday');
  });

  it('pluralises a single weekly day', () => {
    expect(workingDaysLabel('0000001')).toBe('Sundays');
  });

  it('rejects malformed bitmaps safely', () => {
    expect(workingDaysLabel('111')).toBe('—');
    expect(workingDaysLabel('abcdefg')).toBe('—');
    expect(workingDaysLabel('0000000')).toBe('—');
  });
});

describe('formatOpDate', () => {
  it('renders op-day keys as long dates', () => {
    expect(formatOpDate('2026-10-01')).toBe('1 October 2026');
    expect(formatOpDate('2027-01-31')).toBe('31 January 2027');
  });
});

describe('status labels', () => {
  it('covers the full status vocabulary', () => {
    expect(MY_SHIFT_STATUS_LABELS.scheduled).toBe('Scheduled');
    expect(MY_SHIFT_STATUS_LABELS.inactive).toBe('Inactive');
    expect(MY_SHIFT_STATUS_LABELS.not_assigned).toBe('No shift assigned');
  });
});
