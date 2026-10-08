import React from 'react';
import { TaskStatus, MaintenanceStatus } from '../../types';
import { Clock, CheckCircle2, AlertTriangle, Send, RefreshCw, AlertCircle } from 'lucide-react';

interface StatusBadgeProps {
  status: TaskStatus | MaintenanceStatus | 'overdue';
  size?: 'sm' | 'md';
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status, size = 'md' }) => {
  const isSm = size === 'sm';

  const config: Record<
    string,
    { label: string; bg: string; text: string; border: string; icon: React.ReactNode }
  > = {
    assigned: {
      label: 'Assigned',
      bg: 'bg-[#F0F4F2]',
      text: 'text-[#20292C]',
      border: 'border-[#D2D8D6]',
      icon: <Clock className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
    pending: {
      label: 'Pending',
      bg: 'bg-[#F0F4F2]',
      text: 'text-[#667174]',
      border: 'border-[#D2D8D6]',
      icon: <Clock className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
    in_progress: {
      label: 'In Progress',
      bg: 'bg-[#E8F7ED]',
      text: 'text-[#278B46]',
      border: 'border-[#A3E5B7]',
      icon: <RefreshCw className={`${isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} animate-spin`} />,
    },
    reopened: {
      label: 'Returned',
      bg: 'bg-[#FDF6E8]',
      text: 'text-[#B87C10]',
      border: 'border-[#F5DEAB]',
      icon: <AlertTriangle className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
    submitted: {
      label: 'In Review',
      bg: 'bg-[#EEF3FF]',
      text: 'text-[#2B5DD8]',
      border: 'border-[#C2D4FF]',
      icon: <Send className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
    completed: {
      label: 'Completed',
      bg: 'bg-[#E8F7ED]',
      text: 'text-[#278B46]',
      border: 'border-[#BBECCC]',
      icon: <CheckCircle2 className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
    cancelled: {
      label: 'Cancelled',
      bg: 'bg-[#F5F5F5]',
      text: 'text-[#8D999C]',
      border: 'border-[#E4E8E6]',
      icon: <AlertCircle className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
    resolved: {
      label: 'Resolved',
      bg: 'bg-[#E8F7ED]',
      text: 'text-[#278B46]',
      border: 'border-[#BBECCC]',
      icon: <CheckCircle2 className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
    on_hold: {
      label: 'On Hold',
      bg: 'bg-[#FDF6E8]',
      text: 'text-[#B87C10]',
      border: 'border-[#F5DEAB]',
      icon: <Clock className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
    abandoned: {
      label: 'Abandoned',
      bg: 'bg-[#F5F5F5]',
      text: 'text-[#8D999C]',
      border: 'border-[#E4E8E6]',
      icon: <AlertCircle className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
    scheduled: {
      label: 'Scheduled',
      bg: 'bg-[#F0F4F2]',
      text: 'text-[#667174]',
      border: 'border-[#D2D8D6]',
      icon: <Clock className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
    reported: {
      label: 'Reported',
      bg: 'bg-[#FDF6E8]',
      text: 'text-[#B87C10]',
      border: 'border-[#F5DEAB]',
      icon: <Clock className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
    overdue: {
      label: 'Overdue',
      bg: 'bg-[#FCEBEA]',
      text: 'text-[#D9534F]',
      border: 'border-[#F8C8C6]',
      icon: <AlertTriangle className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
  };

  const current = config[status] || config.assigned;

  return (
    <span
      className={`inline-flex items-center gap-1.5 font-medium rounded-full border ${current.bg} ${current.text} ${current.border} ${
        isSm ? 'px-2 py-0.5 text-[11px]' : 'px-2.5 py-1 text-xs'
      }`}
    >
      {current.icon}
      <span>{current.label}</span>
    </span>
  );
};
