import React from 'react';
import { Task } from '../../types';
import { StatusBadge } from '../common/StatusBadge';
import { PriorityBadge } from '../common/PriorityBadge';
import { MapPin, Clock } from 'lucide-react';

interface TaskCardProps {
  task: Task;
  onClick: () => void;
}

export const TaskCard: React.FC<TaskCardProps> = ({ task, onClick }) => {
  // Overdue: backend status or a clock-time due in the past, still actionable
  const dueTime = task.due_at ? new Date(task.due_at).getTime() : null;
  const isOverdue =
    task.status === 'overdue' ||
    (!!dueTime && dueTime < Date.now() && !['completed', 'cancelled', 'submitted'].includes(task.status));

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

  return (
    <div
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onClick()}
      className="bg-white rounded-2xl p-4 border border-[#E4E8E6] hover:border-[#D2D8D6] transition-all active:scale-[0.99] cursor-pointer shadow-[0_1px_3px_rgba(0,0,0,0.03)]"
    >
      {/* Top category & priority */}
      <div className="flex items-center justify-between gap-2 mb-2">
        <span className="text-[11px] font-bold tracking-wider uppercase text-[#667174]">
          {task.category}
        </span>
        <div className="flex items-center gap-1.5">
          <PriorityBadge priority={task.priority} />
        </div>
      </div>

      {/* Task title */}
      <h3 className="text-[16px] font-semibold text-[#20292C] leading-snug mb-1.5 font-['Space_Grotesk']">
        {task.title}
      </h3>

      {/* Location */}
      <div className="flex items-center gap-1.5 text-xs text-[#667174] mb-3">
        <MapPin className="w-3.5 h-3.5 text-[#8D999C] flex-shrink-0" />
        <span className="font-medium text-[#20292C]">{task.location_name}</span>
        <span className="text-[#8D999C]">·</span>
        <span>{task.zone_name}</span>
      </div>

      {/* Bottom due date & status */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-xs">
          <Clock className={`w-3.5 h-3.5 ${isOverdue ? 'text-[#D9534F]' : 'text-[#8D999C]'}`} />
          <span className={isOverdue ? 'text-[#D9534F] font-semibold' : 'text-[#667174]'}>
            {isOverdue ? `Overdue (${timeFormatted})` : dueLabel}
          </span>
        </div>
        <StatusBadge status={isOverdue ? 'overdue' : task.status} size="sm" />
      </div>
    </div>
  );
};
