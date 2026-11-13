import React from 'react';
import { useTranslation } from 'react-i18next';
import { Task } from '../../types';
import { StatusBadge } from '../common/StatusBadge';
import { SpeakButton } from '../common/SpeakButton';
import { MapPin, Clock, ArrowUp, AlertOctagon } from 'lucide-react';

interface TaskCardProps {
  task: Task;
  onClick: () => void;
}

/** Subtle priority mark — text + icon, never color alone.
 *  low → nothing, medium → muted word, high → amber, critical → danger. */
const PriorityMark: React.FC<{ priority: Task['priority'] }> = ({ priority }) => {
  const { t } = useTranslation();
  if (priority === 'critical') {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-dng">
        <AlertOctagon className="w-3 h-3" />
        {t('priority.critical')}
      </span>
    );
  }
  if (priority === 'high' || priority === 'urgent') {
    return (
      <span className="inline-flex items-center gap-0.5 text-[10px] font-semibold text-warn">
        <ArrowUp className="w-3 h-3" />
        {t('priority.high')}
      </span>
    );
  }
  if (priority === 'medium') {
    return (
      <span className="text-[10px] font-medium text-mute">
        {t('priority.medium')}
      </span>
    );
  }
  return null;
};

/** Statuses that are self-evident from context — no badge needed. */
const QUIET_STATUSES = new Set(['assigned', 'pending', 'scheduled', 'overdue', 'in_progress']);

export const TaskCard: React.FC<TaskCardProps> = ({ task, onClick }) => {
  const { t } = useTranslation();
  // Overdue: backend status or a clock-time due in the past, still actionable
  const dueTime = task.due_at ? new Date(task.due_at).getTime() : null;
  const isOverdue =
    task.status === 'overdue' ||
    (!!dueTime && dueTime < Date.now() && !['completed', 'cancelled', 'abandoned', 'submitted'].includes(task.status));

  const dueDate = task.due_at ? new Date(task.due_at) : task.due_date ? new Date(`${task.due_date}T00:00:00`) : null;
  const isToday = !!dueDate && new Date().toDateString() === dueDate.toDateString();
  const hasTime = !!task.due_at;
  const timeFormatted = hasTime ? dueDate!.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
  const dateFormatted = dueDate ? dueDate.toLocaleDateString([], { month: 'short', day: 'numeric' }) : '—';
  const dueLabel = !dueDate
    ? t('tasks.noDueTime')
    : hasTime
    ? isToday
      ? `${t('tasks.today')} · ${timeFormatted}`
      : `${dateFormatted} · ${timeFormatted}`
    : isToday
    ? t('tasks.today')
    : dateFormatted;

  const showBadge = !isOverdue && !QUIET_STATUSES.has(task.status);

  return (
    <div
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onClick()}
      className="bg-surface border border-line rounded-[14px] p-3 cursor-pointer transition-colors hover:border-sub/40 active:scale-[0.99] active:bg-soft/60"
    >
      {/* Level 1 — category + priority */}
      <div className="flex items-center justify-between gap-2 mb-1">
        <span className="text-[10px] font-semibold tracking-[0.08em] uppercase text-mute">
          {task.category}
        </span>
        <div className="flex items-center gap-1 flex-shrink-0">
          <PriorityMark priority={task.priority} />
          <SpeakButton task={task} />
        </div>
      </div>

      {/* Level 2 — task title */}
      <h3 className="text-[15px] font-semibold text-ink leading-snug mb-1.5 font-['Space_Grotesk'] line-clamp-2">
        {task.title}
      </h3>

      {/* Level 3 — location · zone, then deadline + status */}
      <div className="flex items-center gap-1.5 text-xs text-sub min-w-0 mb-1.5">
        <MapPin className="w-3.5 h-3.5 text-mute flex-shrink-0" />
        <span className="font-medium text-ink/80 truncate">{task.location_name}</span>
        {task.zone_name && (
          <>
            <span className="text-mute">·</span>
            <span className="truncate">{task.zone_name}</span>
          </>
        )}
      </div>

      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-xs min-w-0">
          <Clock className={`w-3.5 h-3.5 flex-shrink-0 ${isOverdue ? 'text-dng' : 'text-mute'}`} />
          {isOverdue ? (
            <span className="text-dng font-medium truncate">
              {t('tasks.overduePrefix')} · {timeFormatted || dateFormatted}
            </span>
          ) : (
            <span className="text-sub truncate">{dueLabel}</span>
          )}
        </div>
        {showBadge && <StatusBadge status={task.status} size="sm" />}
      </div>
    </div>
  );
};
