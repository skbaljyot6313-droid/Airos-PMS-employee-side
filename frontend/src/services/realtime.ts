/**
 * Centrifugo realtime — one shared WebSocket per session, subscribing to
 * the employee's own private channel (priv:emp:{employee_uid}). Tokens
 * come from this API (GET /realtime/token, POST /realtime/subscribe) —
 * nothing secret is bundled.
 *
 * Events are invalidation hints: an event triggers an immediate
 * notification-feed poll (the feed materializes SA-side assignments on
 * read) and notifies listeners (task/maintenance screens re-fetch).
 * The 45 s poll stays as the reconciliation backstop, so a Centrifugo
 * outage degrades to the pre-realtime behavior — never breaks.
 */
import { Centrifuge } from 'centrifuge';
import { apiClient } from '../api/client';
import { pollNotificationsNow } from './notificationService';
import { cacheInvalidate, cacheInvalidateAll } from './dataCache';

interface TokenResponse {
  token: string;
  expires_at: number;
  ws_url: string;
}

interface SubscribeResponse {
  tokens: Record<string, string>;
}

export interface RealtimeEvent {
  type?: string;
  data?: unknown;
}

const listeners = new Set<(e: RealtimeEvent) => void>();

// ---------------------------------------------------------------------------
// Event → cache-invalidation map (Phase 4). Each publication is a hint
// ONLY — the API stays authoritative; the affected list prefix is dropped
// so the next read (or the screen's own re-pull) hits the network. Event
// payloads are {type, uid, v, ts} + minimal metadata — never full records.
// ---------------------------------------------------------------------------

const INVALIDATION_MAP: [prefix: string, keys: string[]][] = [
  ['task.', ['tasks:']],
  ['maintenance.', ['maintenance:', 'tasks:']],
  ['ticket.', ['maintenance:', 'tasks:']],
  ['attendance.', ['attendance:']],
  ['notification.', ['notifications:']],
  ['resource.', ['maintenance:']],
  ['company.ref_', ['bootstrap']],
];

/** Synthetic type emitted when a subscription could not recover missed
 *  publications — screens treat it like their own prefixes. */
export const UNRECOVERED_EVENT = 'realtime.unrecovered';

const invalidateForEvent = (type: string): void => {
  for (const [prefix, keys] of INVALIDATION_MAP) {
    if (type.startsWith(prefix)) {
      for (const k of keys) cacheInvalidate(k);
    }
  }
};

/** Subscribe to realtime events for the session — returns unsubscribe. */
export function subscribeRealtime(
  listener: (e: RealtimeEvent) => void,
): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function emit(e: RealtimeEvent): void {
  listeners.forEach((l) => l(e));
}

let centrifuge: Centrifuge | null = null;
/** Set when the backend reports realtime unconfigured (503). Retried
 *  after a cooldown so a config rollout during a session still works. */
let unavailableUntil = 0;
const UNAVAILABLE_COOLDOWN_MS = 60_000;

async function fetchToken(): Promise<TokenResponse> {
  return apiClient<TokenResponse>('/realtime/token');
}

/**
 * Start the realtime session for an employee; returns a stop function.
 * No-ops (returns a dummy stop) when realtime is unconfigured server-side.
 */
