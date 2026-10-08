import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  RefreshCw,
  ChevronLeft,
  ChevronRight,
  CalendarCheck,
  Clock,
  Play,
  Coffee,
  Square,
  CheckCircle2,
  ClipboardList,
  Info,
} from 'lucide-react';
import { PrimaryButton, SecondaryButton } from '../../components/common/Buttons';
import { ErrorState, LoadingState } from '../../components/common/FeedbackStates';
import { errorMessage } from '../../api/client';
import {
  AttendanceMonth,
  LEAVE_TYPE_LABELS,
  REQUEST_STATUS_LABELS,
  WorkdayAction,
  businessDate,
  createDayOffRequestApi,
  emptyWorkday,
  endDayApi,
  getMonthApi,
  getWorkdayApi,
  isNotImplemented,
  monthKey,
  nextWorkdayState,
  requestCoversDate,
  requestTypeLabel,
  resumeApi,
  startBreakApi,
  startDayApi,
} from '../../api/attendance';
import {
  AttendanceDayStatus,
  LeaveType,
  RequestStatus,
  RequestType,
  Workday,
  WorkdayState,
} from '../../types';

// ---------------------------------------------------------------------------
// Display metadata
// ---------------------------------------------------------------------------

const STATE_CHIP: Record<WorkdayState, { label: string; cls: string }> = {
  not_started: {
    label: 'Not Started',
    cls: 'bg-[#F0F2F1] text-[#667174] border-[#E4E8E6]',
  },
  working: {
    label: 'Working',
    cls: 'bg-[#E8F7ED] text-[#278B46] border-[#BBECCC]',
  },
  on_break: {
    label: 'On Break',
    cls: 'bg-[#F5DEAB]/40 text-[#B87C10] border-[#F5DEAB]',
  },
  completed: {
    label: 'Day Completed',
    cls: 'bg-[#E8F7ED] text-[#278B46] border-[#BBECCC]',
  },
};

const DAY_STATUS_META: Record<
  AttendanceDayStatus,
  { label: string; dot: string; cell: string }
> = {
  present: {
    label: 'Present',
    dot: 'bg-[#33B059]',
    cell: 'bg-[#E8F7ED] text-[#278B46]',
  },
  week_off: {
    label: 'Week Off',
    dot: 'bg-[#8D999C]',
    cell: 'bg-[#F0F2F1] text-[#667174]',
  },
  leave: {
    label: 'Leave',
    dot: 'bg-[#2B5DD8]',
    cell: 'bg-[#EEF3FF] text-[#2B5DD8]',
  },
  absent: {
    label: 'Absent',
    dot: 'bg-[#D9534F]',
    cell: 'bg-[#FCEBEA] text-[#D9534F]',
  },
};

const LEAVE_TYPES = Object.keys(LEAVE_TYPE_LABELS) as LeaveType[];

/** Status chip styling for the requests table — same palette as
 *  STATE_CHIP / StatusBadge. */
const REQUEST_STATUS_CHIP: Record<RequestStatus, string> = {
  pending: 'bg-[#FDF6E8] text-[#B87C10] border-[#F5DEAB]',
  approved: 'bg-[#E8F7ED] text-[#278B46] border-[#BBECCC]',
  rejected: 'bg-[#FCEBEA] text-[#D9534F] border-[#F8C8C6]',
  cancelled: 'bg-[#F5F5F5] text-[#8D999C] border-[#E4E8E6]',
};

const WEEKDAY_HEADERS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

/** "12 October 2026" — day-first regardless of device locale. */
const formatDateLong = (dateStr: string): string => {
  const [y, m, d] = dateStr.split('-').map(Number);
  return `${d} ${MONTH_NAMES[m - 1]} ${y}`;
};

const weekdayName = (dateStr: string): string => {
  const [y, m, d] = dateStr.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString([], { weekday: 'long' });
};

/** "20/10/2026" — DD/MM/YYYY regardless of device locale. */
const formatDateShort = (dateStr: string): string => {
  const [y, m, d] = dateStr.split('-');
  return `${d}/${m}/${y}`;
};

/** Native date input with a forced DD/MM/YYYY display — the input is
 * invisible but still opens the system picker on tap. */
