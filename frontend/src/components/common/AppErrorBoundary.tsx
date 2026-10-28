import React from 'react';
import { RefreshCw } from 'lucide-react';

interface State {
  crashed: boolean;
}

/**
 * Last-resort crash boundary — catches render errors anywhere in the app
 * and shows a branded recovery screen instead of a white screen. The user
 * reloads; nothing is reported (no telemetry pipeline exists here).
 */
export class AppErrorBoundary extends React.Component<
  React.PropsWithChildren,
  State
> {
  state: State = { crashed: false };

  static getDerivedStateFromError(): State {
    return { crashed: true };
  }

  componentDidCatch(error: unknown, info: React.ErrorInfo) {
    console.error('Unhandled UI error:', error, info.componentStack);
  }

  render() {
    if (!this.state.crashed) return this.props.children;
    return (
      <div className="flex-1 flex flex-col items-center justify-center bg-white p-6 text-center">
        <div className="w-12 h-12 rounded-2xl bg-[#667174] flex items-center justify-center text-white mb-3 shadow-sm">
          <span className="font-bold text-lg font-['Space_Grotesk']">A</span>
        </div>
        <p className="text-base font-semibold text-[#20292C] mb-1">
          Something went wrong
        </p>
        <p className="text-sm text-[#667174] mb-6 max-w-xs">
          The app hit an unexpected problem. Your work is safe — reload to
          continue where you left off.
        </p>
        <button
          onClick={() => window.location.reload()}
          className="inline-flex items-center gap-2 px-6 py-2.5 rounded-xl bg-[#33B059] text-white font-semibold text-sm active:scale-95 transition-all"
        >
          <RefreshCw className="w-4 h-4" />
          Reload app
        </button>
      </div>
    );
  }
}