export function startRealtime(
  employeeUid: string,
  companyUid?: string,
): () => void {
  if (Date.now() < unavailableUntil) return () => {};
  let stopped = false;
  let sub: { unsubscribe: () => void } | null = null;

  void (async () => {
    const channel = `priv:emp:${employeeUid}`;
    try {
      if (!centrifuge) {
        const { token, ws_url } = await fetchToken();
        centrifuge = new Centrifuge(ws_url, {
          token,
          getToken: async () => (await fetchToken()).token,
        });
        centrifuge.connect();
      }
      const fetchSubToken = async () => {
        const res = await apiClient<SubscribeResponse>(
          '/realtime/subscribe',
          { method: 'POST', body: JSON.stringify({ channels: [channel] }) },
        );
        return res.tokens[channel];
      };
      const s = centrifuge.newSubscription(channel, {
        token: await fetchSubToken(),
        getToken: fetchSubToken,
      });
      s.on('publication', (ctx) => {
        const ev = (ctx.data ?? {}) as RealtimeEvent;
        if (ev.type) invalidateForEvent(ev.type);
        // Any business event can carry a new assignment — re-poll the
        // feed so popups/notifications arrive instantly.
        pollNotificationsNow();
        emit(ev);
      });
      // Centrifugo recovery: a RESUBSCRIBE that couldn't recover missed
      // publications is a silent gap — wipe the data caches and let
      // screens reconcile via UNRECOVERED_EVENT + the poll floor. The
      // initial subscribe reports recovered=false legitimately; the
      // gap case is wasRecovering && !recovered.
      s.on('subscribed', (ctx) => {
        if (ctx.wasRecovering === true && ctx.recovered === false) {
          cacheInvalidateAll();
          pollNotificationsNow();
          emit({ type: UNRECOVERED_EVENT });
        }
      });
      s.subscribe();
      // Optional shared company channel — ref_version markers only,
      // behind VITE_COMPANY_CHANNEL (default OFF); tokens are minted
      // server-side for the caller's own company only.
      if (import.meta.env.VITE_COMPANY_CHANNEL === '1' && companyUid) {
        const cs = centrifuge.newSubscription(`company:${companyUid}`, {
          getToken: async () => {
            const res = await apiClient<SubscribeResponse>(
              '/realtime/subscribe',
              {
                method: 'POST',
                body: JSON.stringify({
                  channels: [`company:${companyUid}`],
                }),
              },
            );
            return res.tokens[`company:${companyUid}`];
          },
        });
        cs.on('publication', (ctx) => {
          const ev = (ctx.data ?? {}) as RealtimeEvent;
          if (ev.type) invalidateForEvent(ev.type);
          emit(ev);
        });
        cs.subscribe();
      }
      if (stopped) {
        s.unsubscribe();
      } else {
        sub = s;
      }
    } catch (err: unknown) {
      const status =
        typeof err === 'object' && err !== null && 'status' in err
          ? (err as { status?: number }).status
          : undefined;
      if (status === 503) {
        unavailableUntil = Date.now() + UNAVAILABLE_COOLDOWN_MS;
      }
    }
  })();

  return () => {
    stopped = true;
    sub?.unsubscribe();
  };
}

/**
 * Debounced event subscription for screens — coalesces bursts of
 * publications into one callback, filtered to matching event prefixes.
 * Returns unsubscribe; also clears the pending debounce timer.
 */
export function subscribeRealtimeEvents(
  prefixes: string[],
  callback: () => void,
  debounceMs = 400,
): () => void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const unsub = subscribeRealtime((e) => {
    // An unrecovered subscription silently dropped events — every
    // subscribed screen reconciles.
    const match =
      e.type === UNRECOVERED_EVENT ||
      (e.type && prefixes.some((p) => e.type!.startsWith(p)));
    if (!match) return;
    clearTimeout(timer);
    timer = setTimeout(callback, debounceMs);
  });
  return () => {
    clearTimeout(timer);
    unsub();
  };
}

/** App-resume nudge — centrifuge-js auto-reconnects, but a suspended
 *  Android process may hold a dead socket; connect() is a no-op when
 *  already connected/connecting. Also reconcile the feed immediately. */
export function realtimeResume(): void {
  if (centrifuge) {
    try {
      centrifuge.connect();
    } catch {
      /* noop */
    }
  }
  pollNotificationsNow();
}

/** Drop the socket entirely — call on logout. */
export function stopRealtime(): void {
  const c = centrifuge;
  centrifuge = null;
  unavailableUntil = 0;
  if (c) {
    try {
      c.disconnect();
    } catch {
      /* noop */
    }
  }
}
