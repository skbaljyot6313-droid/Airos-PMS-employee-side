import React from 'react';
import { useTranslation } from 'react-i18next';
import { ClipboardList, Wrench, AlertTriangle, RefreshCw, WifiOff } from 'lucide-react';
import { SecondaryButton } from './Buttons';

interface EmptyStateProps {
  title: string;
  description: string;
  type?: 'tasks' | 'maintenance' | 'general';
  actionLabel?: string;
  onAction?: () => void;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  title,
  description,
  type = 'tasks',
  actionLabel,
  onAction,
}) => {
  const Icon = type === 'maintenance' ? Wrench : ClipboardList;

  return (
    <div className="flex flex-col items-center justify-center px-6 py-8 text-center">
      <div className="w-11 h-11 rounded-xl bg-soft flex items-center justify-center text-mute mb-3">
        <Icon className="w-5 h-5 stroke-[1.75]" />
      </div>
      <h3 className="text-sm font-semibold text-ink font-['Space_Grotesk'] mb-1">
        {title}
      </h3>
      <p className="text-xs text-sub max-w-[260px] leading-relaxed mb-4">
        {description}
      </p>
      {actionLabel && onAction && (
        <SecondaryButton size="sm" fullWidth={false} onClick={onAction}>
          {actionLabel}
        </SecondaryButton>
      )}
    </div>
  );
};

interface ErrorStateProps {
  message?: string;
  onRetry?: () => void;
}

export const ErrorState: React.FC<ErrorStateProps> = ({
  message,
  onRetry,
}) => {
  const { t } = useTranslation();
  const msg = message ?? t('errors.connectionFailed');
  const [offline, setOffline] = React.useState(
    () => typeof navigator !== 'undefined' && navigator.onLine === false
  );

  React.useEffect(() => {
    const handleOnline = () => {
      setOffline(false);
      // Connectivity is back — retry the failed load automatically.
      onRetry?.();
    };
    const handleOffline = () => setOffline(true);
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, [onRetry]);

  return (
    <div className="flex flex-col items-center justify-center px-5 py-6 text-center mx-4 my-4 bg-surface rounded-xl border border-line">
      <div className="w-10 h-10 rounded-full bg-dngsoft flex items-center justify-center text-dng mb-3">
        {offline ? (
          <WifiOff className="w-5 h-5 stroke-[2]" />
        ) : (
          <AlertTriangle className="w-5 h-5 stroke-[2]" />
        )}
      </div>
      <h3 className="text-sm font-semibold text-ink mb-1 font-['Space_Grotesk']">
        {offline ? t('errors.offlineTitle') : t('errors.syncIssue')}
      </h3>
      <p className="text-xs text-sub max-w-[280px] leading-relaxed mb-4">
        {offline
          ? t('errors.offlineDesc')
          : msg}
      </p>
      {onRetry && (
        <SecondaryButton
          size="sm"
          fullWidth={false}
          onClick={onRetry}
          icon={<RefreshCw className="w-3.5 h-3.5" />}
        >
          {offline ? t('common.tryAgain') : t('errors.retryConnection')}
        </SecondaryButton>
      )}
    </div>
  );
};

/** Skeleton row matching the real task-row footprint. */
const SkeletonRow: React.FC = () => (
  <div className="px-4 py-3">
    <div className="flex items-center justify-between mb-2">
      <div className="h-2.5 w-16 rounded bg-soft" />
      <div className="h-2.5 w-10 rounded bg-soft" />
    </div>
    <div className="h-4 w-3/4 rounded bg-soft mb-2" />
    <div className="h-3 w-1/2 rounded bg-soft mb-1.5" />
    <div className="h-3 w-1/3 rounded bg-soft" />
  </div>
);

export const LoadingState: React.FC<{ message?: string }> = ({
  message,
}) => {
  const { t } = useTranslation();
  const msg = message ?? t('errors.loadingDefault');
  return (
    <div className="divide-y divide-line animate-pulse" aria-busy="true" aria-label={msg}>
      <SkeletonRow />
      <SkeletonRow />
      <SkeletonRow />
      <SkeletonRow />
      <SkeletonRow />
    </div>
  );
};
