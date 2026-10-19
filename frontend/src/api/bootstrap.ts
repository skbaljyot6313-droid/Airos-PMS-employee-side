/**
 * GET /bootstrap client path (Phase 3) — behind VITE_BOOTSTRAP=1, default
 * OFF. The consolidated endpoint returns {user, company, zones, shift,
 * unread_count} in ≤3 queries; any section that arrives as null or is
 * listed in `errors` falls back to its legacy endpoint — the app must
 * work identically whether the endpoint is healthy, partially degraded,
 * or disabled server-side (BOOTSTRAP_ENABLED backend flag → 404).
 *
 * Launch contract: callers render whatever the persistent static cache
 * has, then warmStaticCache() calls /bootstrap and rewrites the cache.
 * ref_version is kept with the zones entry — it's a content hash, not
 * data.
 */

import { apiClient } from './client';
import { listZonesApi } from './directory';
import { getMyShiftApi } from './shift';
import { unreadCountApi } from './notifications';
import { staticGet, staticSet } from '../services/staticCache';
import { Company, MyShift } from '../types';
import { ListResponseWire, ZoneWire } from './wire';

export const BOOTSTRAP_ENABLED = import.meta.env.VITE_BOOTSTRAP === '1';

export interface BootstrapWire {
  ref_version: string;
  user: Record<string, unknown>;
  company: Record<string, unknown> | null;
  zones: ListResponseWire<ZoneWire> | null;
  shift: Record<string, unknown> | null;
  unread_count: { unread: number } | null;
  errors: Record<string, string>;
}

export const fetchBootstrapApi = (): Promise<BootstrapWire> =>
  apiClient<BootstrapWire>('/bootstrap');

interface ZonesEntry {
  ref_version: string | null;
  items: ZoneWire[];
}

/** Read the persisted zones entry — raw-array tolerant for older writes. */
export const readStaticZones = async (
  uid: string,
): Promise<ZoneWire[] | undefined> => {
  const entry = await staticGet<ZonesEntry | ZoneWire[]>(uid, 'zones');
  if (!entry) return undefined;
  return Array.isArray(entry) ? entry : entry.items;
};

/**
 * Fill the persistent static cache from /bootstrap, falling back per
 * section to the legacy endpoint when the section is null/errored.
 * Never throws — a failed warm leaves prior static data in place.
 */
export async function warmStaticCache(
  uid: string,
  sessionCompany: Company | null,
): Promise<void> {
  if (!BOOTSTRAP_ENABLED || !uid) return;

  let boot: BootstrapWire | null = null;
  try {
    boot = await fetchBootstrapApi();
  } catch {
    boot = null; // endpoint missing/down → full legacy fallback
  }
  const failed = new Set(Object.keys(boot?.errors ?? {}));
  const section = <T>(v: T | null | undefined, name: string): T | null =>
    v == null || failed.has(name) ? null : v;

  // zones — {ref_version, items} so revalidation can diff cheaply.
  try {
    const z = section(boot?.zones, 'zones');
    if (z) {
      await staticSet(uid, 'zones', {
        ref_version: boot!.ref_version ?? null,
        items: z.items,
      });
    } else {
      const items = (await listZonesApi()).items;
      await staticSet(uid, 'zones', {
        ref_version: boot?.ref_version ?? null,
        items,
      });
    }
  } catch {
    /* static write is best-effort */
  }

  // company — no standalone endpoint; bootstrap section or the session
  // object /auth/me already returned.
  try {
    const c = section(boot?.company, 'company') ?? sessionCompany;
    if (c) await staticSet(uid, 'company', c);
  } catch {
    /* best-effort */
  }

  // shift definitions — legacy fallback: GET /attendance/shift.
  try {
    const s = section(boot?.shift, 'shift') ?? (await getMyShiftApi());
    if (s) await staticSet(uid, 'shift', s);
  } catch {
    /* no assignment or fetch failure — leave prior entry */
  }

  // unread_count — legacy fallback: GET /notifications/unread-count.
  // Not persisted (not static reference data); the call just validates
  // the fallback path works when the section fails.
  if (section(boot?.unread_count, 'unread') == null) {
    try {
      await unreadCountApi();
    } catch {
      /* best-effort */
    }
  }
}