const DateField: React.FC<{
  value: string;
  min?: string;
  onChange: (v: string) => void;
}> = ({ value, min, onChange }) => (
  <div className="relative">
    <input
      type="date"
      value={value}
      min={min}
      onChange={(e) => e.target.value && onChange(e.target.value)}
      className="absolute inset-0 w-full opacity-0"
      aria-label="Select date"
    />
    <div className="w-full p-2.5 rounded-xl border border-[#E4E8E6] bg-[#F7F8F6] text-xs text-[#20292C] pointer-events-none">
      {value ? formatDateShort(value) : 'DD/MM/YYYY'}
    </div>
  </div>
);

const formatTime = (ts: string): string =>
  new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

// ---------------------------------------------------------------------------
// Screen
// ---------------------------------------------------------------------------

export const AttendanceScreen: React.FC = () => {
  // Workday card state
  const [workday, setWorkday] = useState<Workday | null>(null);
  const [synced, setSynced] = useState<boolean>(true);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<WorkdayAction | null>(null);

  // Calendar state
  const [cursor, setCursor] = useState<Date>(() => {
    const d = new Date();
    return new Date(d.getFullYear(), d.getMonth(), 1);
  });
  const [monthData, setMonthData] = useState<AttendanceMonth>({ days: [], requests: [] });
  const [monthLoading, setMonthLoading] = useState<boolean>(false);
  const [monthError, setMonthError] = useState<string | null>(null);
  const monthCache = useRef<Map<string, AttendanceMonth>>(new Map());

  // Leave / week-off request bottom sheet
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [reqType, setReqType] = useState<RequestType>('leave');
  const [reqLeaveType, setReqLeaveType] = useState<LeaveType>('casual_leave');
  const [reqToDate, setReqToDate] = useState<string>('');
  const [reqReason, setReqReason] = useState<string>('');
  const [reqError, setReqError] = useState<string | null>(null);
  const [reqSubmitting, setReqSubmitting] = useState<boolean>(false);

  const todayStr = businessDate();

  const loadWorkday = useCallback(async (isRefresh = false) => {
    try {
      if (isRefresh) setRefreshing(true);
      else setLoading(true);
      setError(null);

      const w = await getWorkdayApi();
      setWorkday(w ?? emptyWorkday(businessDate()));
      setSynced(true);
    } catch (err: unknown) {
      if (isNotImplemented(err)) {
        // Attendance router not registered yet — local-only mode.
        setWorkday(emptyWorkday(businessDate()));
        setSynced(false);
      } else {
        setError(errorMessage(err, 'Unable to load your attendance.'));
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  const loadMonth = useCallback(async (key: string, force = false) => {
    if (!force) {
      const cached = monthCache.current.get(key);
      if (cached) {
        setMonthData(cached);
        setMonthError(null);
        return;
      }
    }
    setMonthLoading(true);
    setMonthError(null);
    try {
      const data = await getMonthApi(key);
      monthCache.current.set(key, data);
      setMonthData(data);
    } catch (err: unknown) {
      if (isNotImplemented(err)) {
        // Service missing — grid still renders with today highlighted.
        const empty: AttendanceMonth = { days: [], requests: [] };
        monthCache.current.set(key, empty);
        setMonthData(empty);
      } else {
        setMonthData({ days: [], requests: [] });
        setMonthError(errorMessage(err, 'Unable to load this month.'));
      }
    } finally {
      setMonthLoading(false);
    }
  }, []);

  useEffect(() => {
    loadWorkday();
  }, [loadWorkday]);

  useEffect(() => {
    loadMonth(monthKey(cursor));
  }, [cursor, loadMonth]);

  const handleRefresh = () => {
    loadWorkday(true);
    loadMonth(monthKey(cursor), true);
  };

  // -------------------------------------------------------------------------
  // Workday transitions — API first; on 404/501 keep the change on-device.
  // -------------------------------------------------------------------------

  const runAction = async (action: WorkdayAction) => {
    if (!workday || actionLoading) return;
    setActionError(null);
    setActionLoading(action);

    const call = {
      start: startDayApi,
      break: startBreakApi,
      resume: resumeApi,
      end: endDayApi,
    }[action];

    try {
      const updated = await call();
      if (updated) {
        setWorkday(updated);
        setSynced(true);
      } else {
        // Server accepted with an empty body — derive the new state locally.
        setWorkday(nextWorkdayState(workday, action));
      }
    } catch (err: unknown) {
      if (isNotImplemented(err)) {
        setWorkday(nextWorkdayState(workday, action));
        setSynced(false);
      } else {
        setActionError(
          errorMessage(err, 'Unable to update your work day. Please try again.')
        );
      }
    } finally {
      setActionLoading(null);
    }
  };

  // -------------------------------------------------------------------------
  // Calendar grid — Mon-first cells, nulls are leading blanks.
  // -------------------------------------------------------------------------

  const cells = useMemo<(string | null)[]>(() => {
    const y = cursor.getFullYear();
    const m = cursor.getMonth();
    const daysInMonth = new Date(y, m + 1, 0).getDate();
    const leading = (new Date(y, m, 1).getDay() + 6) % 7; // Mon = 0
    const out: (string | null)[] = Array(leading).fill(null);
    for (let d = 1; d <= daysInMonth; d++) {
      out.push(
        `${y}-${String(m + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`
      );
    }
    return out;
  }, [cursor]);

  const statusByDate = useMemo(
    () => new Map<string, AttendanceDayStatus>(monthData.days.map((d) => [d.date, d.status])),
    [monthData.days]
  );

  const monthLabel = `${MONTH_NAMES[cursor.getMonth()]} ${cursor.getFullYear()}`;

  const shiftMonth = (delta: number) =>
    setCursor((c) => new Date(c.getFullYear(), c.getMonth() + delta, 1));

  // -------------------------------------------------------------------------
  // Day-off request sheet
  // -------------------------------------------------------------------------

  const openDay = (date: string) => {
    if (date < todayStr) return; // past dates are not selectable
    setSelectedDate(date);
    setReqToDate(date); // single-day by default — widen via the To field
    setReqType('leave');
    setReqLeaveType('casual_leave');
    setReqReason('');
    setReqError(null);
  };

  const existingRequest = selectedDate
    ? monthData.requests.find(
        (r) =>
          requestCoversDate(r, selectedDate) &&
          (r.status === 'pending' || r.status === 'approved')
      )
    : undefined;

  const rejectedRequest = selectedDate
    ? monthData.requests.find(
        (r) => requestCoversDate(r, selectedDate) && r.status === 'rejected'
      )
    : undefined;

  const submitRequest = async () => {
    if (!selectedDate || reqSubmitting) return;
    const toDate = reqToDate || selectedDate;
    if (toDate < selectedDate) {
      setReqError('The To date cannot be before the From date.');
      return;
    }
    const reason = reqReason.trim();
    if (reqType === 'leave' && !reason) {
      setReqError('A reason is required for leave requests.');
      return;
    }
    setReqSubmitting(true);
    setReqError(null);
    try {
      const created = await createDayOffRequestApi({
        from_date: selectedDate,
        to_date: toDate,
        request_type: reqType,
        leave_type: reqType === 'leave' ? reqLeaveType : null,
        reason: reason || null,
      });
      const key = monthKey(cursor);
      if (created) {
        setMonthData((prev) => {
          // The request lands in the table below the grid — pending
          // requests never paint day markers.
          const next: AttendanceMonth = {
            requests: [...prev.requests.filter((r) => r.id !== created.id), created],
            days: prev.days,
          };
          monthCache.current.set(key, next);
          return next;
        });
      } else {
        // Empty-body success — drop the cache so the next visit refetches
        // rather than fabricating a pending record.
        monthCache.current.delete(key);
      }
      setSelectedDate(null);
    } catch (err: unknown) {
      if (isNotImplemented(err)) {
        setReqError("Requests aren't enabled yet");
      } else {
        setReqError(errorMessage(err, 'Unable to submit the request.'));
      }
    } finally {
      setReqSubmitting(false);
    }
  };

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  const chip = workday ? STATE_CHIP[workday.state] : STATE_CHIP.not_started;

  const timeRows: { label: string; at: string }[] = workday
    ? (
        [
          { label: 'Started', at: workday.started_at },
          { label: 'Break', at: workday.break_started_at },
          { label: 'Ended', at: workday.ended_at },
        ] as { label: string; at: string | null }[]
      ).filter((r): r is { label: string; at: string } => r.at !== null)
    : [];

  return (
    <div className="flex-1 flex flex-col bg-[#F7F8F6] overflow-y-auto">
      {/* Sticky Top Header */}
      <div className="bg-white border-b border-[#E4E8E6] px-5 pt-4 pb-3.5 sticky top-0 z-20 shadow-[0_1px_3px_rgba(0,0,0,0.02)]">
        <div className="flex items-center justify-between gap-3">
          <div>
            <span className="text-xs font-semibold text-[#667174] uppercase tracking-wider block">
              Property Operations
            </span>
            <h1 className="text-2xl font-bold tracking-tight text-[#20292C] font-['Space_Grotesk']">
              Attendance
            </h1>
            <p className="text-xs text-[#8D999C] mt-0.5">
              Track your work day and attendance
            </p>
          </div>

          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="p-2 rounded-xl border border-[#E4E8E6] bg-[#F7F8F6] text-[#20292C] hover:bg-[#EFEFEF] transition-all"
            aria-label="Refresh attendance"
          >
            <RefreshCw
              className={`w-4 h-4 ${refreshing ? 'animate-spin text-[#33B059]' : 'text-[#667174]'}`}
            />
          </button>
        </div>
      </div>

      <div className="flex-1 p-4">
        {loading ? (
          <LoadingState message="Loading your attendance..." />
        ) : error ? (
          <ErrorState message={error} onRetry={() => loadWorkday(false)} />
        ) : workday ? (
          <div className="space-y-4 pb-8">
            {/* Workday Card */}
            <div className="bg-white rounded-2xl p-4 border border-[#E4E8E6] shadow-sm space-y-3">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <Clock className="w-4 h-4 text-[#33B059]" />
                  <h3 className="text-xs font-bold text-[#20292C] uppercase tracking-wider font-['Space_Grotesk']">
                    Today's Work Day
                  </h3>
                </div>
                <span
                  className={`text-[11px] font-bold px-2.5 py-0.5 rounded-full border ${chip.cls}`}
                >
                  {chip.label}
                </span>
              </div>

              <p className="text-xs text-[#667174]">
                {weekdayName(workday.date)} · {formatDateLong(workday.date)}
              </p>

              {timeRows.length > 0 && (
                <div className="divide-y divide-[#F0F2F1] text-xs border-t border-[#F0F2F1]">
                  {timeRows.map((r) => (
                    <div
                      key={r.label}
                      className="py-2 flex items-center justify-between"
                    >
                      <span className="text-[#8D999C]">{r.label}</span>
                      <span className="font-semibold text-[#20292C]">
                        {formatTime(r.at)}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {actionError && (
                <div className="p-3 bg-[#FCEBEA] text-xs text-[#D9534F] rounded-xl">
                  {actionError}
                </div>
              )}

              {!synced && (
                <div className="flex items-start gap-1.5 text-[11px] text-[#8D999C] leading-snug">
                  <Info className="w-3.5 h-3.5 mt-px flex-shrink-0" />
                  <span>
                    Attendance service isn't connected yet — changes are kept on
                    this device only.
                  </span>
                </div>
              )}

              {workday.state === 'completed' && (
                <div className="text-center py-1">
                  <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-[#278B46] bg-[#E8F7ED] px-4 py-2 rounded-full border border-[#BBECCC]">
                    <CheckCircle2 className="w-4 h-4" />
                    Day completed — see you tomorrow
                  </span>
                </div>
              )}

              {workday.state === 'not_started' ? (
                <PrimaryButton
                  onClick={() => runAction('start')}
                  loading={actionLoading === 'start'}
                  icon={<Play className="w-4 h-4" />}
                >
                  Start Day
                </PrimaryButton>
              ) : (
                <div className="flex gap-2">
                  <SecondaryButton
                    onClick={() =>
                      runAction(workday.state === 'on_break' ? 'resume' : 'break')
                    }
                    disabled={
                      workday.state !== 'working' && workday.state !== 'on_break'
                    }
                    loading={actionLoading === 'break' || actionLoading === 'resume'}
                    icon={
                      workday.state === 'on_break' ? (
                        <Play className="w-4 h-4" />
                      ) : (
                        <Coffee className="w-4 h-4" />
                      )
                    }
                  >
                    {workday.state === 'on_break' ? 'Resume' : 'Break'}
                  </SecondaryButton>
                  <PrimaryButton
                    onClick={() => runAction('end')}
                    disabled={workday.state !== 'working'}
                    loading={actionLoading === 'end'}
                    icon={<Square className="w-4 h-4" />}
                  >
                    End Day
                  </PrimaryButton>
                </div>
              )}
            </div>

            {/* Calendar Card */}
            <div className="bg-white rounded-2xl p-4 border border-[#E4E8E6] shadow-sm">
              <div className="flex items-center justify-between gap-2 mb-3">
                <div className="flex items-center gap-2">
                  <CalendarCheck className="w-4 h-4 text-[#33B059]" />
                  <h3 className="text-xs font-bold text-[#20292C] uppercase tracking-wider font-['Space_Grotesk']">
                    Your Attendance
                  </h3>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => shiftMonth(-1)}
                    aria-label="Previous month"
                    className="p-1.5 rounded-lg border border-[#E4E8E6] text-[#667174] hover:bg-[#F7F8F6] active:bg-[#EFEFEF] transition-colors"
                  >
                    <ChevronLeft className="w-4 h-4" />
                  </button>
                  <span className="text-xs font-semibold text-[#20292C] min-w-[110px] text-center font-['Space_Grotesk']">
                    {monthLabel}
                  </span>
                  <button
                    onClick={() => shiftMonth(1)}
                    aria-label="Next month"
                    className="p-1.5 rounded-lg border border-[#E4E8E6] text-[#667174] hover:bg-[#F7F8F6] active:bg-[#EFEFEF] transition-colors"
                  >
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-7 gap-1 mb-1">
                {WEEKDAY_HEADERS.map((d) => (
                  <span
                    key={d}
                    className="text-center text-[10px] font-bold text-[#8D999C] uppercase tracking-wider"
                  >
                    {d}
                  </span>
                ))}
              </div>

              <div
                className={`grid grid-cols-7 gap-1 transition-opacity ${
                  monthLoading ? 'opacity-50 animate-pulse' : ''
                }`}
              >
                {cells.map((date, i) => {
                  if (date === null) return <div key={`blank-${i}`} />;
                  const dayNum = Number(date.split('-')[2]);
                  const status = statusByDate.get(date);
                  const meta = status ? DAY_STATUS_META[status] : null;
                  const isToday = date === todayStr;
                  const isPast = date < todayStr;

                  return (
                    <button
                      key={date}
                      type="button"
                      disabled={isPast}
                      onClick={() => openDay(date)}
                      aria-label={`${formatDateLong(date)}${meta ? ` — ${meta.label}` : ''}`}
                      className={`aspect-square rounded-xl flex flex-col items-center justify-center text-xs relative select-none transition-all ${
                        isToday
                          ? 'bg-[#33B059] text-white font-bold shadow-sm'
                          : `${meta ? meta.cell : 'text-[#20292C]'} ${
                              isPast
                                ? 'opacity-45 cursor-default'
                                : 'cursor-pointer hover:bg-[#F0F2F1] active:scale-95'
                            }`
                      }`}
                    >
                      <span>{dayNum}</span>
                      {meta && (
                        <span
                          className={`w-1.5 h-1.5 rounded-full mt-0.5 ${
                            isToday ? 'bg-white' : meta.dot
                          }`}
                        />
                      )}
                    </button>
                  );
                })}
              </div>

              {monthError && (
                <div className="p-3 mt-3 bg-[#FCEBEA] text-xs text-[#D9534F] rounded-xl">
                  {monthError}
                </div>
              )}

              {!monthError && !monthLoading && monthData.days.length === 0 && (
                <p className="text-[11px] text-[#8D999C] mt-3 text-center">
                  No attendance records yet.
                </p>
              )}

              {/* Legend — real day statuses only; requests are listed
                  in the table below, never painted on the grid. */}
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 mt-3 pt-3 border-t border-[#F0F2F1]">
                {(
                  ['present', 'week_off', 'leave', 'absent'] as const
                ).map((s) => (
                  <span
                    key={s}
                    className="inline-flex items-center gap-1 text-[10px] font-medium text-[#667174]"
                  >
                    <span
                      className={`w-1.5 h-1.5 rounded-full ${DAY_STATUS_META[s].dot}`}
                    />
                    {DAY_STATUS_META[s].label}
                  </span>
                ))}
              </div>
            </div>

            {/* Requests — the month's filings as a table (same calendar
                response; pending items live here, not on the grid). */}
            <div className="bg-white rounded-2xl p-4 border border-[#E4E8E6] shadow-sm">
              <div className="flex items-center gap-2 mb-3">
                <ClipboardList className="w-4 h-4 text-[#33B059]" />
                <h3 className="text-xs font-bold text-[#20292C] uppercase tracking-wider font-['Space_Grotesk']">
                  Requests
                </h3>
              </div>

              {monthData.requests.length === 0 ? (
                <p className="text-[11px] text-[#8D999C] text-center py-2">
                  No requests this month.
                </p>
              ) : (
                <div className="overflow-x-auto -mx-1 px-1">
                  <table className="w-full text-[11px] leading-snug">
                    <thead>
                      <tr className="text-left text-[10px] font-bold text-[#8D999C] uppercase tracking-wider border-b border-[#F0F2F1]">
                        <th className="py-1.5 pr-2 font-bold">From</th>
                        <th className="py-1.5 pr-2 font-bold">To</th>
                        <th className="py-1.5 pr-2 font-bold">Type</th>
                        <th className="py-1.5 pr-2 font-bold text-center">Days</th>
                        <th className="py-1.5 pr-2 font-bold">Reason</th>
                        <th className="py-1.5 font-bold text-right">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#F0F2F1]">
                      {monthData.requests.map((r) => (
                        <tr key={r.id} className="text-[#20292C]">
                          <td className="py-2 pr-2 whitespace-nowrap font-medium">
                            {formatDateShort(r.from_date)}
                          </td>
                          <td className="py-2 pr-2 whitespace-nowrap font-medium">
                            {formatDateShort(r.to_date)}
                          </td>
                          <td className="py-2 pr-2 whitespace-nowrap">
                            {requestTypeLabel(r)}
                          </td>
                          <td className="py-2 pr-2 text-center font-semibold">
                            {r.requested_days}
                          </td>
                          <td
                            className="py-2 pr-2 max-w-[90px] truncate text-[#667174]"
                            title={r.reason ?? undefined}
                          >
                            {r.reason || '—'}
                          </td>
                          <td className="py-2 text-right">
                            <span
                              className={`inline-block text-[10px] font-bold px-2 py-0.5 rounded-full border whitespace-nowrap ${REQUEST_STATUS_CHIP[r.status]}`}
                            >
                              {REQUEST_STATUS_LABELS[r.status]}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        ) : null}
      </div>

      {/* Day Detail / Leave Request Sheet */}
      {selectedDate && (
        <div
          className="fixed inset-0 z-40 flex items-end justify-center bg-black/40"
          onClick={() => setSelectedDate(null)}
        >
          <div
            className="w-full max-w-[420px] bg-white rounded-t-3xl p-5 pb-8 space-y-3"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="w-10 h-1 bg-[#E4E8E6] rounded-full mx-auto mb-1" />
            <h4 className="text-sm font-bold text-[#20292C] font-['Space_Grotesk']">
              {formatDateLong(selectedDate)}
            </h4>
            <p className="text-[11px] text-[#8D999C] -mt-1">
              Request leave or a week off starting this date
            </p>

            {existingRequest ? (
              <div className="rounded-xl border border-[#E4E8E6] bg-[#F7F8F6] p-3.5 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-semibold text-[#20292C]">
                    {requestTypeLabel(existingRequest)} request
                  </span>
                  <span
                    className={`text-[11px] font-bold px-2.5 py-0.5 rounded-full border ${REQUEST_STATUS_CHIP[existingRequest.status]}`}
                  >
                    {REQUEST_STATUS_LABELS[existingRequest.status]}
                  </span>
                </div>
                <p className="text-[11px] text-[#667174] leading-snug">
                  {formatDateLong(existingRequest.from_date)}
                  {existingRequest.to_date !== existingRequest.from_date &&
                    ` — ${formatDateLong(existingRequest.to_date)}`}{' '}
                  · {existingRequest.requested_days}{' '}
                  {existingRequest.requested_days === 1 ? 'day' : 'days'}
                </p>
                {existingRequest.reason && (
                  <p className="text-[11px] text-[#667174] leading-snug">
                    {existingRequest.reason}
                  </p>
                )}
                <SecondaryButton
                  size="sm"
                  onClick={() => setSelectedDate(null)}
                >
                  Close
                </SecondaryButton>
              </div>
            ) : (
              <>
                {rejectedRequest && (
                  <div className="p-3 bg-[#FCEBEA]/60 text-[11px] text-[#D9534F] rounded-xl">
                    A previous request covering this date was rejected — you
                    can submit a new one.
                  </div>
                )}

                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="block text-[10px] font-bold text-[#8D999C] uppercase tracking-wider mb-1">
                      From
                    </label>
                    <DateField
                      value={selectedDate}
                      min={todayStr}
                      onChange={(v) => {
                        setSelectedDate(v);
                        if (reqToDate < v) setReqToDate(v);
                      }}
                    />
                  </div>
                  <div>
                    <label className="block text-[10px] font-bold text-[#8D999C] uppercase tracking-wider mb-1">
                      To
                    </label>
                    <DateField
                      value={reqToDate || selectedDate}
                      min={selectedDate}
                      onChange={setReqToDate}
                    />
                  </div>
                </div>

                <label className="block text-xs font-bold text-[#20292C] uppercase tracking-wider font-['Space_Grotesk']">
                  Type
                </label>
                <div className="grid grid-cols-2 gap-2">
                  {(['leave', 'week_off'] as const).map((t) => (
                    <button
                      key={t}
                      type="button"
                      onClick={() => setReqType(t)}
                      className={`p-3 rounded-xl border text-xs font-semibold transition-all ${
                        reqType === t
                          ? 'border-[#33B059] bg-[#E8F7ED] text-[#278B46]'
                          : 'border-[#E4E8E6] text-[#667174] hover:bg-[#F7F8F6]'
                      }`}
                    >
                      {t === 'leave' ? 'Leave' : 'Week Off'}
                    </button>
                  ))}
                </div>

                {reqType === 'leave' && (
                  <div>
                    <label className="block text-xs font-bold text-[#20292C] uppercase tracking-wider mb-1.5 font-['Space_Grotesk']">
                      Leave Type
                    </label>
                    <div className="flex flex-wrap gap-1.5">
                      {LEAVE_TYPES.map((t) => (
                        <button
                          key={t}
                          type="button"
                          onClick={() => setReqLeaveType(t)}
                          className={`px-3 py-2 rounded-xl border text-[11px] font-semibold transition-all ${
                            reqLeaveType === t
                              ? 'border-[#33B059] bg-[#E8F7ED] text-[#278B46]'
                              : 'border-[#E4E8E6] text-[#667174] hover:bg-[#F7F8F6]'
                          }`}
                        >
                          {LEAVE_TYPE_LABELS[t]}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                <div>
                  <label className="block text-xs font-bold text-[#20292C] uppercase tracking-wider mb-1.5 font-['Space_Grotesk']">
                    {reqType === 'leave'
                      ? 'Reason (Required)'
                      : 'Reason (Optional)'}
                  </label>
                  <textarea
                    value={reqReason}
                    onChange={(e) => setReqReason(e.target.value)}
                    placeholder="Add a note for your supervisor..."
                    rows={2}
                    className="w-full p-3 rounded-xl border border-[#E4E8E6] bg-[#F7F8F6] text-xs text-[#20292C] placeholder-[#8D999C] focus:bg-white focus:outline-none focus:border-[#33B059]"
                  />
                </div>

                {reqError && (
                  <div className="p-3 bg-[#FCEBEA] text-xs text-[#D9534F] rounded-xl">
                    {reqError}
                  </div>
                )}

                <div className="flex gap-2.5 pt-1">
                  <SecondaryButton onClick={() => setSelectedDate(null)}>
                    Cancel
                  </SecondaryButton>
                  <PrimaryButton
                    onClick={submitRequest}
                    loading={reqSubmitting}
                  >
                    Submit Request
                  </PrimaryButton>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
