import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useAuth } from '../../context/AuthContext';
import { Task, TaskBucket } from '../../types';
import { fetchTasksApi, taskBucket } from '../../api/tasks';
import { businessDate } from '../../api/attendance';
import { errorMessage } from '../../api/client';
import { subscribeRealtimeEvents } from '../../services/realtime';
import { perfMarkOnce } from '../../utils/perf';
import { TaskCard } from '../../components/tasks/TaskCard';
import { EmptyState, ErrorState, LoadingState } from '../../components/common/FeedbackStates';
import { RefreshCw, MapPin, Building2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export interface TaskListSelection {
  id: string;
  kind: 'task' | 'maintenance';
}

interface TasksScreenProps {
  onSelectTask: (selection: TaskListSelection) => void;
  onTasksCountChange?: (count: number) => void;
}

export const TasksScreen: React.FC<TasksScreenProps> = ({ onSelectTask, onTasksCountChange }) => {
  const { employee, company } = useAuth();
  const { t } = useTranslation();
  const [activeBucket, setActiveBucket] = useState<TaskBucket>('to_do');
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const loadInFlight = useRef(false);
  const refreshPending = useRef(false);

  const loadTasks = useCallback(async (isRefresh = false) => {
    if (loadInFlight.current) {
      refreshPending.current ||= isRefresh;
      return;
    }
    loadInFlight.current = true;
    try {
      if (isRefresh) setRefreshing(true);
      else setLoading(true);
      setError(null);

      // Fetch operational tasks AND assigned maintenance tickets
      const data = await fetchTasksApi(employee?.id);
      setTasks(data);
      perfMarkOnce('t6_data');

      const todoCount = data.filter((t) => taskBucket(t.status) === 'to_do').length;
      if (onTasksCountChange) {
        onTasksCountChange(todoCount);
      }
    } catch (err: unknown) {
      setError(errorMessage(err, t('tasks.loadError')));
    } finally {
      loadInFlight.current = false;
      setLoading(false);
      setRefreshing(false);
      if (refreshPending.current) {
        refreshPending.current = false;
        void loadTasks(true);
      }
    }
  }, [onTasksCountChange]);

  useEffect(() => {
    loadTasks();
    return () => { refreshPending.current = false; };
  }, [loadTasks]);

  // Realtime invalidation — task/maintenance events refresh the list
  // (payloads are hints only; the API stays authoritative).
  useEffect(
    () =>
      subscribeRealtimeEvents(['task.', 'maintenance.', 'ticket.'], () =>
        loadTasks(true),
      ),
    [loadTasks],
  );

  // Completed bucket = only items that reached a terminal state today
  // (business/IST wall-clock date, matching attendance conventions).
  const today = businessDate();
  const completedToday = (t: Task): boolean => {
    if (taskBucket(t.status) !== 'done') return false;
    if (!t.completed_at) return false;
    const d = new Date(t.completed_at);
    return !Number.isNaN(d.getTime()) && businessDate(d) === today;
  };

  // Overdue work is management-visible only — the backend's authoritative
  // 'overdue' status marks items out of the employee's actionable set.
  // Valid active assignments and completed history are untouched.
  const visibleTasks = tasks.filter((t) => t.status !== 'overdue');

  // Filter tasks into the active bucket
  const filteredTasks =
    activeBucket === 'done'
      ? visibleTasks.filter(completedToday)
      : visibleTasks.filter((t) => taskBucket(t.status) === activeBucket);

  const todoCount = visibleTasks.filter((t) => taskBucket(t.status) === 'to_do').length;
  const inReviewCount = tasks.filter((t) => taskBucket(t.status) === 'in_review').length;
  const doneCount = tasks.filter(completedToday).length;

  // Greeting based on current time
  const hour = new Date().getHours();
  const greeting =
    hour < 12
      ? t('greeting.morning')
      : hour < 17
      ? t('greeting.afternoon')
      : t('greeting.evening');
  const firstName = employee?.name ? employee.name.split(' ')[0] : t('greeting.staff');

  const buckets: { id: TaskBucket; label: string; count: number }[] = [
    { id: 'to_do', label: t('tasks.bucketToDo'), count: todoCount },
    { id: 'in_review', label: t('tasks.bucketInReview'), count: inReviewCount },
    { id: 'done', label: t('tasks.bucketDone'), count: doneCount },
  ];

  return (
    <div className="flex-1 flex flex-col bg-app overflow-y-auto">
      {/* Editorial header — greeting, title, refresh, context, underline tabs */}
      <div className="bg-surface border-b border-line sticky top-0 z-20">
        <div className="px-4 pt-3 pb-1">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <span className="text-[11px] font-normal text-mute block">
                {greeting}, {firstName}
              </span>
              <h1 className="text-[22px] font-bold tracking-[-0.02em] text-ink font-['Space_Grotesk'] leading-tight">
                {t('tasks.yourTasks')}
              </h1>
            </div>

            <button
              onClick={() => loadTasks(true)}
              disabled={refreshing}
              className="p-2 -mr-1 mt-0.5 rounded-md text-mute hover:text-ink hover:bg-soft active:scale-95 transition-all"
              aria-label={t('tasks.refresh')}
            >
              <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin text-acc' : ''}`} />
            </button>
          </div>

          {/* Property · zone metadata — single quiet context line */}
          <div className="flex items-center gap-1.5 text-[11px] text-sub mt-1 min-w-0">
            <Building2 className="w-3 h-3 text-mute flex-shrink-0" />
            <span className="font-medium text-ink truncate">
              {company?.brand_name || company?.name || t('tasks.company')}
            </span>
            <span className="text-mute">·</span>
            <MapPin className="w-3 h-3 text-mute flex-shrink-0" />
            <span className="truncate">
              {employee?.zone_name || t('tasks.zoneNotAssigned')}
            </span>
          </div>
        </div>

        {/* Status tabs — hairline separator, lime underline on active */}
        <div
          role="tablist"
          aria-label={t('tasks.statusAria')}
          className="flex items-stretch px-2 mt-2"
        >
          {buckets.map((b) => {
            const active = activeBucket === b.id;
            return (
              <button
                key={b.id}
                role="tab"
                aria-selected={active}
                onClick={() => setActiveBucket(b.id)}
                className={`relative flex-1 px-2 pb-2 pt-1 text-[11px] transition-colors flex items-center justify-center gap-1.5 ${
                  active ? 'text-ink font-semibold' : 'text-mute font-medium hover:text-sub'
                }`}
              >
                <span>{b.label}</span>
                <span className={`text-[10px] tabular-nums font-medium ${active ? 'text-acc' : 'text-mute'}`}>
                  {b.count}
                </span>
                <span
                  aria-hidden
                  className={`absolute bottom-[-1px] left-3 right-3 h-[2.5px] rounded-full transition-colors ${
                    active ? 'bg-lime' : 'bg-transparent'
                  }`}
                />
              </button>
            );
          })}
        </div>
      </div>

      {/* Task List Content — editorial rows separated by hairlines */}
      <div className="flex-1">
        {loading ? (
          <LoadingState message={t('tasks.loading')} />
        ) : error ? (
          <ErrorState message={error} onRetry={() => loadTasks(false)} />
        ) : filteredTasks.length === 0 ? (
          <EmptyState
            type="tasks"
            title={
              activeBucket === 'to_do'
                ? t('tasks.emptyToDo')
                : activeBucket === 'in_review'
                ? t('tasks.emptyInReview')
                : t('tasks.emptyDone')
            }
            description={
              activeBucket === 'to_do'
                ? t('tasks.emptyToDoDesc')
                : activeBucket === 'in_review'
                ? t('tasks.emptyInReviewDesc')
                : t('tasks.emptyDoneDesc')
            }
            actionLabel={t('common.refreshList')}
            onAction={() => loadTasks(true)}
          />
        ) : (
          <div className="px-4 pt-3 pb-8 space-y-2.5">
            {filteredTasks.map((task) => (
              <TaskCard
                key={task.id}
                task={task}
                onClick={() => onSelectTask({ id: task.id, kind: task.kind || 'task' })}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
