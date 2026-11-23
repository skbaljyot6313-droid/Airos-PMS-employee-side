import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronLeft, ChevronRight, Plus, RefreshCw, Wrench } from 'lucide-react';
import { fetchTasksApi } from '../../api/tasks';
import { teamApi, TeamDepartment } from '../../api/team';
import { getZonesCached } from '../../api/directory';
import { ZoneWire } from '../../api/wire';
import { useAuth } from '../../context/AuthContext';
import { AssignSheet } from './MyTeamScreen';
import { businessDate } from '../../api/attendance';
import type { Task } from '../../types';

const pad = (n: number) => String(n).padStart(2, '0');
const isoDay = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

/** The date a task belongs on the calendar — the scheduled occurrence,
 *  falling back to the due date. Creation time is never used. */
const taskDay = (t: Task): string | null =>
  t.scheduled_for?.slice(0, 10) ?? t.due_date?.slice(0, 10) ?? null;

const taskTime = (t: Task): string | null =>
  t.scheduled_for?.slice(11, 16) ?? t.start_time ?? t.due_time?.slice(0, 5) ?? null;

const hm = (v?: string | null): string | null => (v ? v.slice(0, 5) : null);

/** 'HH:MM–HH:MM' window when the schedule carries an end time. */
const taskWindow = (t: Task): string | null => {
  const start = hm(t.start_time) ?? taskTime(t);
  const end = hm(t.end_time);
  if (start && end) return `${start}–${end}`;
  return start;
};

const STATUS_LABEL: Record<string, string> = {
  pending: 'Scheduled', assigned: 'Scheduled', scheduled: 'Scheduled',
  in_progress: 'In Progress', completed: 'Completed', submitted: 'Submitted',
  overdue: 'Overdue', cancelled: 'Cancelled', reopened: 'Reopened',
};

const statusLabel = (t: Task, today: string): string => {
  const day = taskDay(t);
  if (UPCOMING.has(t.status) && day && day < today) return 'Overdue';
  return STATUS_LABEL[t.status] ?? t.status;
};

const UPCOMING = new Set(['pending', 'assigned', 'in_progress', 'reopened', 'scheduled']);

const statusDot = (t: Task, today: string): string => {
  const day = taskDay(t);
  if (t.kind === 'maintenance') return 'bg-[#790D16]';
  if (UPCOMING.has(t.status) && day && day < today) return 'bg-[#D64545]';
  switch (t.status) {
    case 'completed': return 'bg-[#16865B]';
    case 'submitted': return 'bg-[#F4BE38]';
    case 'in_progress': return 'bg-[#5C3FA8]';
    case 'overdue': return 'bg-[#D64545]';
    default: return 'bg-[#1B365D]';
  }
};

interface Props { onOpenTask: (taskId: string, kind?: 'task' | 'maintenance') => void; }

