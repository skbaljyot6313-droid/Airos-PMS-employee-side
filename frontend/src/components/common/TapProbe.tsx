import React, { useEffect, useRef, useState } from 'react';

interface ProbeEvent {
  t: string;
  msg: string;
}

const MAX = 10;

/**
 * TEMPORARY diagnostic — records pointer events, route transitions and JS
 * errors into a small on-screen log so we can see where the tap-to-detail
 * chain breaks on a physical device (no USB debugging needed).
 * Remove once the tap bug is identified.
 */
export const TapProbe: React.FC<{ route: string }> = ({ route }) => {
  const [events, setEvents] = useState<ProbeEvent[]>([]);
  const [open, setOpen] = useState(true);
  const buf = useRef<ProbeEvent[]>([]);

  const push = (msg: string) => {
    const ev = { t: new Date().toLocaleTimeString([], { hour12: false }), msg };
    buf.current = [...buf.current.slice(-MAX + 1), ev];
    setEvents(buf.current);
    console.log('[TapProbe]', msg);
  };

  // Route transitions
  useEffect(() => {
    push(`route=${route}`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route]);

  // Pointer + click + errors, capture phase
  useEffect(() => {
    const describe = (el: EventTarget | null): string => {
      const e = el as HTMLElement | null;
      if (!e || !e.closest) return 'non-dom';
      const tag = e.tagName?.toLowerCase() ?? '?';
      const role = e.getAttribute?.('role');
      const card = e.closest('[role="button"],button,a,[data-taskid]');
      const cardTag = card ? `${(card as HTMLElement).tagName?.toLowerCase()}:${(card as HTMLElement).className?.slice?.(0, 30)}` : 'none';
      return `${tag}${role ? `[${role}]` : ''} card≈${cardTag}`;
    };
    const pd = (e: PointerEvent) => push(`down @${Math.round(e.clientX)},${Math.round(e.clientY)} ${describe(e.target)}`);
    const cl = (e: MouseEvent) => push(`CLICK ${describe(e.target)}`);
    const err = (e: ErrorEvent) => push(`JSERR ${e.message?.slice(0, 80)}`);
    const rej = (e: PromiseRejectionEvent) => push(`REJ ${String(e.reason)?.slice(0, 80)}`);
    window.addEventListener('pointerdown', pd, true);
    window.addEventListener('click', cl, true);
    window.addEventListener('error', err, true);
    window.addEventListener('unhandledrejection', rej);
    return () => {
      window.removeEventListener('pointerdown', pd, true);
      window.removeEventListener('click', cl, true);
      window.removeEventListener('error', err, true);
      window.removeEventListener('unhandledrejection', rej);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-24 left-2 z-[999] w-9 h-9 rounded-full bg-[#0D1C42] text-white text-[10px] font-bold shadow-lg"
        style={{ pointerEvents: 'auto' }}
      >
        DBG
      </button>
    );
  }

  return (
    <div
      className="fixed bottom-24 left-2 right-2 z-[999] max-h-[38vh] overflow-y-auto rounded-xl bg-black/85 text-white font-mono text-[9px] p-2 shadow-xl"
      style={{ pointerEvents: 'auto' }}
    >
      <div className="flex items-center justify-between mb-1">
        <span className="font-bold">TAP PROBE · {route}</span>
        <button onClick={() => setOpen(false)} className="px-2 py-0.5 bg-white/20 rounded">hide</button>
      </div>
      {events.length === 0 && <div className="text-white/50">waiting for taps…</div>}
      {events.map((e, i) => (
        <div key={i} className="leading-snug">
          <span className="text-white/40">{e.t}</span> {e.msg}
        </div>
      ))}
    </div>
  );
};
