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
import { subscribeRealtimeEvents } from '../../services/realtime';
import { useTranslation } from 'react-i18next';
import {
  AttendanceMonth,
  LEAVE_TYPE_LABELS,
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
  resumeApi,
  startBreakApi,
  startDayApi,
} from '../../api/attendance';
import {
  startLocationTracking,
  stopLocationTracking,
} from '../../services/locationTracker';
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

const STATE_CHIP: Record<WorkdayState, string> = {
  not_started: 'bg-[#F6F4F2] text-[#667085] border-[#E7E5E4]',
  working: 'bg-[#F7E9EE] text-[#0D1C42] border-[#EAD3DB]',
  on_break: 'bg-[#FDF3E2]/40 text-[#A56514] border-[#FDF3E2]',
  completed: 'bg-[#F7E9EE] text-[#0D1C42] border-[#EAD3DB]',
};

const DAY_STATUS_META: Record<AttendanceDayStatus, { dot: string; cell: string }> = {
  present: { dot: 'bg-[#16865B]', cell: 'bg-[#E3F3EC] text-[#0E6B47]' },
  week_off: { dot: 'bg-[#98A2B3]', cell: 'bg-[#F6F4F2] text-[#667085]' },
  leave: { dot: 'bg-[#3478D4]', cell: 'bg-[#EAF1FB] text-[#3478D4]' },
  absent: { dot: 'bg-[#D64545]', cell: 'bg-[#FAEBEB] text-[#D64545]' },
};

const LEAVE_TYPES = Object.keys(LEAVE_TYPE_LABELS) as LeaveType[];

/** Status chip styling for the requests table — same palette as
 *  STATE_CHIP / StatusBadge. */
const REQUEST_STATUS_CHIP: Record<RequestStatus, string> = {
  pending: 'bg-[#FDF6E8] text-[#A56514] border-[#FDF3E2]',
  approved: 'bg-[#F7E9EE] text-[#0D1C42] border-[#EAD3DB]',
  rejected: 'bg-[#FAEBEB] text-[#D64545] border-[#F0C8C8]',
  cancelled: 'bg-[#F5F5F5] text-[#98A2B3] border-[#E7E5E4]',
};

const MONTH_KEYS = [
  'jan', 'feb', 'mar', 'apr', 'may', 'jun',
  'jul', 'aug', 'sep', 'oct', 'nov', 'dec',
] as const;

const WEEKDAY_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const;
const WEEKDAY_NAME_KEYS = [
  'sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday',
] as const;

type TFn = (key: string) => string;

/** "12 October 2026" — day-first regardless of device locale. */
const formatDateLong = (dateStr: string, t: TFn): string => {
  const [y, m, d] = dateStr.split('-').map(Number);
  return `${d} ${t(`attendance.months.${MONTH_KEYS[m - 1]}`)} ${y}`;
};

const weekdayName = (dateStr: string, t: TFn): string => {
  const [y, m, d] = dateStr.split('-').map(Number);
  const day = new Date(y, m - 1, d).getDay();
  return t(`attendance.weekdayNames.${WEEKDAY_NAME_KEYS[day]}`);
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
  ariaLabel: string;
  onChange: (v: string) => void;
}> = ({ value, min, ariaLabel, onChange }) => (
  <div className="relative">
    <input
      type="date"
      value={value}
      min={min}
      onChange={(e) => e.target.value && onChange(e.target.value)}
      className="absolute inset-0 w-full opacity-0"
      aria-label={ariaLabel}
    />
    <div className="w-full p-2.5 rounded-xl border border-[#E7E5E4] bg-[#FFFCFA] text-xs text-[#0D1C42] pointer-events-none">
      {value ? formatDateShort(value) : 'DD/MM/YYYY'}
    </div>
  </div>
);

const requestTypeLabelT = (
  r: Pick<import('../../types').DayOffRequest, 'request_type' | 'leave_type'>,
  t: TFn
): string =>
  r.request_type === 'week_off'
    ? t('attendance.weekOff')
    : t(`attendance.leaveTypeLabels.${r.leave_type ?? 'other'}`);

const formatTime = (ts: string): string =>
  new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

// ---------------------------------------------------------------------------
// Screen
// ---------------------------------------------------------------------------

