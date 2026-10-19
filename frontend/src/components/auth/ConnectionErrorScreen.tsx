import React from 'react';

/**
 * Retryable connection-error screen shown when session restore fails on
 * a network/5xx path (status-0, timeout). Tokens are preserved — the
 * user retries, or signs out to a different account. Never shown for
 * real 401/403 session expiry (those land on Login as before).
 */
export const ConnectionErrorScreen: React.FC<{
  message: string;
  onRetry: () => void;
  onLogout: () => void;
}> = ({ message, onRetry, onLogout }) => (
  <div className="flex-1 flex flex-col items-center justify-center bg-white p-6">
    <div className="w-12 h-12 rounded-2xl bg-[#667174] flex items-center justify-center text-white mb-3 shadow-sm">
      <span className="font-bold text-lg font-['Space_Grotesk']">A</span>
    </div>
    <p className="text-base font-semibold text-[#20292C] mb-1">Can't reach the server</p>
    <p className="text-sm text-[#667174] text-center mb-6 max-w-xs">{message}</p>
    <button
      onClick={onRetry}
      className="px-6 py-2.5 rounded-xl bg-[#33B059] text-white font-semibold text-sm active:scale-95 transition-all"
    >
      Try again
    </button>
    <button onClick={onLogout} className="mt-3 text-sm text-[#667174] underline">
      Sign in with a different account
    </button>
  </div>
);
