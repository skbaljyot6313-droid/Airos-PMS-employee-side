/**
 * Thin typed bridge over the native AirosLocation Capacitor plugin
 * (frontend/android/.../LocationTrackerPlugin.java +
 * LocationTrackingService.java, registered in MainActivity).
 *
 * The plugin drives the foreground service — capture, offline queue,
 * uploads and auth refresh all run natively, independent of the WebView.
 * React code never sees Intents or SharedPreferences; on web / when the
 * plugin is absent every call rejects and callers degrade silently.
 */

import { registerPlugin } from '@capacitor/core';

export interface NativeTrackerState {
  running: boolean;
  /** Session the service is currently uploading under, if any. */
  sessionId: string | null;
  sequenceNumber: number;
  /** ms epoch of the last successfully delivered fix (0 = none). */
  lastFixAt: number;
  /** Offline backlog size — nonzero while connectivity is down. */
  queuedCount: number;
  lastError?: string;
}

interface AirosLocationPlugin {
  start(options: {
    apiBase: string;
    accessToken: string;
    refreshToken?: string;
    sessionId: string;
    intervalSeconds?: number;
  }): Promise<{ started: boolean }>;
  stop(): Promise<void>;
  updateAuth(options: {
    accessToken: string;
    refreshToken?: string;
  }): Promise<void>;
  getState(): Promise<NativeTrackerState>;
  openBatteryOptimizationSettings(): Promise<void>;
}

export const NativeLocation =
  registerPlugin<AirosLocationPlugin>('AirosLocation');
