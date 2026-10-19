/**
 * Cold-start performance marks — Phase-0 observability.
 *
 * Cheap performance.mark() calls at the startup milestones; console.info
 * output reaches adb logcat through the Capacitor console bridge, so
 * field devices can be profiled without any backend changes.
 *
 * Milestones:
 *   t2_webview      JS bundle evaluated (main.tsx module scope)
 *   t3_auth         session resolution finished (AuthContext)
 *   t4_first_req    first API request dispatched (client.ts)
 *   t5_first_res    first API response received (client.ts)
 *   t6_data         first screen data resolved (TasksScreen)
 *   t7_usable       authenticated shell first rendered (App.tsx)
 */

const PREFIX = 'airos:';
const seen = new Set<string>();
let reported = false;

/** Idempotent mark — first call wins (later same-name calls no-op). */
export function perfMarkOnce(name: string): void {
  if (seen.has(name)) return;
  seen.add(name);
  try {
    performance.mark(`${PREFIX}${name}`);
  } catch {
    /* performance API unavailable — instrumentation must never break */
  }
}

const t = (name: string): number | undefined => {
  try {
    const entries = performance.getEntriesByName(`${PREFIX}${name}`);
    return entries.length ? entries[0].startTime : undefined;
  } catch {
    return undefined;
  }
};

/** One-shot cold-start summary → console.info → logcat. */
export function perfReportOnce(): void {
  if (reported) return;
  reported = true;
  try {
    const t2 = t('t2_webview');
    const t3 = t('t3_auth');
    const t4 = t('t4_first_req');
    const t5 = t('t5_first_res');
    const t6 = t('t6_data');
    const t7 = t('t7_usable');
    const base = t2 ?? 0;
    const d = (v?: number) => (v !== undefined ? `${Math.round(v - base)}` : '?');
    console.info(
      `[PERF] cold-start webview=0ms auth=${d(t3)}ms ` +
        `first_req=${d(t4)}ms first_res=${d(t5)}ms ` +
        `data=${d(t6)}ms usable=${d(t7)}ms`
    );
  } catch {
    /* never break startup on telemetry */
  }
}
