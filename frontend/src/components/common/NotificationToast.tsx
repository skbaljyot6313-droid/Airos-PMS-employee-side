import React, { useEffect } from 'react';
import { Bell, X, ChevronRight } from 'lucide-react';
import { StaffNotification } from '../../types';

interface NotificationToastProps {
  notification: StaffNotification;
  /** Tap — deep-links to the task/ticket; also dismissed. */
  onOpen: (n: StaffNotification) => void;
  onDismiss: (n: StaffNotification) => void;
}

const AUTO_DISMISS_MS = 6000;

/**
 * In-app notification popup — slides in at the top of the frame, auto-
 * dismisses, taps deep-link to the work item. One at a time; the owner
 * queues multiple arrivals.
 */
export const NotificationToast: React.FC<NotificationToastProps> = ({
  notification,
  onOpen,
  onDismiss,
}) => {
  useEffect(() => {
    const t = setTimeout(() => onDismiss(notification), AUTO_DISMISS_MS);
    return () => clearTimeout(t);
  }, [notification, onDismiss]);

  const hasTarget = notification.taskId !== null || notification.ticketId !== null;

  return (
    <div
      className="absolute top-0 inset-x-0 z-[90] px-4 pt-3 pointer-events-none"
      role="status"
      aria-live="polite"
    >
      <div
        className="pointer-events-auto w-full max-w-sm mx-auto bg-white rounded-2xl shadow-xl border border-[#E4E8E6] flex items-start gap-3 p-4 cursor-pointer active:scale-[0.98] transition-transform"
        onClick={() => onOpen(notification)}
      >
        <div className="w-9 h-9 rounded-xl bg-[#E8F7ED] text-[#33B059] flex items-center justify-center flex-shrink-0">
          <Bell className="w-4.5 h-4.5" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-[13px] font-bold text-[#20292C] font-['Space_Grotesk'] leading-tight">
            {notification.title}
          </p>
          <p className="text-xs text-[#667174] mt-0.5 line-clamp-2">
            {notification.body}
          </p>
          {hasTarget && (
            <p className="text-[11px] font-semibold text-[#33B059] mt-1 flex items-center gap-0.5">
              Tap to view <ChevronRight className="w-3 h-3" />
            </p>
          )}
        </div>
        <button
          aria-label="Dismiss"
          className="text-[#8D999C] hover:text-[#667174] p-1 -m-1 flex-shrink-0"
          onClick={(e) => {
            e.stopPropagation();
            onDismiss(notification);
          }}
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
};
