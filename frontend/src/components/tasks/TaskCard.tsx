import React from 'react';
import { Task } from '../../types';
import { StatusBadge } from '../common/StatusBadge';
import { MapPin, Clock, ArrowUp, AlertOctagon } from 'lucide-react';

interface TaskCardProps {
  task: Task;
  onClick: () => void;
}

/** Subtle priority mark — text + icon, never color alone.
 *  low → nothing, medium → muted word, high → amber, critical → danger. */
const PriorityMark: React.FC<{ priority: Task['priority'] }> = ({ priority }) => {
  if (priority === 'critical') {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-dng">
        <AlertOctagon className="w-3 h-3" />
        Critical
      </span>
    );
  }
  if (priority === 'high') {
    return (
      <span className="inline-flex items-center gap-0.5 text-[10px] font-semibold text-warn">
        <ArrowUp className="w-3 h-3" />
        High
      </span>
    );
  }
  if (priority === 'medium') {
    return <span className="text-[10px] font-medium text-mute">Medium</span>;
  }
  return null;
};

/** Statuses that are self-evident from context — no badge needed. */
const QUIET_STATUSES = new Set(['assigned', 'pending', 'scheduled', 'overdue', 'in_progress']);

export const TaskCard: React.FC<TaskCardProps> = ({ task, onClick }) => {
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
    ? 'No due time set'
    : hasTime
    ? isToday
      ? `Today · ${timeFormatted}`
      : `${dateFormatted} · ${timeFormatted}`
    : isToday
    ? 'Today'
    : dateFormatted;

  const showBadge = !isOverdue && !QUIET_STATUSES.has(task.status);

  return (
    <div
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onClick()}
      className="px-4 py-3.5 cursor-pointer transition-colors hover:bg-soft/70 active:bg-soft"
    >
      {/* Level 1 — category + priority */}
      <div className="flex items-center justify-between gap-2 mb-1">
        <span className="text-[10px] font-medium tracking-[0.08em] uppercase text-mute">
          {task.category}
        </span>
        <PriorityMark priority={task.priority} />
      </div>

      {/* Level 2 — task title */}
      <h3 className="text-[15px] font-semibold text-ink leading-snug mb-1 font-['Space_Grotesk'] line-clamp-2">
        {task.title}
      </h3>

      {/* Level 3 — location · zone, then deadline + status */}
      <div className="flex items-center gap-1 text-[11.5px] text-sub min-w-0">
        <MapPin className="w-3 h-3 text-mute flex-shrink-0" />
        <span className="font-medium text-ink/80 truncate">{task.location_name}</span>
        {task.zone_name && (
          <>
            <span className="text-mute">·</span>
            <span className="truncate">{task.zone_name}</span>
          </>
        )}
      </div>

      <div className="flex items-center justify-between gap-2 mt-1">
        <div className="flex items-center gap-1 text-[11.5px] min-w-0">
          <Clock className={`w-3 h-3 flex-shrink-0 ${isOverdue ? 'text-dng' : 'text-mute'}`} />
          {isOverdue ? (
            <span className="text-dng font-medium truncate">
              Overdue · {timeFormatted || dateFormatted}
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
