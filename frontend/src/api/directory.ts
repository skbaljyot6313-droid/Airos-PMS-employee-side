/**
 * Directory lookups — the only structure endpoint this backend exposes is
 * GET /zones (scoped to the caller's property). Used for display-only
 * enrichment (zone names for uids); no business logic lives here.
 */

import { apiClient } from './client';
import { ListResponseWire, ZoneWire } from './wire';

/** Raw GET /zones call — used ONLY by the zone cache below; screens and
 *  other api modules go through getZonesCached()/getZoneNameMap(). */
export const listZonesApi = (): Promise<ListResponseWire<ZoneWire>> =>
  apiClient<ListResponseWire<ZoneWire>>('/zones');

// ---------------------------------------------------------------------------
// Zone cache — tasks/maintenance screens resolve zones on every call; a
// short-lived memo avoids refetching /zones each time (single-flight).
// ---------------------------------------------------------------------------

const ZONE_CACHE_TTL_MS = 60_000;
let zoneCache: { at: number; items: ZoneWire[] } | null = null;
let zoneInFlight: Promise<ZoneWire[]> | null = null;

export function invalidateZoneCache(): void {
  zoneCache = null;
}

export async function getZonesCached(): Promise<ZoneWire[]> {
  if (zoneCache && Date.now() - zoneCache.at < ZONE_CACHE_TTL_MS) {
    return zoneCache.items;
  }
  // Bootstrap flag on → the persistent static cache (filled by
  // warmStaticCache) satisfies the read without a network call.
  if (import.meta.env.VITE_BOOTSTRAP === '1') {
    try {
      const { readStaticZones } = await import('./bootstrap');
      const { cacheScopeUid } = await import('../services/dataCache');
      const uid = cacheScopeUid();
      const items = uid ? await readStaticZones(uid) : undefined;
      if (items && items.length > 0) {
        zoneCache = { at: Date.now(), items };
        return items;
      }
    } catch {
      /* fall through to the network path */
    }
  }
  zoneInFlight ??= listZonesApi()
    .then((res) => {
      zoneCache = { at: Date.now(), items: res.items };
      return res.items;
    })
    .catch(() => [] as ZoneWire[])
    .finally(() => {
      zoneInFlight = null;
    });
  return zoneInFlight;
}

export async function getZoneNameMap(): Promise<Map<string, string>> {
  const zones = await getZonesCached();
  return new Map(zones.map((z) => [z.zone_uid, z.name]));
}
