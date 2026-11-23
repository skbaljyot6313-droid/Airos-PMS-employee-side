import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  CalendarDays, ChevronDown, ChevronLeft, ChevronRight, Plus,
  RefreshCw, Search, Users, X,
} from 'lucide-react';
import {
  ConflictError, ScheduleConflict, TeamDepartment, TeamWorkPayload,
  teamApi,
} from '../../api/team';
import { getZonesCached } from '../../api/directory';
import { businessDate } from '../../api/attendance';
import { TaskWire, ZoneWire } from '../../api/wire';
import { errorMessage } from '../../api/client';

const pad = (n: number) => String(n).padStart(2, '0');
const isoDay = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const hm = (v?: string | null) => (v ? v.slice(0, 5) : null);

const STATUS_DOT: Record<string, string> = {
  completed: 'bg-[#16865B]', submitted: 'bg-[#F4BE38]', in_progress: 'bg-[#5C3FA8]',
  overdue: 'bg-[#D64545]', cancelled: 'bg-[#98A2B3]',
};
const OPEN = new Set(['pending', 'assigned', 'in_progress', 'reopened', 'scheduled']);
const PRIORITIES = ['low', 'medium', 'high', 'critical'];

const taskDay = (t: TaskWire) =>
  t.scheduled_for?.slice(0, 10) ?? t.due_date?.slice(0, 10) ?? null;

const initials = (name: string) =>
  name.split(/\s+/).map((w) => w[0]).filter(Boolean).slice(0, 2).join('').toUpperCase();

interface Props { onOpenTask: (taskId: string) => void; }

/* ------------------------------------------------------------------ */
/* Assign / Edit sheet                                                  */
/* ------------------------------------------------------------------ */

interface SheetProps {
  dept: TeamDepartment;
  zones: ZoneWire[];
  editing?: TaskWire | null;
  onClose: () => void;
  onSaved: () => void;
}

