import React from 'react';
import { TaskPriority, MaintenancePriority } from '../../types';
import { AlertCircle, AlertOctagon, ArrowUp, ArrowDown } from 'lucide-react';

interface PriorityBadgeProps {
  priority: TaskPriority | MaintenancePriority;
  size?: 'sm' | 'md';
}

export const PriorityBadge: React.FC<PriorityBadgeProps> = ({ priority, size = 'sm' }) => {
  const isSm = size === 'sm';

  const config: Record<
    string,
    { label: string; bg: string; text: string; border: string; icon: React.ReactNode }
  > = {
    critical: {
      label: 'Critical',
      bg: 'bg-[#FCEBEA]',
      text: 'text-[#D9534F]',
      border: 'border-[#F8C8C6]',
      icon: <AlertOctagon className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
    high: {
      label: 'High',
      bg: 'bg-[#FFF3E8]',
      text: 'text-[#D0651A]',
      border: 'border-[#FDD9BE]',
      icon: <ArrowUp className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
    medium: {
      label: 'Medium',
      bg: 'bg-[#F7F8F6]',
      text: 'text-[#667174]',
      border: 'border-[#E4E8E6]',
      icon: <AlertCircle className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
    low: {
      label: 'Low',
      bg: 'bg-[#F7F8F6]',
      text: 'text-[#8D999C]',
      border: 'border-[#E4E8E6]',
      icon: <ArrowDown className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
  };

  const current = config[priority] || config.medium;

  return (
    <span
      className={`inline-flex items-center gap-1 font-medium rounded border ${current.bg} ${current.text} ${current.border} ${
        isSm ? 'px-1.5 py-0.5 text-[11px]' : 'px-2 py-0.5 text-xs'
      }`}
    >
      {current.icon}
      <span>{current.label}</span>
    </span>
  );
};
