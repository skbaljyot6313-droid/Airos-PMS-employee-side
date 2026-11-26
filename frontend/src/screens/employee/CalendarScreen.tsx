import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  Clock,
  Coffee,
  LogIn,
  LogOut,
  PlayCircle,
  Plus,
  RefreshCw,
  Wrench,
} from 'lucide-react';
import { fetchWorkCalendarApi, WorkCalendarData } from '../../api/calendar';
import { fetchTasksApi } from '../../api/tasks';
import { teamApi, TeamDepartment } from '../../api/team';
import { getZonesCached } from '../../api/directory';
import { ZoneWire } from '../../api/wire';
import { useAuth } from '../../context/AuthContext';
import { AssignSheet } from './MyTeamScreen';
import {
  businessDate,
  isNotImplemented,
  requestCoversDate,
  requestTypeLabel,
  REQUEST_STATUS_LABELS,
} from '../../api/attendance';
import type { Task, Workday } from '../../types';

const pad = (n: number) => String(n).padStart(2, '0');
const isoDay = (d: Date) =>
  `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const parseDay = (d: string) => new Date(`${d}T00:00:00`);
const hm = (v?: string | null): string | null => (v ? v.slice(0, 5) : null);

const IST = 'Asia/Kolkata';
const dateFmt = new Intl.DateTimeFormat('en', {
  timeZone: IST,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
});
const timeFmt = new Intl.DateTimeFormat('en-GB', {
  timeZone: IST,
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

const istParts = (ts: string) => {
  const parts = dateFmt.formatToParts(new Date(ts));
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? '';
  return { year: get('year'), month: get('month'), day: get('day') };
};

const istDay = (ts?: string | null): string | null => {
  if (!ts) return null;
  try {
    const p = istParts(ts);
    return p.year && p.month && p.day ? `${p.year}-${p.month}-${p.day}` : null;
  } catch {
    return null;
  }
};

const istTime = (ts?: string | null): string | null => {
  if (!ts) return null;
  try {
    return timeFmt.format(new Date(ts));
  } catch {
    return null;
  }
};

const minutesFromHm = (v?: string | null): number | null => {
  if (!v) return null;
  const [h, m] = v.slice(0, 5).split(':').map(Number);
  return Number.isFinite(h) && Number.isFinite(m) ? h * 60 + m : null;
};

const istMinutes = (ts?: string | null): number | null => {
  const v = istTime(ts);
  return v ? minutesFromHm(v) : null;
};

const formatMinutes = (minutes: number): string => {
  const dayOffset = Math.floor(minutes / 1440);
  const within = ((minutes % 1440) + 1440) % 1440;
  const out = `${pad(Math.floor(within / 60))}:${pad(within % 60)}`;
  return dayOffset > 0 ? `${out} +${dayOffset}` : out;
};

/** The scheduled occurrence date — operational_date is authoritative for
 *  recurring work; scheduled_for falls back to an IST day key. */
const taskDay = (t: Task): string | null =>
  t.operational_date ??
  (t.scheduled_for ? istDay(t.scheduled_for) : null) ??
  t.due_date?.slice(0, 10) ??
  null;

const taskStartMinutes = (t: Task): number | null =>
  (t.scheduled_for ? istMinutes(t.scheduled_for) : null) ??
  minutesFromHm(t.start_time) ??
  minutesFromHm(t.due_time);

const taskEndMinutes = (t: Task, start: number | null): number | null => {
  const rawEnd = minutesFromHm(t.end_time);
  if (rawEnd != null) {
    return start != null && rawEnd <= start ? rawEnd + 1440 : rawEnd;
  }
  if (start != null && t.estimated_minutes != null) return start + t.estimated_minutes;
  return null;
};

/** 'HH:MM–HH:MM' display window when the schedule carries an end. */
const taskWindow = (t: Task): string | null => {
  const startM = taskStartMinutes(t);
  const start = t.scheduled_for
    ? istTime(t.scheduled_for)
    : hm(t.start_time) ?? hm(t.due_time);
  if (startM == null || !start) return null;
  const end = taskEndMinutes(t, startM);
  return end != null ? `${start}–${formatMinutes(end)}` : start;
};

const STATUS_LABEL: Record<string, string> = {
  pending: 'Scheduled',
  assigned: 'Scheduled',
  scheduled: 'Scheduled',
  in_progress: 'In Progress',
  completed: 'Completed',
  submitted: 'Submitted',
  overdue: 'Overdue',
  cancelled: 'Cancelled',
  reopened: 'Reopened',
};

const UPCOMING = new Set([
  'pending',
  'assigned',
  'in_progress',
  'reopened',
  'scheduled',
]);

const statusLabel = (task: Task, today: string): string => {
  const day = taskDay(task);
  if (UPCOMING.has(task.status) && day && day < today) return 'Overdue';
  return STATUS_LABEL[task.status] ?? task.status;
};

const statusDot = (task: Task, today: string): string => {
  const day = taskDay(task);
  if (task.kind === 'maintenance') return 'bg-[#790D16]';
  if (UPCOMING.has(task.status) && day && day < today) return 'bg-[#D64545]';
  switch (task.status) {
    case 'completed':
      return 'bg-[#16865B]';
    case 'submitted':
      return 'bg-[#F4BE38]';
    case 'in_progress':
      return 'bg-[#5C3FA8]';
    case 'overdue':
      return 'bg-[#D64545]';
    default:
      return 'bg-[#1B365D]';
  }
};

type TimelineKind =
  | 'status'
  | 'day-start'
  | 'day-end'
  | 'break'
  | 'scheduled'
  | 'activity';

type Tone = 'indigo' | 'green' | 'amber' | 'red' | 'purple' | 'slate';
type TimelineIcon =
  | 'clock'
  | 'login'
  | 'logout'
  | 'break'
  | 'scheduled'
  | 'started'
  | 'done'
  | 'warning';

interface TimelineEntry {
  id: string;
  kind: TimelineKind;
  label: string;
  title: string;
  detail?: string | null;
  time: string | null;
  endTime?: string | null;
  sort: number;
  tone: Tone;
  icon: TimelineIcon;
  task?: Task;
}

interface DayModel {
  scheduled: Task[];
  entries: TimelineEntry[];
  doneCount: number;
  breakCount: number;
  attendance: Workday | null;
}

const EMPTY_DATA: WorkCalendarData = { days: [], requests: [], tasks: [] };

const ALLOCATION_EVENTS = new Set([
  'allocated',
  'assigned',
  'auto_generated',
  'created',
  'reassigned',
  'scheduled',
]);
const START_EVENTS = new Set(['started', 'in_progress']);
const SUBMIT_EVENTS = new Set(['submitted']);
const DONE_EVENTS = new Set([
  'approved',
  'completed',
  'resolved',
  'closed',
  'admin_closed',
]);
const REOPEN_EVENTS = new Set([
  'reopened',
  'rejected',
  'disapproved',
  'redo_requested',
]);
const CANCEL_EVENTS = new Set(['cancelled', 'abandoned', 'released']);
const IGNORED_EVENTS = new Set([
  'commented',
  'location_recorded',
  'room_status_changed',
]);

const activityKind = (type: string): string | null => {
  if (IGNORED_EVENTS.has(type)) return null;
  if (ALLOCATION_EVENTS.has(type)) return 'allocated';
  if (START_EVENTS.has(type)) return 'started';
  if (SUBMIT_EVENTS.has(type)) return 'submitted';
  if (DONE_EVENTS.has(type)) return 'completed';
  if (REOPEN_EVENTS.has(type)) return 'reopened';
  if (CANCEL_EVENTS.has(type)) return 'cancelled';
  if (type === 'held') return 'onHold';
  if (type === 'resumed') return 'resumed';
  if (type === 'edited' || type === 'updated') return 'updated';
  return 'updated';
};

const activityMeta = (
  kind: string
): { tone: Tone; icon: TimelineIcon } => {
  switch (kind) {
    case 'started':
      return { tone: 'purple', icon: 'started' };
    case 'submitted':
    case 'completed':
      return { tone: 'green', icon: 'done' };
    case 'reopened':
    case 'cancelled':
      return { tone: 'red', icon: 'warning' };
    case 'onHold':
      return { tone: 'amber', icon: 'break' };
    case 'resumed':
      return { tone: 'green', icon: 'started' };
    case 'updated':
      return { tone: 'slate', icon: 'clock' };
    default:
      return { tone: 'indigo', icon: 'scheduled' };
  }
};

const buildDay = (
  day: string,
  data: WorkCalendarData,
  tr: (key: string) => string
): DayModel => {
  const attendance = data.days.find((d) => d.date === day)?.attendance ?? null;
  const request = data.requests.find(
    (r) => r.status !== 'cancelled' && requestCoversDate(r, day)
  );
  const scheduled = data.tasks.filter((task) => taskDay(task) === day);
  const entries: TimelineEntry[] = [];
  const doneIds = new Set<string>();

  const addActivity = (
    task: Task,
    kind: string,
    timestamp: string,
    detail?: string | null,
    suffix = ''
  ) => {
    const meta = activityMeta(kind);
    entries.push({
      id: `act-${task.id}-${timestamp}-${kind}${suffix}`,
      kind: 'activity',
      label: tr(`calendar.${kind}`),
      title: task.title,
      detail: detail || null,
      time: istTime(timestamp),
      sort: istMinutes(timestamp) ?? 9998,
      tone: meta.tone,
      icon: meta.icon,
      task,
    });
  };

  if (attendance?.status && attendance.status !== 'present') {
    entries.push({
      id: `status-${day}`,
      kind: 'status',
      label: tr(`attendance.dayStatus.${attendance.status}`),
      title: request ? requestTypeLabel(request) : tr(`attendance.dayStatus.${attendance.status}`),
      detail: request?.reason ?? null,
      time: null,
      sort: -3,
      tone: attendance.status === 'absent' ? 'red' : 'amber',
      icon: 'warning',
    });
  } else if (!attendance?.started_at && request && request.status !== 'rejected') {
    entries.push({
      id: `request-${day}`,
      kind: 'status',
      label: tr(`attendance.dayStatus.${request.request_type}`),
      title: requestTypeLabel(request),
      detail: [REQUEST_STATUS_LABELS[request.status], request.reason]
        .filter(Boolean)
        .join(' · '),
      time: null,
      sort: -3,
      tone: 'amber',
      icon: 'warning',
    });
  }

  if (attendance?.started_at) {
    entries.push({
      id: `start-${day}`,
      kind: 'day-start',
      label: tr('calendar.dayStarted'),
      title: tr('calendar.dayStarted'),
      detail: attendance.status ? tr(`attendance.dayStatus.${attendance.status}`) : null,
      time: istTime(attendance.started_at),
      sort: istMinutes(attendance.started_at) ?? 0,
      tone: 'green',
      icon: 'login',
    });
  }

  (attendance?.breaks ?? []).forEach((b, i) => {
    const start = istTime(b.started_at);
    const startM = istMinutes(b.started_at);
    const endM = istMinutes(b.ended_at);
    entries.push({
      id: `break-${day}-${i}`,
      kind: 'break',
      label: tr('calendar.break'),
      title: tr('calendar.break'),
      detail: b.duration_seconds != null ? `${Math.round(b.duration_seconds / 60)} min` : null,
      time: start,
      endTime: istTime(b.ended_at),
      sort: startM ?? 9997,
      tone: 'amber',
      icon: 'break',
    });
  });

  if (attendance?.ended_at) {
    entries.push({
      id: `end-${day}`,
      kind: 'day-end',
      label: tr('calendar.dayEnded'),
      title: tr('calendar.dayEnded'),
      time: istTime(attendance.ended_at),
      sort: istMinutes(attendance.ended_at) ?? 9999,
      tone: 'green',
      icon: 'logout',
    });
  }

  scheduled.forEach((task) => {
    const start = taskStartMinutes(task);
    const end = taskEndMinutes(task, start);
    entries.push({
      id: `scheduled-${task.id}`,
      kind: 'scheduled',
      label: tr('calendar.scheduled'),
      title: task.title,
      detail: [
        task.location_name || task.zone_name,
        task.department_name,
        statusLabel(task, day),
      ].filter(Boolean).join(' · '),
      time: start != null
        ? (task.scheduled_for ? istTime(task.scheduled_for) : formatMinutes(start))
        : null,
      endTime: end != null ? formatMinutes(end) : null,
      sort: start ?? 9996,
      tone: task.kind === 'maintenance' ? 'red' : 'indigo',
      icon: 'scheduled',
      task,
    });
    if (task.status === 'completed') doneIds.add(task.id);
  });

  data.tasks.forEach((task) => {
    const events = (task.history ?? [])
      .filter((event) => istDay(event.timestamp) === day)
      .map((event) => ({ event, kind: activityKind(event.event_type) }))
      .filter((item): item is { event: Task['history'][number]; kind: string } => !!item.kind);

    events.forEach(({ event, kind }, index) => {
      addActivity(task, kind, event.timestamp, event.notes ?? event.actor_name, `-${index}`);
      if (kind === 'submitted' || kind === 'completed') doneIds.add(task.id);
    });

    const types = new Set(events.map((item) => item.event.event_type));
    if (
      task.created_at &&
      istDay(task.created_at) === day &&
      ![...ALLOCATION_EVENTS].some((type) => types.has(type))
    ) {
      addActivity(task, 'allocated', task.created_at, null, '-created');
    }
    if (
      task.submitted_at &&
      istDay(task.submitted_at) === day &&
      ![...SUBMIT_EVENTS, ...DONE_EVENTS].some((type) => types.has(type))
    ) {
      addActivity(task, 'submitted', task.submitted_at, null, '-submitted');
      doneIds.add(task.id);
    }
    if (
      task.abandoned_at &&
      istDay(task.abandoned_at) === day &&
      ![...DONE_EVENTS, ...CANCEL_EVENTS].some((type) => types.has(type))
    ) {
      addActivity(task, 'cancelled', task.abandoned_at, null, '-abandoned');
    } else if (
      task.completed_at &&
      istDay(task.completed_at) === day &&
      ![...DONE_EVENTS, ...CANCEL_EVENTS].some((type) => types.has(type))
    ) {
      addActivity(task, 'completed', task.completed_at, null, '-completed');
      doneIds.add(task.id);
    }
  });

  entries.sort((a, b) => a.sort - b.sort || a.title.localeCompare(b.title));
  return {
    scheduled,
    entries,
    doneCount: doneIds.size,
    breakCount: attendance?.breaks?.length ?? 0,
    attendance,
  };
};

const TONES: Record<Tone, { dot: string; card: string; icon: string }> = {
  indigo: {
    dot: 'bg-[#1B365D]',
    card: 'border-[#DCE5F1] bg-[#F7FAFF]',
    icon: 'text-[#1B365D]',
  },
  green: {
    dot: 'bg-[#16865B]',
    card: 'border-[#CDEADD] bg-[#F5FCF8]',
    icon: 'text-[#16865B]',
  },
  amber: {
    dot: 'bg-[#E0A008]',
    card: 'border-[#F3DFA6] bg-[#FFFCF0]',
    icon: 'text-[#A97700]',
  },
  red: {
    dot: 'bg-[#D64545]',
    card: 'border-[#F0CACA] bg-[#FFF7F7]',
    icon: 'text-[#B83232]',
  },
  purple: {
    dot: 'bg-[#5C3FA8]',
    card: 'border-[#DDD4F3] bg-[#FAF8FF]',
    icon: 'text-[#5C3FA8]',
  },
  slate: {
    dot: 'bg-[#8392A8]',
    card: 'border-line bg-surface',
    icon: 'text-mute',
  },
};

const iconFor = (icon: TimelineIcon) => {
  switch (icon) {
    case 'login':
      return LogIn;
    case 'logout':
      return LogOut;
    case 'break':
      return Coffee;
    case 'started':
      return PlayCircle;
    case 'done':
      return CheckCircle2;
    case 'warning':
      return AlertTriangle;
    case 'scheduled':
      return ClipboardList;
    default:
      return Clock;
  }
};

interface Props {
  onOpenTask: (taskId: string, kind?: 'task' | 'maintenance') => void;
}

/** Employee work calendar — allocated work plus the actual attendance and
 *  work-activity timeline for each day. */
export const CalendarScreen: React.FC<Props> = ({ onOpenTask }) => {
  const { t } = useTranslation();
  const today = businessDate();
  const [data, setData] = useState<WorkCalendarData>(EMPTY_DATA);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [anchor, setAnchor] = useState(() => today);
  const [selected, setSelected] = useState(today);
  const [view, setView] = useState<'month' | 'week' | 'day' | 'agenda'>('week');
  const { user } = useAuth();
  const isManager = user?.role === 'department_manager';
  const [depts, setDepts] = useState<TeamDepartment[]>([]);
  const [zones, setZones] = useState<ZoneWire[]>([]);
  const [assignOpen, setAssignOpen] = useState(false);

  useEffect(() => {
    if (!isManager) return;
    void teamApi.overview().then((r) => setDepts(r.items)).catch(() => undefined);
    void getZonesCached().then(setZones).catch(() => undefined);
  }, [isManager]);

  const [ay, am] = anchor.split('-').map(Number);
  const first = new Date(ay, am - 1, 1);
  const startOffset = (first.getDay() + 6) % 7;
  const daysInMonth = new Date(ay, am, 0).getDate();
  const monthDays = useMemo(
    () =>
      Array.from({ length: daysInMonth }, (_, i) =>
        isoDay(new Date(ay, am - 1, i + 1))
      ),
    [ay, am, daysInMonth]
  );
  const cells: (string | null)[] = [
    ...Array<null>(startOffset).fill(null),
    ...monthDays,
  ];

  const viewDays = useMemo(() => {
    const sel = parseDay(selected);
    if (view === 'day' || view === 'month') return [selected];
    if (view === 'week') {
      const monday = new Date(sel);
      monday.setDate(sel.getDate() - ((sel.getDay() + 6) % 7));
      return Array.from({ length: 7 }, (_, i) => {
        const d = new Date(monday);
        d.setDate(monday.getDate() + i);
        return isoDay(d);
      });
    }
    return Array.from({ length: 14 }, (_, i) => {
      const d = new Date(sel);
      d.setDate(d.getDate() + i);
      return isoDay(d);
    });
  }, [view, selected]);

  const range = useMemo(
    () =>
      view === 'month'
        ? { from: monthDays[0], to: monthDays[monthDays.length - 1] }
        : { from: viewDays[0], to: viewDays[viewDays.length - 1] },
    [monthDays, view, viewDays]
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      setData(await fetchWorkCalendarApi(range.from, range.to));
    } catch (err) {
      if (isNotImplemented(err)) {
        // Older deployed backends do not have the timeline feed yet — keep
        // the previous tasks-only calendar instead of failing the tab.
        try {
          setData({ ...EMPTY_DATA, tasks: await fetchTasksApi() });
        } catch {
          setError(true);
        }
      } else {
        setError(true);
      }
    } finally {
      setLoading(false);
    }
  }, [range.from, range.to]);
  useEffect(() => {
    void load();
  }, [load]);

  const renderDays = useMemo(
    () => Array.from(new Set([...(view === 'month' ? monthDays : []), ...viewDays])),
    [monthDays, view, viewDays]
  );
  const dayModels = useMemo(() => {
    const map = new Map<string, DayModel>();
    renderDays.forEach((day) =>
      map.set(day, buildDay(day, data, (key) => String(t(key))))
    );
    return map;
  }, [data, renderDays, t]);

  const shiftMonth = (n: number) => {
    const d = new Date(ay, am - 1 + n, 1);
    setAnchor(isoDay(d));
  };

  const shiftAnchor = (n: number) => {
    const d = parseDay(selected);
    d.setDate(
      d.getDate() + (view === 'day' ? n : view === 'week' ? n * 7 : n * 14)
    );
    setSelected(isoDay(d));
    setAnchor(isoDay(d));
  };

  const monthLabel = first.toLocaleDateString(undefined, {
    month: 'long',
    year: 'numeric',
  });

  const openTask = (task: Task) =>
    onOpenTask(task.id, task.kind === 'maintenance' ? 'maintenance' : 'task');

  const timelineIcon = (entry: TimelineEntry) => {
    const Icon = entry.task?.kind === 'maintenance' && entry.icon === 'scheduled'
      ? Wrench
      : iconFor(entry.icon);
    return <Icon className={`w-3.5 h-3.5 ${TONES[entry.tone].icon}`} />;
  };

  const dayCard = (day: string, compact = false) => {
    const model = dayModels.get(day) ?? buildDay(day, data, (key) => String(t(key)));
    const shown = compact ? model.entries.slice(0, 6) : model.entries;
    const hidden = model.entries.length - shown.length;
    const dayLabel = parseDay(day).toLocaleDateString(undefined, {
      weekday: 'short',
      day: 'numeric',
      month: 'short',
    });
    return (
      <section
        key={day}
        className={`bg-white border rounded-2xl overflow-hidden ${
          day === selected ? 'border-acc' : 'border-line'
        }`}
      >
        <button
          onClick={() => {
            setSelected(day);
            setAnchor(day);
            if (compact) setView('day');
          }}
          className="w-full px-3 py-2.5 flex items-center justify-between text-left"
        >
          <div>
            <p className={`text-[10px] font-bold ${day === today ? 'text-acc' : 'text-ink'}`}>
              {dayLabel}
              {day === today ? ` · ${t('calendar.today')}` : ''}
            </p>
            <div className="mt-0.5 flex flex-wrap gap-x-2 gap-y-0.5 text-[9px] text-mute">
              <span>{model.scheduled.length} {t('calendar.scheduled').toLowerCase()}</span>
              <span>{model.doneCount} {t('calendar.done').toLowerCase()}</span>
              {model.breakCount > 0 && <span>{model.breakCount} {t('calendar.breaks').toLowerCase()}</span>}
            </div>
          </div>
          <ChevronRight className="w-4 h-4 text-mute" />
        </button>

        <div className="px-3 pb-3">
          {shown.length === 0 ? (
            <p className="py-3 text-[10px] text-mute border-t border-line">
              {t('calendar.noActivity')}
            </p>
          ) : (
            <div className="border-t border-line pt-1">
              {shown.map((entry) => {
                const tone = TONES[entry.tone];
                const content = (
                  <div className="flex gap-2 py-1.5">
                    <div className="w-11 pt-0.5 text-right text-[9px] font-semibold text-mute">
                      {entry.time ?? t('calendar.anytime')}
                      {entry.endTime && <div>{entry.endTime}</div>}
                    </div>
                    <div className="relative w-4 flex justify-center">
                      <span className="absolute top-0 bottom-0 w-px bg-line" />
                      <span className={`relative mt-1 w-2 h-2 rounded-full ${tone.dot}`} />
                    </div>
                    <div className={`flex-1 min-w-0 rounded-xl border px-2 py-1.5 ${tone.card}`}>
                      <div className="flex items-center gap-1.5">
                        {timelineIcon(entry)}
                        <span className="text-[8px] font-bold uppercase tracking-wide text-mute">
                          {entry.label}
                        </span>
                      </div>
                      <p className="mt-0.5 text-[10px] font-semibold text-ink truncate">
                        {entry.title}
                      </p>
                      {entry.detail && (
                        <p className="text-[9px] text-mute truncate">{entry.detail}</p>
                      )}
                    </div>
                  </div>
                );
                return entry.task ? (
                  <button
                    key={entry.id}
                    onClick={() => openTask(entry.task!)}
                    className="w-full text-left"
                  >
                    {content}
                  </button>
                ) : (
                  <div key={entry.id}>{content}</div>
                );
              })}
              {hidden > 0 && (
                <button
                  onClick={() => {
                    setSelected(day);
                    setAnchor(day);
                    setView('day');
                  }}
                  className="w-full py-1.5 text-[9px] font-semibold text-acc text-left"
                >
                  +{hidden} {t('calendar.more')}
                </button>
              )}
            </div>
          )}
        </div>
      </section>
    );
  };

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      <div className="px-4 pt-4 pb-2 flex items-center justify-between">
        <h1 className="text-[15px] font-bold text-ink">{t('calendar.title')}</h1>
        <div className="flex items-center gap-1.5">
          <div className="flex bg-surface border border-line rounded-lg overflow-hidden">
            {(['month', 'week', 'day', 'agenda'] as const).map((v) => (
              <button
                key={v}
                onClick={() => setView(v)}
                className={`px-2.5 py-1 text-[9px] font-semibold ${
                  view === v ? 'bg-ink text-white' : 'text-mute'
                }`}
              >
                {t(`calendar.${v}`)}
              </button>
            ))}
          </div>
          {isManager && depts.length > 0 && (
            <button
              onClick={() => setAssignOpen(true)}
              className="flex items-center gap-1 bg-acc text-white rounded-lg px-2.5 py-1.5 text-[10px] font-bold min-h-[32px]"
            >
              <Plus className="w-3.5 h-3.5" /> {t('team.assign')}
            </button>
          )}
          <button onClick={() => void load()} className="p-1.5 text-mute">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {error && (
        <p className="mx-4 mb-2 rounded-lg border border-[#F0CACA] bg-[#FFF7F7] px-3 py-2 text-[10px] text-[#B83232]">
          {t('calendar.loadError')}
        </p>
      )}

      {view === 'month' && (
        <div className="px-4">
          <div className="flex items-center justify-between py-1">
            <button onClick={() => shiftMonth(-1)} className="p-1.5 text-mute">
              <ChevronLeft className="w-4 h-4" />
            </button>
            <button
              onClick={() => {
                setAnchor(today);
                setSelected(today);
              }}
              className="text-[10px] font-semibold text-ink"
            >
              {monthLabel}
            </button>
            <button onClick={() => shiftMonth(1)} className="p-1.5 text-mute">
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
          <div className="grid grid-cols-7 text-center text-[9px] font-semibold text-mute py-1">
            {['M', 'T', 'W', 'T', 'F', 'S', 'S'].map((d, i) => <span key={i}>{d}</span>)}
          </div>
          <div className="grid grid-cols-7 gap-y-1 pb-2">
            {cells.map((d, i) => {
              if (!d) return <span key={`x${i}`} />;
              const model = dayModels.get(d);
              const items = model?.scheduled ?? [];
              const hasActivity = (model?.entries.length ?? 0) > items.length;
              const isSel = d === selected;
              const isToday = d === today;
              return (
                <button
                  key={d}
                  onClick={() => {
                    setSelected(d);
                    setView('day');
                  }}
                  className="flex flex-col items-center py-1"
                >
                  <span
                    className={`w-7 h-7 flex items-center justify-center rounded-full text-[10px] ${
                      isSel
                        ? 'bg-acc text-white font-bold'
                        : isToday
                          ? 'border border-acc text-acc font-bold'
                          : 'text-ink'
                    }`}
                  >
                    {Number(d.slice(8))}
                  </span>
                  <span className="flex gap-0.5 h-1 mt-0.5">
                    {items.slice(0, 2).map((task) => (
                      <span key={task.id} className={`w-1 h-1 rounded-full ${statusDot(task, today)}`} />
                    ))}
                    {hasActivity && <span className="w-1 h-1 rounded-full bg-[#16865B]" />}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {view !== 'month' && (
        <div className="px-4 pb-1 flex items-center justify-between">
          <button onClick={() => shiftAnchor(-1)} className="p-1.5 text-mute">
            <ChevronLeft className="w-4 h-4" />
          </button>
          <button
            onClick={() => {
              setAnchor(today);
              setSelected(today);
            }}
            className="text-[10px] font-semibold text-ink"
          >
            {view === 'day'
              ? parseDay(selected).toLocaleDateString(undefined, {
                  weekday: 'short',
                  day: 'numeric',
                  month: 'short',
                })
              : `${parseDay(viewDays[0]).toLocaleDateString(undefined, {
                  day: 'numeric',
                  month: 'short',
                })} – ${parseDay(viewDays[viewDays.length - 1]).toLocaleDateString(undefined, {
                  day: 'numeric',
                  month: 'short',
                })}`}
          </button>
          <button onClick={() => shiftAnchor(1)} className="p-1.5 text-mute">
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      )}

      <div className="flex-1 px-4 pb-6 space-y-3">
        {viewDays.map((day) => dayCard(day, view !== 'day'))}
        {loading && (
          <p className="py-4 text-center text-[10px] text-mute">
            {t('common.loading')}
          </p>
        )}
      </div>

      {assignOpen && depts[0] && (
        <AssignSheet
          dept={depts[0]}
          zones={zones}
          onClose={() => setAssignOpen(false)}
          onSaved={() => {
            setAssignOpen(false);
            void load();
          }}
        />
      )}
    </div>
  );
};
