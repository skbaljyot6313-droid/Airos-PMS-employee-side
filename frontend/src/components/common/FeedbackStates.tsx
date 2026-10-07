import React from 'react';
import { ClipboardList, Wrench, AlertTriangle, RefreshCw } from 'lucide-react';
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
    <div className="flex flex-col items-center justify-center p-8 text-center my-6">
      <div className="w-14 h-14 rounded-2xl bg-[#F0F4F2] border border-[#E4E8E6] flex items-center justify-center text-[#667174] mb-3">
        <Icon className="w-7 h-7 stroke-[1.75]" />
      </div>
      <h3 className="text-base font-semibold text-[#20292C] font-['Space_Grotesk'] mb-1">
        {title}
      </h3>
      <p className="text-xs text-[#667174] max-w-[260px] leading-relaxed mb-4">
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
  message = "Couldn't connect to AiROS. Check your internet connection and try again.",
  onRetry,
}) => {
  return (
    <div className="flex flex-col items-center justify-center p-6 text-center my-8 bg-[#FCEBEA]/40 rounded-2xl border border-[#F8C8C6] mx-4">
      <div className="w-12 h-12 rounded-xl bg-[#FCEBEA] flex items-center justify-center text-[#D9534F] mb-3">
        <AlertTriangle className="w-6 h-6 stroke-[2]" />
      </div>
      <h3 className="text-sm font-semibold text-[#20292C] mb-1 font-['Space_Grotesk']">
        Operational Sync Issue
      </h3>
      <p className="text-xs text-[#667174] max-w-[280px] leading-relaxed mb-4">
        {message}
      </p>
      {onRetry && (
        <SecondaryButton
          size="sm"
          fullWidth={false}
          onClick={onRetry}
          icon={<RefreshCw className="w-3.5 h-3.5" />}
        >
          Retry Connection
        </SecondaryButton>
      )}
    </div>
  );
};

export const LoadingState: React.FC<{ message?: string }> = ({
  message = 'Loading operational data...',
}) => {
  return (
    <div className="p-4 space-y-3 animate-pulse">
      <div className="h-28 bg-[#ECEEED] rounded-2xl w-full" />
      <div className="h-28 bg-[#ECEEED] rounded-2xl w-full" />
      <div className="h-28 bg-[#ECEEED] rounded-2xl w-full" />
      <p className="text-center text-xs text-[#8D999C] pt-2">{message}</p>
    </div>
  );
};