/** Employee calendar — every piece of scheduled work, on the day it's due. */
export const CalendarScreen: React.FC<Props> = ({ onOpenTask }) => {
  const { t } = useTranslation();
  const today = businessDate();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
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
    void getZonesCached().then(setZones);
  }, [isManager]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setTasks(await fetchTasksApi());
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const byDay = useMemo(() => {
    const m = new Map<string, Task[]>();
    tasks.forEach((task) => {
      const d = taskDay(task);
      if (!d) return;
      // terminal statuses still show, but only on/past their actual day —
      // abandoned work never appears as upcoming.
      const list = m.get(d) ?? [];
      list.push(task);
      m.set(d, list);
    });
    return m;
  }, [tasks]);

  // Month grid for the anchor's month
  const [ay, am] = anchor.split('-').map(Number);
  const first = new Date(ay, am - 1, 1);
  const startOffset = (first.getDay() + 6) % 7; // Monday-first
  const daysInMonth = new Date(ay, am, 0).getDate();
  const cells: (string | null)[] = [
    ...Array<null>(startOffset).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => isoDay(new Date(ay, am - 1, i + 1))),
  ];

  const shiftMonth = (n: number) => {
    const d = new Date(ay, am - 1 + n, 1);
    setAnchor(isoDay(d));
  };

  const viewDays = useMemo(() => {
    const sel = new Date(`${selected}T00:00:00`);
    if (view === 'day') return [selected];
    if (view === 'month') return [selected];
    if (view === 'week') {
      const monday = new Date(sel);
      monday.setDate(sel.getDate() - ((sel.getDay() + 6) % 7));
      return Array.from({ length: 7 }, (_, i) => {
        const d = new Date(monday); d.setDate(monday.getDate() + i);
        return isoDay(d);
      });
    }
    return Array.from({ length: 14 }, (_, i) => {
      const d = new Date(sel); d.setDate(d.getDate() + i);
      return isoDay(d);
    });
  }, [view, selected]);

  const shiftAnchor = (n: number) => {
    const d = new Date(`${selected}T00:00:00`);
    d.setDate(d.getDate() + (view === 'day' ? n : view === 'week' ? n * 7 : n * 14));
    setSelected(isoDay(d));
    setAnchor(isoDay(d));
  };

  const monthLabel = new Date(ay, am - 1, 1).toLocaleDateString(undefined, { month: 'long', year: 'numeric' });

  const row = (task: Task) => {
    const day = taskDay(task);
    const overdue = UPCOMING.has(task.status) && day != null && day < today;
    return (
      <button
        key={task.id}
        onClick={() => onOpenTask(task.id, task.kind === 'maintenance' ? 'maintenance' : 'task')}
        className="w-full flex items-center gap-3 px-3 py-2.5 bg-white border border-line rounded-xl text-left active:bg-gray-50"
      >
        <span className={`w-1.5 self-stretch rounded-full ${statusDot(task, today)}`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            {task.kind === 'maintenance' && <Wrench className="w-3 h-3 text-[#790D16] shrink-0" />}
            <span className="text-[10px] font-semibold text-ink truncate">{task.title}</span>
            {overdue && (
              <span className="shrink-0 text-[9px] font-bold uppercase tracking-wide text-[#D64545]">
                {t('calendar.overdue')}
              </span>
            )}
          </div>
          <div className="text-[9px] text-mute truncate">
            {taskWindow(task) ? `${taskWindow(task)}` : ''}
            {task.break_start_time ? ` · break ${hm(task.break_start_time)}–${hm(task.break_end_time) ?? ''}` : ''}
            {task.location_name || task.zone_name ? ` · ${task.location_name || task.zone_name}` : ''}
            {task.department_name ? ` · ${task.department_name}` : ''}
            {task.checklist.length > 0
              ? ` · ☑ ${task.checklist.filter((c) => c.completed).length}/${task.checklist.length}`
              : ''}
          </div>
        </div>
        <div className="flex flex-col items-end gap-0.5 shrink-0">
          <span className="text-[9px] uppercase tracking-wide text-mute">
            {task.priority}
          </span>
          <span className="text-[8px] font-semibold uppercase tracking-wide text-sub">
            {statusLabel(task, today)}
          </span>
        </div>
      </button>
    );
  };

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      {/* Header */}
      <div className="px-4 pt-4 pb-2 flex items-center justify-between">
        <h1 className="text-[15px] font-bold text-ink">{t('calendar.title')}</h1>
        <div className="flex items-center gap-1.5">
          <div className="flex bg-surface border border-line rounded-lg overflow-hidden">
            {(['month', 'week', 'day', 'agenda'] as const).map((v) => (
              <button key={v} onClick={() => setView(v)}
                className={`px-2.5 py-1 text-[9px] font-semibold ${
                  view === v ? 'bg-ink text-white' : 'text-mute'}`}>
                {t(`calendar.${v}`)}
              </button>
            ))}
          </div>
          {isManager && depts.length > 0 && (
            <button onClick={() => setAssignOpen(true)}
              className="flex items-center gap-1 bg-acc text-white rounded-lg px-2.5 py-1.5 text-[10px] font-bold min-h-[32px]">
              <Plus className="w-3.5 h-3.5" /> {t('team.assign')}
            </button>
          )}
          <button onClick={() => void load()} className="p-1.5 text-mute">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {view === 'month' && (
        <div className="px-4">
          {/* Month nav */}
          <div className="flex items-center justify-between py-1">
            <button onClick={() => shiftMonth(-1)} className="p-1.5 text-mute">
              <ChevronLeft className="w-4 h-4" />
            </button>
            <button onClick={() => { setAnchor(today); setSelected(today); }}
              className="text-[10px] font-semibold text-ink">
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
              const items = byDay.get(d) ?? [];
              const isSel = d === selected;
              const isToday = d === today;
              return (
                <button key={d} onClick={() => setSelected(d)}
                  className="flex flex-col items-center py-1">
                  <span className={`w-7 h-7 flex items-center justify-center rounded-full text-[10px] ${
                    isSel ? 'bg-acc text-white font-bold'
                    : isToday ? 'border border-acc text-acc font-bold'
                    : 'text-ink'}`}>
                    {Number(d.slice(8))}
                  </span>
                  <span className="flex gap-0.5 h-1 mt-0.5">
                    {items.slice(0, 3).map((tk) => (
                      <span key={tk.id} className={`w-1 h-1 rounded-full ${statusDot(tk, today)}`} />
                    ))}
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
          <button onClick={() => { setAnchor(today); setSelected(today); }}
            className="text-[10px] font-semibold text-ink">
            {view === 'day'
              ? new Date(`${selected}T00:00:00`).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })
              : `${new Date(`${viewDays[0]}T00:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })} – ${new Date(`${viewDays[viewDays.length - 1]}T00:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}`}
          </button>
          <button onClick={() => shiftAnchor(1)} className="p-1.5 text-mute">
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Agenda-style list for week/day/agenda and the month's selected day */}
      <div className="flex-1 px-4 pb-6 space-y-3">
        {viewDays.map((d) => {
          const items = byDay.get(d) ?? [];
          return (
            <div key={d}>
              <p className={`text-[9px] font-bold uppercase tracking-wider pb-1.5 ${
                d === today ? 'text-acc' : 'text-mute'}`}>
                {new Date(`${d}T00:00:00`).toLocaleDateString(undefined, {
                  weekday: 'short', day: 'numeric', month: 'short',
                })}
                {d === today ? ` · ${t('calendar.today')}` : ''}
              </p>
              {items.length === 0 ? (
                (view === 'agenda' || view === 'day' || view === 'week') && (
                  <p className="text-[10px] text-mute pl-1">{t('calendar.nothingScheduled')}</p>
                )
              ) : (
                <div className="space-y-1.5">{items.map(row)}</div>
              )}
            </div>
          );
        })}
        {!loading && viewDays.every((d) => !(byDay.get(d)?.length)) && view === 'month' && (
          <p className="text-[10px] text-mute text-center py-6">{t('calendar.nothingScheduled')}</p>
        )}
      </div>

      {assignOpen && depts[0] && (
        <AssignSheet dept={depts[0]} zones={zones}
          onClose={() => setAssignOpen(false)}
          onSaved={() => { setAssignOpen(false); void load(); }} />
      )}
    </div>
  );
};
