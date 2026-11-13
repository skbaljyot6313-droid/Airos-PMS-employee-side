import React from 'react';
import { useTranslation } from 'react-i18next';
import { TaskStatus, MaintenanceStatus } from '../../types';
import { Clock, CheckCircle2, AlertTriangle, Send, RefreshCw, AlertCircle } from 'lucide-react';

interface StatusBadgeProps {
  status: TaskStatus | MaintenanceStatus | 'overdue';
  size?: 'sm' | 'md';
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status, size = 'md' }) => {
  const { t } = useTranslation();
  const isSm = size === 'sm';

  const config: Record<
    string,
    { label: string; bg: string; text: string; icon: React.ReactNode }
  > = {
    assigned: {
      label: t('status.assigned'),
      bg: 'bg-soft',
      text: 'text-ink',
      icon: <Clock className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
    pending: {
      label: t('status.pending'),
      bg: 'bg-soft',
      text: 'text-sub',
      icon: <Clock className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
    in_progress: {
      label: t('status.in_progress'),
      bg: 'bg-accsoft',
      text: 'text-acc',
      icon: <RefreshCw className={`${isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} animate-spin`} />,
    },
    reopened: {
      label: t('status.reopened'),
      bg: 'bg-warnsoft',
      text: 'text-warn',
      icon: <AlertTriangle className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
    submitted: {
      label: t('status.submitted'),
      bg: 'bg-infosoft',
      text: 'text-info',
      icon: <Send className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
    completed: {
      label: t('status.completed'),
      bg: 'bg-accsoft',
      text: 'text-ok',
      icon: <CheckCircle2 className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
    cancelled: {
      label: t('status.cancelled'),
      bg: 'bg-soft',
      text: 'text-mute',
      icon: <AlertCircle className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
    resolved: {
      label: t('status.resolved'),
      bg: 'bg-accsoft',
      text: 'text-ok',
      icon: <CheckCircle2 className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
    on_hold: {
      label: t('status.on_hold'),
      bg: 'bg-warnsoft',
      text: 'text-warn',
      icon: <Clock className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
    abandoned: {
      label: t('status.abandoned'),
      bg: 'bg-soft',
      text: 'text-mute',
      icon: <AlertCircle className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
    scheduled: {
      label: t('status.scheduled'),
      bg: 'bg-soft',
      text: 'text-sub',
      icon: <Clock className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
    reported: {
      label: t('status.reported'),
      bg: 'bg-warnsoft',
      text: 'text-warn',
      icon: <Clock className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
    overdue: {
      label: t('status.overdue'),
      bg: 'bg-dngsoft',
      text: 'text-dng',
      icon: <AlertTriangle className={isSm ? 'w-3 h-3' : 'w-3.5 h-3.5'} />,
    },
  };

  const current = config[status] || config.assigned;

  return (
    <span
      className={`inline-flex items-center gap-1 font-medium rounded-full ${current.bg} ${current.text} ${
        isSm ? 'px-2 py-0.5 text-[10px]' : 'px-2.5 py-1 text-xs'
      }`}
    >
      {current.icon}
      <span>{current.label}</span>
    </span>
  );
};
