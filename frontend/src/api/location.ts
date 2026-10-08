/**
 * Live location API — contract over /location/current.
 *
 * Current-position-only: the backend keeps each employee's LATEST fix in
 * Redis under a 60 s TTL — there is no history endpoint and no coordinate
 * history anywhere. The tracker (src/services/locationTracker.ts) is the
 * only producer; employees can only ever read their own fix.
 *
 * Endpoints:
 *   POST /location/current → LocationAckWire
 *   GET  /location/current → LiveLocationWire (is_live=false when absent)
 */

import { apiClient } from './client';
import { LiveLocationWire, LocationAckWire, LocationUpdateWire } from './wire';

/** Push one fix. Tight timeout — a slow request must never stall the
 *  tracking loop; the next tick simply retries. */
export function postCurrentLocation(
  payload: LocationUpdateWire
): Promise<LocationAckWire> {
  return apiClient<LocationAckWire>('/location/current', {
    method: 'POST',
    body: JSON.stringify(payload),
    timeoutMs: 8000,
  });
}

/** Read the caller's own latest fix — for polling UIs; never throws 404
 *  for "no fix", that state is is_live=false. */
export function getCurrentLocation(): Promise<LiveLocationWire> {
  return apiClient<LiveLocationWire>('/location/current');
}