export const AttendanceScreen: React.FC = () => {
  const { t } = useTranslation();
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
        setError(errorMessage(err, t('attendance.loadError')));
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
        setMonthError(errorMessage(err, t('attendance.monthLoadError')));
      }
    } finally {
      setMonthLoading(false);
    }
  }, []);

  useEffect(() => {
    loadWorkday();
  }, [loadWorkday]);

  // Realtime invalidation — attendance events refresh today's workday.
  useEffect(
    () =>
      subscribeRealtimeEvents(['attendance.'], () => loadWorkday(true)),
    [loadWorkday],
  );

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

    // Location tracking follows the workday: on while working, off on break/end.
    const tracking = {
      start: startLocationTracking,
      resume: startLocationTracking,
      break: stopLocationTracking,
      end: stopLocationTracking,
    }[action];

    try {
      const updated = await call();
      void tracking();
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
          errorMessage(err, t('attendance.actionError'))
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

  const monthLabel = `${t(`attendance.months.${MONTH_KEYS[cursor.getMonth()]}`)} ${cursor.getFullYear()}`;

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
      setReqError(t('attendance.toBeforeFromError'));
      return;
    }
    const reason = reqReason.trim();
    if (reqType === 'leave' && !reason) {
      setReqError(t('attendance.reasonRequiredError'));
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
        setReqError(t('attendance.notEnabled'));
      } else {
        setReqError(errorMessage(err, t('attendance.submitRequestError')));
      }
    } finally {
      setReqSubmitting(false);
    }
  };

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  const chipCls = workday ? STATE_CHIP[workday.state] : STATE_CHIP.not_started;

  const timeRows: { label: string; at: string }[] = workday
    ? (
        [
          { label: t('attendance.started'), at: workday.started_at },
          { label: t('attendance.breakLabel'), at: workday.break_started_at },
          { label: t('attendance.ended'), at: workday.ended_at },
        ] as { label: string; at: string | null }[]
      ).filter((r): r is { label: string; at: string } => r.at !== null)
    : [];

  return (
    <div className="flex-1 flex flex-col bg-[#FFFCFA] overflow-y-auto">
      {/* Sticky Top Header */}
      <div className="bg-white border-b border-[#E7E5E4] px-4 pt-3 pb-2.5 sticky top-0 z-20 shadow-[0_1px_3px_rgba(0,0,0,0.02)]">
        <div className="flex items-center justify-between gap-3">
          <div>
            <span className="text-[9px] font-semibold text-[#667085] uppercase tracking-wider block">
              {t('attendance.eyebrow')}
            </span>
            <h1 className="text-[16px] font-bold tracking-tight text-[#0D1C42] font-['Satoshi']">
              {t('attendance.title')}
            </h1>
            <p className="text-xs text-[#98A2B3] mt-0.5">
              {t('attendance.subtitle')}
            </p>
          </div>

          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="p-2 rounded-xl border border-[#E7E5E4] bg-[#FFFCFA] text-[#0D1C42] hover:bg-[#F6F4F2] transition-all"
            aria-label={t('attendance.refresh')}
          >
            <RefreshCw
              className={`w-4 h-4 ${refreshing ? 'animate-spin text-[#800020]' : 'text-[#667085]'}`}
            />
          </button>
        </div>
      </div>

      <div className="flex-1 p-4">
        {loading ? (
          <LoadingState message={t('attendance.loading')} />
        ) : error ? (
          <ErrorState message={error} onRetry={() => loadWorkday(false)} />
        ) : workday ? (
          <div className="space-y-4 pb-8">
            {/* Workday Card */}
            <div className="bg-white rounded-2xl p-4 border border-[#E7E5E4] shadow-sm space-y-3">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <Clock className="w-4 h-4 text-[#800020]" />
                  <h3 className="text-xs font-bold text-[#0D1C42] uppercase tracking-wider font-['Satoshi']">
                    {t('attendance.todayWorkday')}
                  </h3>
                </div>
                <span
                  className={`text-[9px] font-bold px-2.5 py-0.5 rounded-full border ${chipCls}`}
                >
                  {t(`attendance.state.${workday?.state ?? 'not_started'}`)}
                </span>
              </div>

              <p className="text-xs text-[#667085]">
                {weekdayName(workday.date, t)} · {formatDateLong(workday.date, t)}
              </p>

              {timeRows.length > 0 && (
                <div className="divide-y divide-[#F6F4F2] text-xs border-t border-[#F6F4F2]">
                  {timeRows.map((r) => (
                    <div
                      key={r.label}
                      className="py-2 flex items-center justify-between"
                    >
                      <span className="text-[#98A2B3]">{r.label}</span>
                      <span className="font-semibold text-[#0D1C42]">
                        {formatTime(r.at)}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {actionError && (
                <div className="p-3 bg-[#FAEBEB] text-xs text-[#D64545] rounded-xl">
                  {actionError}
                </div>
              )}

              {!synced && (
                <div className="flex items-start gap-1.5 text-[9px] text-[#98A2B3] leading-snug">
                  <Info className="w-3.5 h-3.5 mt-px flex-shrink-0" />
                  <span>
                    {t('attendance.offlineNote')}
                  </span>
                </div>
              )}

              {workday.state === 'completed' && (
                <div className="text-center py-1">
                  <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-[#0D1C42] bg-[#F7E9EE] px-4 py-2 rounded-full border border-[#EAD3DB]">
                    <CheckCircle2 className="w-4 h-4" />
                    {t('attendance.dayCompletedMsg')}
                  </span>
                </div>
              )}

              {workday.state === 'not_started' ? (
                <PrimaryButton
                  onClick={() => runAction('start')}
                  loading={actionLoading === 'start'}
                  icon={<Play className="w-4 h-4" />}
                >
                  {t('attendance.startDay')}
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
                    {workday.state === 'on_break' ? t('attendance.resume') : t('attendance.break')}
                  </SecondaryButton>
                  <PrimaryButton
                    onClick={() => runAction('end')}
                    disabled={workday.state !== 'working'}
                    loading={actionLoading === 'end'}
                    icon={<Square className="w-4 h-4" />}
                  >
                    {t('attendance.endDay')}
                  </PrimaryButton>
                </div>
              )}
            </div>

            {/* Calendar Card */}
            <div className="bg-white rounded-2xl p-4 border border-[#E7E5E4] shadow-sm">
              <div className="flex items-center justify-between gap-2 mb-3">
                <div className="flex items-center gap-2">
                  <CalendarCheck className="w-4 h-4 text-[#800020]" />
                  <h3 className="text-xs font-bold text-[#0D1C42] uppercase tracking-wider font-['Satoshi']">
                    {t('attendance.yourAttendance')}
                  </h3>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => shiftMonth(-1)}
                    aria-label={t('attendance.prevMonth')}
                    className="p-1.5 rounded-lg border border-[#E7E5E4] text-[#667085] hover:bg-[#FFFCFA] active:bg-[#F6F4F2] transition-colors"
                  >
                    <ChevronLeft className="w-4 h-4" />
                  </button>
                  <span className="text-xs font-semibold text-[#0D1C42] min-w-[110px] text-center font-['Satoshi']">
                    {monthLabel}
                  </span>
                  <button
                    onClick={() => shiftMonth(1)}
                    aria-label={t('attendance.nextMonth')}
                    className="p-1.5 rounded-lg border border-[#E7E5E4] text-[#667085] hover:bg-[#FFFCFA] active:bg-[#F6F4F2] transition-colors"
                  >
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-7 gap-1 mb-1">
                {WEEKDAY_KEYS.map((d) => (
                  <span
                    key={d}
                    className="text-center text-[9px] font-bold text-[#98A2B3] uppercase tracking-wider"
                  >
                    {t(`attendance.weekdays.${d}`)}
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
                      aria-label={`${formatDateLong(date, t)}${meta ? ` — ${status ? t(`attendance.dayStatus.${status}`) : ''}` : ''}`}
                      className={`aspect-square rounded-xl flex flex-col items-center justify-center text-xs relative select-none transition-all ${
                        isToday
                          ? 'bg-[#800020] text-white font-bold shadow-sm'
                          : `${meta ? meta.cell : 'text-[#0D1C42]'} ${
                              isPast
                                ? 'opacity-45 cursor-default'
                                : 'cursor-pointer hover:bg-[#F6F4F2] active:scale-95'
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
                <div className="p-3 mt-3 bg-[#FAEBEB] text-xs text-[#D64545] rounded-xl">
                  {monthError}
                </div>
              )}

              {!monthError && !monthLoading && monthData.days.length === 0 && (
                <p className="text-[9px] text-[#98A2B3] mt-3 text-center">
                  {t('attendance.noRecords')}
                </p>
              )}

              {/* Legend — real day statuses only; requests are listed
                  in the table below, never painted on the grid. */}
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 mt-3 pt-3 border-t border-[#F6F4F2]">
                {(
                  ['present', 'week_off', 'leave', 'absent'] as const
                ).map((s) => (
                  <span
                    key={s}
                    className="inline-flex items-center gap-1 text-[9px] font-medium text-[#667085]"
                  >
                    <span
                      className={`w-1.5 h-1.5 rounded-full ${DAY_STATUS_META[s].dot}`}
                    />
                    {t(`attendance.dayStatus.${s}`)}
                  </span>
                ))}
              </div>
            </div>

            {/* Requests — the month's filings as a table (same calendar
                response; pending items live here, not on the grid). */}
            <div className="bg-white rounded-2xl p-4 border border-[#E7E5E4] shadow-sm">
              <div className="flex items-center gap-2 mb-3">
                <ClipboardList className="w-4 h-4 text-[#800020]" />
                <h3 className="text-xs font-bold text-[#0D1C42] uppercase tracking-wider font-['Satoshi']">
                  {t('attendance.requests')}
                </h3>
              </div>

              {monthData.requests.length === 0 ? (
                <p className="text-[9px] text-[#98A2B3] text-center py-2">
                  {t('attendance.noRequests')}
                </p>
              ) : (
                <div className="overflow-x-auto -mx-1 px-1">
                  <table className="w-full text-[9px] leading-snug">
                    <thead>
                      <tr className="text-left text-[9px] font-bold text-[#98A2B3] uppercase tracking-wider border-b border-[#F6F4F2]">
                        <th className="py-1.5 pr-2 font-bold">{t('attendance.from')}</th>
                        <th className="py-1.5 pr-2 font-bold">{t('attendance.to')}</th>
                        <th className="py-1.5 pr-2 font-bold">{t('attendance.type')}</th>
                        <th className="py-1.5 pr-2 font-bold text-center">{t('attendance.days')}</th>
                        <th className="py-1.5 pr-2 font-bold">{t('attendance.reason')}</th>
                        <th className="py-1.5 font-bold text-right">{t('attendance.status')}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#F6F4F2]">
                      {monthData.requests.map((r) => (
                        <tr key={r.id} className="text-[#0D1C42]">
                          <td className="py-2 pr-2 whitespace-nowrap font-medium">
                            {formatDateShort(r.from_date)}
                          </td>
                          <td className="py-2 pr-2 whitespace-nowrap font-medium">
                            {formatDateShort(r.to_date)}
                          </td>
                          <td className="py-2 pr-2 whitespace-nowrap">
                            {requestTypeLabelT(r, t)}
                          </td>
                          <td className="py-2 pr-2 text-center font-semibold">
                            {r.requested_days}
                          </td>
                          <td
                            className="py-2 pr-2 max-w-[90px] truncate text-[#667085]"
                            title={r.reason ?? undefined}
                          >
                            {r.reason || '—'}
                          </td>
                          <td className="py-2 text-right">
                            <span
                              className={`inline-block text-[9px] font-bold px-2 py-0.5 rounded-full border whitespace-nowrap ${REQUEST_STATUS_CHIP[r.status]}`}
                            >
                              {t(`attendance.requestStatus.${r.status}`)}
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
            className="w-full max-w-[420px] bg-white rounded-t-3xl p-5 pb-[max(2rem,calc(env(safe-area-inset-bottom,0px)+1rem))] space-y-3"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="w-10 h-1 bg-[#E7E5E4] rounded-full mx-auto mb-1" />
            <h4 className="text-sm font-bold text-[#0D1C42] font-['Satoshi']">
              {formatDateLong(selectedDate, t)}
            </h4>
            <p className="text-[9px] text-[#98A2B3] -mt-1">
              {t('attendance.sheetSub')}
            </p>

            {existingRequest ? (
              <div className="rounded-xl border border-[#E7E5E4] bg-[#FFFCFA] p-3.5 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-semibold text-[#0D1C42]">
                    {requestTypeLabelT(existingRequest, t)} {t('attendance.requestSuffix')}
                  </span>
                  <span
                    className={`text-[9px] font-bold px-2.5 py-0.5 rounded-full border ${REQUEST_STATUS_CHIP[existingRequest.status]}`}
                  >
                    {t(`attendance.requestStatus.${existingRequest.status}`)}
                  </span>
                </div>
                <p className="text-[9px] text-[#667085] leading-snug">
                  {formatDateLong(existingRequest.from_date, t)}
                  {existingRequest.to_date !== existingRequest.from_date &&
                    ` — ${formatDateLong(existingRequest.to_date, t)}`}{' '}
                  · {existingRequest.requested_days}{' '}
                  {t(existingRequest.requested_days === 1 ? 'common.day' : 'common.days')}
                </p>
                {existingRequest.reason && (
                  <p className="text-[9px] text-[#667085] leading-snug">
                    {existingRequest.reason}
                  </p>
                )}
                <SecondaryButton
                  size="sm"
                  onClick={() => setSelectedDate(null)}
                >
                  {t('common.close')}
                </SecondaryButton>
              </div>
            ) : (
              <>
                {rejectedRequest && (
                  <div className="p-3 bg-[#FAEBEB]/60 text-[9px] text-[#D64545] rounded-xl">
                    {t('attendance.rejectedNote')}
                  </div>
                )}

                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="block text-[9px] font-bold text-[#98A2B3] uppercase tracking-wider mb-1">
                      {t('attendance.from')}
                    </label>
                    <DateField
                      value={selectedDate}
                      min={todayStr}
                      ariaLabel={t('common.selectDate')}
                      onChange={(v) => {
                        setSelectedDate(v);
                        if (reqToDate < v) setReqToDate(v);
                      }}
                    />
                  </div>
                  <div>
                    <label className="block text-[9px] font-bold text-[#98A2B3] uppercase tracking-wider mb-1">
                      {t('attendance.to')}
                    </label>
                    <DateField
                      value={reqToDate || selectedDate}
                      min={selectedDate}
                      ariaLabel={t('common.selectDate')}
                      onChange={setReqToDate}
                    />
                  </div>
                </div>

                <label className="block text-xs font-bold text-[#0D1C42] uppercase tracking-wider font-['Satoshi']">
                  {t('attendance.type')}
                </label>
                <div className="grid grid-cols-2 gap-2">
                  {(['leave', 'week_off'] as const).map((rt) => (
                    <button
                      key={rt}
                      type="button"
                      onClick={() => setReqType(rt)}
                      className={`p-3 rounded-xl border text-xs font-semibold transition-all ${
                        reqType === rt
                          ? 'border-[#800020] bg-[#F7E9EE] text-[#0D1C42]'
                          : 'border-[#E7E5E4] text-[#667085] hover:bg-[#FFFCFA]'
                      }`}
                    >
                      {rt === 'leave' ? t('attendance.leave') : t('attendance.weekOff')}
                    </button>
                  ))}
                </div>

                {reqType === 'leave' && (
                  <div>
                    <label className="block text-xs font-bold text-[#0D1C42] uppercase tracking-wider mb-1.5 font-['Satoshi']">
                      {t('attendance.leaveType')}
                    </label>
                    <div className="flex flex-wrap gap-1.5">
                      {LEAVE_TYPES.map((lt) => (
                        <button
                          key={lt}
                          type="button"
                          onClick={() => setReqLeaveType(lt)}
                          className={`px-3 py-2 rounded-xl border text-[9px] font-semibold transition-all ${
                            reqLeaveType === lt
                              ? 'border-[#800020] bg-[#F7E9EE] text-[#0D1C42]'
                              : 'border-[#E7E5E4] text-[#667085] hover:bg-[#FFFCFA]'
                          }`}
                        >
                          {t(`attendance.leaveTypeLabels.${lt}`)}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                <div>
                  <label className="block text-xs font-bold text-[#0D1C42] uppercase tracking-wider mb-1.5 font-['Satoshi']">
                    {reqType === 'leave'
                      ? t('attendance.reasonRequired')
                      : t('attendance.reasonOptional')}
                  </label>
                  <textarea
                    value={reqReason}
                    onChange={(e) => setReqReason(e.target.value)}
                    placeholder={t('attendance.reasonPlaceholder')}
                    rows={2}
                    className="w-full p-3 rounded-xl border border-[#E7E5E4] bg-[#FFFCFA] text-xs text-[#0D1C42] placeholder-[#98A2B3] focus:bg-white focus:outline-none focus:border-[#800020]"
                  />
                </div>

                {reqError && (
                  <div className="p-3 bg-[#FAEBEB] text-xs text-[#D64545] rounded-xl">
                    {reqError}
                  </div>
                )}

                <div className="flex gap-2.5 pt-1">
                  <SecondaryButton onClick={() => setSelectedDate(null)}>
                    {t('common.cancel')}
                  </SecondaryButton>
                  <PrimaryButton
                    onClick={submitRequest}
                    loading={reqSubmitting}
                  >
                    {t('attendance.submitRequest')}
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
