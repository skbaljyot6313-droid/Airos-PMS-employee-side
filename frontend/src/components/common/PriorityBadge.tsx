import React from 'react';
import { useTranslation } from 'react-i18next';
import { TaskPriority, MaintenancePriority } from '../../types';
import { AlertCircle, AlertOctagon, ArrowUp, ArrowDown } from 'lucide-react';

interface PriorityBadgeProps {
  priority: TaskPriority | MaintenancePriority;
  size?: 'sm' | 'md';
}

export const PriorityBadge: React.FC<PriorityBadgeProps> = ({ priority, size = 'sm' }) => {
  const { t } = useTranslation();
  const isSm = size === 'sm';

  const config: Record<
    string,
    { label: string; bg: string; text: string; icon: React.ReactNode }
  > = {
    critical: {
      label: t('priority.critical'),
      bg: 'bg-dngsoft',
      text: 'text-dng',
      icon: <AlertOctagon className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
    high: {
      label: t('priority.high'),
      bg: 'bg-warnsoft',
      text: 'text-warn',
      icon: <ArrowUp className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
    medium: {
      label: t('priority.medium'),
      bg: 'bg-soft',
      text: 'text-sub',
      icon: <AlertCircle className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
    low: {
      label: t('priority.low'),
      bg: 'bg-soft',
      text: 'text-mute',
      icon: <ArrowDown className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
  };

  const current = config[priority] || config.medium;

  return (
    <span
      className={`inline-flex items-center gap-1 font-medium rounded-md ${current.bg} ${current.text} ${
        isSm ? 'px-1.5 py-0.5 text-[10px]' : 'px-2 py-0.5 text-xs'
      }`}
    >
      {current.icon}
      <span>{current.label}</span>
    </span>
  );
};