export const AssignSheet: React.FC<SheetProps> = ({ dept, zones, editing, onClose, onSaved }) => {
  const { t } = useTranslation();
  const today = businessDate();
  const [title, setTitle] = useState(editing?.title ?? '');
  const [description, setDescription] = useState(editing?.description ?? '');
  const [notes, setNotes] = useState('');
  const [date, setDate] = useState(taskDay(editing ?? ({} as TaskWire)) ?? today);
  const [startTime, setStartTime] = useState(hm(editing?.start_time) ?? '');
  const [endTime, setEndTime] = useState(hm(editing?.end_time) ?? '');
  const [breakStart, setBreakStart] = useState(hm(editing?.break_start_time) ?? '');
  const [breakEnd, setBreakEnd] = useState(hm(editing?.break_end_time) ?? '');
  const [estMinutes, setEstMinutes] = useState(
    editing?.estimated_minutes ? String(editing.estimated_minutes) : '');
  const [priority, setPriority] = useState(editing?.priority ?? 'medium');
  const [zoneUid, setZoneUid] = useState(editing?.zone_uid ?? '');
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(editing?.employee_uid ? [editing.employee_uid] : []));
  const [search, setSearch] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflicts, setConflicts] = useState<ScheduleConflict[] | null>(null);

  const roster = useMemo(() =>
    dept.employees.filter((e) =>
      !search || e.name.toLowerCase().includes(search.toLowerCase())),
    [dept.employees, search]);

  const valid = title.trim().length > 0 && date.length === 10 &&
    (editing ? true : selected.size > 0) &&
    (!startTime || !endTime || endTime > startTime) &&
    (!breakStart || !breakEnd || breakEnd > breakStart);

  const buildPayload = (allow: boolean): TeamWorkPayload => ({
    title: title.trim(),
    description: description.trim() || null,
    notes: notes.trim() || null,
    priority,
    zone_uid: zoneUid || null,
    due_date: date,
    start_time: startTime || null,
    end_time: endTime || null,
    break_start_time: breakStart || null,
    break_end_time: breakEnd || null,
    estimated_minutes: estMinutes ? Number(estMinutes) : null,
    employee_uids: [...selected],
    allow_conflicts: allow,
  });

  const submit = async (allow = false) => {
    if (!valid || busy) return;
    setBusy(true); setError(null);
    try {
      if (editing) {
        const { employee_uids: _omit, ...patch } = buildPayload(allow);
        await teamApi.update(editing.task_uid, patch);
      } else {
        await teamApi.allocate(dept.department_uid, buildPayload(allow));
      }
      onSaved();
    } catch (e) {
      if (e instanceof ConflictError) setConflicts(e.conflicts);
      else setError(errorMessage(e, 'Could not save the assignment.'));
    } finally {
      setBusy(false);
    }
  };

  const field = 'w-full bg-surface border border-line rounded-xl px-3 py-2.5 text-[12px] text-ink placeholder:text-mute min-h-[44px]';
  const label = 'text-[9px] font-bold uppercase tracking-wider text-mute pb-1 block';

  return (
    <div className="fixed inset-0 z-50 flex items-end bg-black/40" onClick={onClose}>
      <div className="w-full bg-surface rounded-t-2xl max-h-[92vh] overflow-y-auto pb-[max(1.5rem,env(safe-area-inset-bottom))]"
        onClick={(e) => e.stopPropagation()}>
        <div className="sticky top-0 bg-surface px-4 pt-3 pb-2 flex items-center justify-between border-b border-line">
          <h2 className="text-[13px] font-bold text-ink">
            {editing ? t('team.editWork') : t('team.assignWork')}
          </h2>
          <button onClick={onClose} className="p-1.5 text-mute"><X className="w-4 h-4" /></button>
        </div>

        <div className="px-4 py-3 space-y-3">
          <div>
            <span className={label}>{t('team.workTitle')} *</span>
            <input className={field} value={title} onChange={(e) => setTitle(e.target.value)}
              placeholder={t('team.titlePlaceholder')} />
          </div>
          <div>
            <span className={label}>{t('team.description')}</span>
            <textarea className={`${field} min-h-[64px] resize-none`} value={description}
              onChange={(e) => setDescription(e.target.value)} />
          </div>
          <div>
            <span className={label}>{t('team.notes')}</span>
            <input className={field} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>

          {!editing && (
            <div>
              <span className={label}>{t('team.employees')} *</span>
              <div className="flex items-center gap-2 bg-surface border border-line rounded-xl px-3 mb-2">
                <Search className="w-3.5 h-3.5 text-mute" />
                <input className="flex-1 py-2 text-[12px] text-ink placeholder:text-mute outline-none min-h-[40px]"
                  value={search} onChange={(e) => setSearch(e.target.value)}
                  placeholder={t('team.searchEmployees')} />
              </div>
              <div className="max-h-40 overflow-y-auto space-y-1 border border-line rounded-xl p-2">
                {roster.map((e) => {
                  const on = selected.has(e.employee_uid);
                  return (
                    <button key={e.employee_uid} type="button"
                      onClick={() => {
                        const next = new Set(selected);
                        if (on) next.delete(e.employee_uid); else next.add(e.employee_uid);
                        setSelected(next);
                      }}
                      className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left min-h-[44px] ${
                        on ? 'bg-acc/10 border border-acc/40' : 'border border-transparent'}`}>
                      <span className={`w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold ${
                        on ? 'bg-acc text-white' : 'bg-line text-sub'}`}>
                        {initials(e.name)}
                      </span>
                      <span className="flex-1 min-w-0">
                        <span className="block text-[11px] font-semibold text-ink truncate">{e.name}</span>
                        <span className="block text-[9px] text-mute truncate">{e.job_title ?? ''}</span>
                      </span>
                      <span className={`w-4 h-4 rounded border flex items-center justify-center ${
                        on ? 'bg-acc border-acc text-white' : 'border-line'}`}>
                        {on && <span className="text-[10px]">✓</span>}
                      </span>
                    </button>
                  );
                })}
                {roster.length === 0 && (
                  <p className="text-[10px] text-mute text-center py-3">{t('team.noEmployees')}</p>
                )}
              </div>
              {selected.size > 0 && (
                <p className="text-[10px] text-sub pt-1.5">
                  {selected.size} {t('team.selected')}
                </p>
              )}
            </div>
          )}

          <div className="grid grid-cols-2 gap-2">
            <div>
              <span className={label}>{t('team.date')} *</span>
              <input type="date" className={field} value={date} onChange={(e) => setDate(e.target.value)} />
            </div>
            <div>
              <span className={label}>{t('team.estimatedMinutes')}</span>
              <input type="number" min={0} className={field} value={estMinutes}
                onChange={(e) => setEstMinutes(e.target.value)} placeholder="60" />
            </div>
            <div>
              <span className={label}>{t('team.startTime')}</span>
              <input type="time" className={field} value={startTime} onChange={(e) => setStartTime(e.target.value)} />
            </div>
            <div>
              <span className={label}>{t('team.endTime')}</span>
              <input type="time" className={field} value={endTime} onChange={(e) => setEndTime(e.target.value)} />
            </div>
            <div>
              <span className={label}>{t('team.breakStart')}</span>
              <input type="time" className={field} value={breakStart} onChange={(e) => setBreakStart(e.target.value)} />
            </div>
            <div>
              <span className={label}>{t('team.breakEnd')}</span>
              <input type="time" className={field} value={breakEnd} onChange={(e) => setBreakEnd(e.target.value)} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <span className={label}>{t('team.priority')}</span>
              <div className="relative">
                <select className={`${field} appearance-none pr-8`} value={priority}
                  onChange={(e) => setPriority(e.target.value)}>
                  {PRIORITIES.map((p) => <option key={p} value={p}>{t(`priority.${p}`)}</option>)}
                </select>
                <ChevronDown className="w-3.5 h-3.5 text-mute absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
              </div>
            </div>
            <div>
              <span className={label}>{t('team.zone')}</span>
              <div className="relative">
                <select className={`${field} appearance-none pr-8`} value={zoneUid}
                  onChange={(e) => setZoneUid(e.target.value)}>
                  <option value="">{t('team.noZone')}</option>
                  {zones.map((z) => <option key={z.zone_uid} value={z.zone_uid}>{z.name}</option>)}
                </select>
                <ChevronDown className="w-3.5 h-3.5 text-mute absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
              </div>
            </div>
          </div>

          {conflicts && (
            <div className="bg-[#D64545]/10 border border-[#D64545]/30 rounded-xl p-3 space-y-1.5">
              <p className="text-[10px] font-bold text-[#D64545] uppercase tracking-wide">
                {t('team.conflicts')}
              </p>
              {conflicts.map((c) => (
                <p key={c.task_uid} className="text-[10px] text-sub">
                  {c.kind === 'duplicate' ? t('team.conflictDuplicate') : t('team.conflictOverlap')}
                  {' · '}{c.employee_name ?? ''}{' · '}{c.title}
                  {c.start_time ? ` · ${hm(c.start_time)}–${hm(c.end_time) ?? ''}` : ''}
                </p>
              ))}
            </div>
          )}
          {error && <p className="text-[10px] font-semibold text-[#D64545]">{error}</p>}

          <div className="flex gap-2 pt-1">
            {conflicts ? (
              <>
                <button onClick={() => setConflicts(null)}
                  className="flex-1 py-3 rounded-xl border border-line text-[11px] font-bold text-sub min-h-[44px]">
                  {t('team.editTimes')}
                </button>
                <button onClick={() => void submit(true)} disabled={busy}
                  className="flex-1 py-3 rounded-xl bg-acc text-white text-[11px] font-bold min-h-[44px] disabled:opacity-50">
                  {busy ? t('common.saving') : t('team.createAnyway')}
                </button>
              </>
            ) : (
              <button onClick={() => void submit(false)} disabled={!valid || busy}
                className="flex-1 py-3 rounded-xl bg-acc text-white text-[11px] font-bold min-h-[44px] disabled:opacity-50">
                {busy ? t('common.saving') : editing ? t('team.saveChanges') : t('team.assignCta')}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/* Reassign sheet                                                       */
/* ------------------------------------------------------------------ */

const ReassignSheet: React.FC<{
  dept: TeamDepartment; task: TaskWire; onClose: () => void; onSaved: () => void;
}> = ({ dept, task, onClose, onSaved }) => {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="fixed inset-0 z-50 flex items-end bg-black/40" onClick={onClose}>
      <div className="w-full bg-surface rounded-t-2xl max-h-[70vh] overflow-y-auto pb-[max(1.5rem,env(safe-area-inset-bottom))]"
        onClick={(e) => e.stopPropagation()}>
        <div className="px-4 pt-3 pb-2 flex items-center justify-between border-b border-line">
          <h2 className="text-[13px] font-bold text-ink">{t('team.reassign')}</h2>
          <button onClick={onClose} className="p-1.5 text-mute"><X className="w-4 h-4" /></button>
        </div>
        <div className="p-3 space-y-1">
          {dept.employees.filter((e) => e.employee_uid !== task.employee_uid).map((e) => (
            <button key={e.employee_uid} disabled={busy}
              onClick={async () => {
                setBusy(true); setError(null);
                try { await teamApi.reassign(task.task_uid, e.employee_uid); onSaved(); }
                catch (err) { setError(errorMessage(err, 'Reassign failed')); setBusy(false); }
              }}
              className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl border border-line text-left min-h-[44px]">
              <span className="w-7 h-7 rounded-full bg-line flex items-center justify-center text-[10px] font-bold text-sub">
                {initials(e.name)}
              </span>
              <span className="flex-1 text-[11px] font-semibold text-ink">{e.name}</span>
              <span className="text-[9px] text-mute">{e.open_tasks} {t('team.open')}</span>
            </button>
          ))}
          {error && <p className="text-[10px] font-semibold text-[#D64545] px-1">{error}</p>}
        </div>
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/* My Team                                                              */
/* ------------------------------------------------------------------ */

export const MyTeamScreen: React.FC<Props> = ({ onOpenTask }) => {
  const { t } = useTranslation();
  const today = businessDate();
  const [depts, setDepts] = useState<TeamDepartment[]>([]);
  const [deptIdx, setDeptIdx] = useState(0);
  const [zones, setZones] = useState<ZoneWire[]>([]);
  const [work, setWork] = useState<TaskWire[]>([]);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<'roster' | 'day' | 'week' | 'agenda'>('roster');
  const [anchor, setAnchor] = useState(today);
  const [empFilter, setEmpFilter] = useState<Set<string>>(new Set());
  const [statusFilter, setStatusFilter] = useState('');
  const [priorityFilter, setPriorityFilter] = useState('');
  const [zoneFilter, setZoneFilter] = useState('');
  const [sheet, setSheet] = useState<'assign' | { edit: TaskWire } | { reassign: TaskWire } | null>(null);
  const [expandedEmp, setExpandedEmp] = useState<string | null>(null);

  const dept = depts[deptIdx];
  const empName = useMemo(() => new Map(
    depts.flatMap((d) => d.employees.map((e) => [e.employee_uid, e.name]))), [depts]);

  const loadOverview = useCallback(async () => {
    const res = await teamApi.overview();
    setDepts(res.items);
  }, []);

  const viewRange = useMemo((): [string, string] => {
    const sel = new Date(`${anchor}T00:00:00`);
    if (view === 'day' || view === 'roster') return [anchor, anchor];
    if (view === 'week') {
      const mon = new Date(sel); mon.setDate(sel.getDate() - ((sel.getDay() + 6) % 7));
      const sun = new Date(mon); sun.setDate(mon.getDate() + 6);
      return [isoDay(mon), isoDay(sun)];
    }
    const end = new Date(sel); end.setDate(sel.getDate() + 13);
    return [anchor, isoDay(end)];
  }, [view, anchor]);

  const loadWork = useCallback(async () => {
    if (!dept) return;
    const [from, to] = viewRange;
    const res = await teamApi.work(dept.department_uid, {
      date_from: from, date_to: to,
      status: statusFilter || undefined,
      priority: priorityFilter || undefined,
      zone_uid: zoneFilter || undefined,
      employee_id: empFilter.size === 1 ? [...empFilter][0] : undefined,
    });
    setWork(res.items);
  }, [dept, viewRange, statusFilter, priorityFilter, zoneFilter, empFilter]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try { await Promise.all([loadOverview(), loadWork()]); }
    finally { setLoading(false); }
  }, [loadOverview, loadWork]);

  useEffect(() => { void loadOverview(); void getZonesCached().then(setZones); }, [loadOverview]);
  useEffect(() => { void loadWork(); }, [loadWork]);

  const byDay = useMemo(() => {
    const m = new Map<string, TaskWire[]>();
    work.forEach((task) => {
      const d = taskDay(task);
      if (!d) return;
      if (empFilter.size > 1 && task.employee_uid && !empFilter.has(task.employee_uid)) return;
      m.set(d, [...(m.get(d) ?? []), task]);
    });
    return m;
  }, [work, empFilter]);

  const days = useMemo(() => {
    const [from, to] = viewRange;
    const out: string[] = [];
    const d = new Date(`${from}T00:00:00`);
    const end = new Date(`${to}T00:00:00`);
    while (d <= end && out.length < 31) { out.push(isoDay(d)); d.setDate(d.getDate() + 1); }
    return out;
  }, [viewRange]);

  const workRow = (task: TaskWire) => {
    const day = taskDay(task);
    const overdue = task.is_overdue ?? (OPEN.has(task.status) && day != null && day < today);
    const terminal = ['submitted', 'completed', 'cancelled'].includes(task.status);
    return (
      <div key={task.task_uid}
        className="flex items-stretch gap-3 px-3 py-2.5 bg-white border border-line rounded-xl">
        <span className={`w-1.5 rounded-full ${STATUS_DOT[task.status] ?? (overdue ? 'bg-[#D64545]' : 'bg-[#1B365D]')}`} />
        <button className="flex-1 min-w-0 text-left" onClick={() => onOpenTask(task.task_uid)}>
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] font-semibold text-ink truncate">{task.title}</span>
            {overdue && <span className="text-[9px] font-bold uppercase text-[#D64545]">{t('calendar.overdue')}</span>}
          </div>
          <div className="text-[9px] text-mute truncate">
            {task.assigned_to_name ?? empName.get(task.employee_uid ?? '') ?? ''}
            {task.start_time ? ` · ${hm(task.start_time)}${task.end_time ? `–${hm(task.end_time)}` : ''}` : ''}
            {task.break_start_time ? ` · break ${hm(task.break_start_time)}–${hm(task.break_end_time) ?? ''}` : ''}
          </div>
        </button>
        {!terminal && (
          <div className="flex flex-col gap-1 justify-center shrink-0">
            <button onClick={() => setSheet({ edit: task })}
              className="text-[9px] font-bold text-acc uppercase tracking-wide">{t('team.edit')}</button>
            <button onClick={() => setSheet({ reassign: task })}
              className="text-[9px] font-bold text-sub uppercase tracking-wide">{t('team.move')}</button>
            <button onClick={async () => { await teamApi.cancel(task.task_uid); void loadWork(); }}
              className="text-[9px] font-bold text-[#D64545] uppercase tracking-wide">{t('team.cancel')}</button>
          </div>
        )}
      </div>
    );
  };

  if (!loading && depts.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-2 px-8">
        <Users className="w-8 h-8 text-mute" />
        <p className="text-[11px] text-mute text-center">{t('team.noDepartments')}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      <div className="px-4 pt-4 pb-2 flex items-center justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <h1 className="text-[15px] font-bold text-ink shrink-0">{t('team.title')}</h1>
          {depts.length > 1 && (
            <div className="relative">
              <select value={deptIdx} onChange={(e) => setDeptIdx(Number(e.target.value))}
                className="appearance-none bg-surface border border-line rounded-lg pl-2 pr-6 py-1 text-[10px] font-semibold text-ink">
                {depts.map((d, i) => <option key={d.department_uid} value={i}>{d.name}</option>)}
              </select>
              <ChevronDown className="w-3 h-3 text-mute absolute right-1.5 top-1/2 -translate-y-1/2 pointer-events-none" />
            </div>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <button onClick={() => setSheet('assign')}
            className="flex items-center gap-1 bg-acc text-white rounded-lg px-2.5 py-1.5 text-[10px] font-bold min-h-[32px]">
            <Plus className="w-3.5 h-3.5" /> {t('team.assign')}
          </button>
          <button onClick={() => void refresh()} className="p-1.5 text-mute">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      <div className="px-4 pb-2 flex items-center gap-1.5">
        <div className="flex bg-surface border border-line rounded-lg overflow-hidden">
          {(['roster', 'day', 'week', 'agenda'] as const).map((v) => (
            <button key={v} onClick={() => setView(v)}
              className={`px-2.5 py-1 text-[9px] font-semibold ${view === v ? 'bg-ink text-white' : 'text-mute'}`}>
              {t(`team.${v}`)}
            </button>
          ))}
        </div>
        {view !== 'roster' && (
          <div className="flex items-center gap-1 ml-auto">
            <button onClick={() => {
              const d = new Date(`${anchor}T00:00:00`);
              d.setDate(d.getDate() - (view === 'day' ? 1 : view === 'week' ? 7 : 14));
              setAnchor(isoDay(d));
            }} className="p-1 text-mute"><ChevronLeft className="w-4 h-4" /></button>
            <button onClick={() => setAnchor(today)} className="text-[9px] font-bold text-acc">
              {t('calendar.today')}
            </button>
            <button onClick={() => {
              const d = new Date(`${anchor}T00:00:00`);
              d.setDate(d.getDate() + (view === 'day' ? 1 : view === 'week' ? 7 : 14));
              setAnchor(isoDay(d));
            }} className="p-1 text-mute"><ChevronRight className="w-4 h-4" /></button>
          </div>
        )}
      </div>

      {view !== 'roster' && dept && (
        <div className="px-4 pb-2 flex gap-1.5 overflow-x-auto">
          {dept.employees.map((e) => {
            const on = empFilter.has(e.employee_uid);
            return (
              <button key={e.employee_uid}
                onClick={() => {
                  const next = new Set(empFilter);
                  if (on) next.delete(e.employee_uid); else next.add(e.employee_uid);
                  setEmpFilter(next);
                }}
                className={`shrink-0 px-2.5 py-1 rounded-full border text-[9px] font-semibold ${
                  on ? 'bg-acc text-white border-acc' : 'border-line text-sub'}`}>
                {e.name.split(' ')[0]}
              </button>
            );
          })}
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
            className="shrink-0 bg-surface border border-line rounded-full px-2 py-1 text-[9px] font-semibold text-sub">
            <option value="">{t('team.allStatuses')}</option>
            {['assigned', 'in_progress', 'submitted', 'completed', 'cancelled'].map((st) => (
              <option key={st} value={st}>{st.replace('_', ' ')}</option>
            ))}
          </select>
          <select value={priorityFilter} onChange={(e) => setPriorityFilter(e.target.value)}
            className="shrink-0 bg-surface border border-line rounded-full px-2 py-1 text-[9px] font-semibold text-sub">
            <option value="">{t('team.allPriorities')}</option>
            {PRIORITIES.map((p) => <option key={p} value={p}>{t(`priority.${p}`)}</option>)}
          </select>
          <select value={zoneFilter} onChange={(e) => setZoneFilter(e.target.value)}
            className="shrink-0 bg-surface border border-line rounded-full px-2 py-1 text-[9px] font-semibold text-sub">
            <option value="">{t('team.allZones')}</option>
            {zones.map((z) => <option key={z.zone_uid} value={z.zone_uid}>{z.name}</option>)}
          </select>
        </div>
      )}

      <div className="flex-1 px-4 pb-6 space-y-3">
        {view === 'roster' && dept && (
          <div className="space-y-1.5">
            {dept.employees.map((e) => {
              const open = expandedEmp === e.employee_uid;
              const todayWork = work.filter((w) => w.employee_uid === e.employee_uid);
              return (
                <div key={e.employee_uid} className="bg-white border border-line rounded-xl">
                  <button onClick={() => setExpandedEmp(open ? null : e.employee_uid)}
                    className="w-full flex items-center gap-3 px-3 py-2.5 text-left min-h-[44px]">
                    <span className={`w-9 h-9 rounded-full flex items-center justify-center text-[11px] font-bold ${
                      e.is_head ? 'bg-acc text-white' : 'bg-line text-sub'}`}>
                      {initials(e.name)}
                    </span>
                    <span className="flex-1 min-w-0">
                      <span className="block text-[11px] font-semibold text-ink truncate">
                        {e.name}{e.is_head ? ` · ${t('team.head')}` : ''}
                      </span>
                      <span className="block text-[9px] text-mute truncate">{e.job_title ?? ''}</span>
                    </span>
                    <span className="text-[9px] font-bold text-sub shrink-0">
                      {e.open_tasks} {t('team.open')}
                    </span>
                    <ChevronDown className={`w-3.5 h-3.5 text-mute transition-transform ${open ? 'rotate-180' : ''}`} />
                  </button>
                  {open && (
                    <div className="px-3 pb-2.5 space-y-1.5 border-t border-line pt-2">
                      {todayWork.length === 0 ? (
                        <p className="text-[10px] text-mute">{t('calendar.nothingScheduled')}</p>
                      ) : todayWork.map(workRow)}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {view !== 'roster' && days.map((d) => {
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
              {items.length > 0 && <div className="space-y-1.5">{items.map(workRow)}</div>}
            </div>
          );
        })}
        {view !== 'roster' && !loading && work.length === 0 && (
          <div className="flex flex-col items-center gap-2 py-10">
            <CalendarDays className="w-8 h-8 text-mute" />
            <p className="text-[10px] text-mute">{t('calendar.nothingScheduled')}</p>
          </div>
        )}
      </div>

      {sheet === 'assign' && dept && (
        <AssignSheet dept={dept} zones={zones} onClose={() => setSheet(null)}
          onSaved={() => { setSheet(null); void loadWork(); void loadOverview(); }} />
      )}
      {sheet !== null && sheet !== 'assign' && 'edit' in sheet && dept && (
        <AssignSheet dept={dept} zones={zones} editing={sheet.edit} onClose={() => setSheet(null)}
          onSaved={() => { setSheet(null); void loadWork(); }} />
      )}
      {sheet !== null && sheet !== 'assign' && 'reassign' in sheet && dept && (
        <ReassignSheet dept={dept} task={sheet.reassign} onClose={() => setSheet(null)}
          onSaved={() => { setSheet(null); void loadWork(); void loadOverview(); }} />
      )}
    </div>
  );
};
