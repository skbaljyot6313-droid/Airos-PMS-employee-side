/**
 * Location API — tracking sessions + fix ingest over /location/*.
 *
 * The backend holds each employee's LATEST fix in Redis under a TTL and
 * appends every accepted fix to a daily-partitioned history — the native
 * tracker (src/services/locationTracker.ts → AirosLocation plugin) is the
 * only producer; employees can only ever read their own fix.
 *
 * Endpoints:
 *   POST /location/start   → mint a tracking session
 *   POST /location/current → LocationAckWire (idempotent on seq)
 *   POST /location/stop    → end a session (history survives)
 *   GET  /location/current → LiveLocationWire (is_live=false when absent)
 */

import { apiClient } from './client';
import {
  LiveLocationWire,
  LocationAckWire,
  LocationStartWire,
  LocationStopWire,
  LocationUpdateWire,
} from './wire';

/** Mint a tracking session — identity is server-side; the client never
 *  proposes an id. */
export function startTrackingSession(): Promise<LocationStartWire> {
  return apiClient<LocationStartWire>('/location/start', {
    method: 'POST',
    body: JSON.stringify({}),
  });
}

/** End a session — idempotent; history is never deleted. */
export function stopTrackingSession(sessionId: string): Promise<LocationStopWire> {
  return apiClient<LocationStopWire>('/location/stop', {
    method: 'POST',
    body: JSON.stringify({ tracking_session_id: sessionId }),
  });
}

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
