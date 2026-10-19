/**
 * In-memory stale-while-revalidate cache for list reads (Phase 3).
 *
 * Semantics:
 *  - fresh (< ttlMs): return cache, NO network — saves the round trip.
 *  - stale (>= ttlMs): return cache immediately + background revalidate;
 *    the fresh payload arrives via onUpdate.
 *  - miss: fetch, store, return.
 *
 * Scoping: entries are namespaced by the current user id — setCacheScope
 * is called on login/logout; a scope CHANGE purges everything (account
 * switch can never see another user's lists). Mutations invalidate by
 * prefix; logout invalidates all.
 *
 * Holds only data the screens render anyway — never tokens, credentials
 * or GPS (those never flow through here).
 */

interface Entry {
  data: unknown;
  fetchedAt: number;
}

export interface SwrOpts<T> {
  /** Fresh-entry lifetime (default 45 s — the poll cadence). */
  ttlMs?: number;
  /** Called with the revalidated payload after a stale hit refresh. */
  onUpdate?: (data: T) => void;
  /** Revalidate even inside the fresh window (pull-to-refresh). */
  force?: boolean;
}

const store = new Map<string, Entry>();
const revalidating = new Map<string, Promise<unknown>>();
let scope = 'anon';

export const cacheScopeUid = (): string | null =>
  scope === 'anon' ? null : scope;

export const setCacheScope = (userId: string | null): void => {
  const next = userId ?? 'anon';
  if (next === scope) return;
  store.clear(); // account switch — previous user's data is gone
  scope = next;
};

const fullKey = (key: string): string => `${scope}:${key}`;

export function cachePeek<T>(key: string): { data: T; stale: boolean } | undefined {
  const e = store.get(fullKey(key));
  return e ? { data: e.data as T, stale: false } : undefined;
}

/** Drop entries matching `${scope}:${prefix}` (or a whole key). */
export function cacheInvalidate(prefix: string): void {
  const full = fullKey(prefix);
  for (const k of store.keys()) {
    if (k === full || k.startsWith(full + ':') || k.startsWith(full)) {
      store.delete(k);
    }
  }
}

export function cacheInvalidateAll(): void {
  store.clear();
}

export async function swr<T>(
  key: string,
  fetcher: () => Promise<T>,
  opts: SwrOpts<T> = {},
): Promise<T | undefined> {
  // Kill-switch: VITE_DATA_CACHE=0 bypasses the cache entirely.
  if (import.meta.env.VITE_DATA_CACHE === '0') return fetcher();
  const { ttlMs = 45_000, onUpdate, force = false } = opts;
  const k = fullKey(key);
  const hit = store.get(k);
  const fresh = hit !== undefined && Date.now() - hit.fetchedAt < ttlMs;

  const revalidate = (): void => {
    if (revalidating.has(k)) return;
    const p = fetcher()
      .then((data) => {
        store.set(k, { data, fetchedAt: Date.now() });
        onUpdate?.(data);
      })
      .catch(() => {
        // Keep serving stale on refresh failure — the poll floor will
        // retry on the next cadence.
      })
      .finally(() => {
        revalidating.delete(k);
      });
    revalidating.set(k, p);
  };

  if (hit && fresh && !force) return hit.data as T;
  if (hit && !force) {
    revalidate();
    return hit.data as T; // stale-while-revalidate
  }
  // Miss (or forced refresh) — fetch inline.
  const p = revalidating.get(k);
  if (p !== undefined) {
    // A background revalidate is already in flight — share it.
    const data = await p.catch(() => undefined);
    return data as T | undefined;
  }
  const promise = fetcher()
    .then((data) => {
      store.set(k, { data, fetchedAt: Date.now() });
      return data;
    })
    .finally(() => {
      revalidating.delete(k);
    });
  revalidating.set(k, promise);
  return promise;
}
