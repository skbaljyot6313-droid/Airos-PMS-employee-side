/**
 * Thin typed bridge over the native AirosUpdate Capacitor plugin
 * (frontend/android/.../AppUpdatePlugin.java, registered in MainActivity).
 *
 * React code must never see URLs, file paths, or intents — only these
 * operations. On web / when the plugin is absent every call rejects, and
 * callers degrade silently (update flow simply stays inactive).
 */

import { registerPlugin, PluginListenerHandle } from '@capacitor/core';

export interface PendingApk {
  exists: boolean;
  versionCode?: number;
  versionName?: string;
  sizeBytes?: number;
}

export interface DownloadProgress {
  received: number;
  total: number;
  /** -1 when the server didn't report a content length. */
  percent: number;
}

interface AirosUpdatePlugin {
  downloadApk(options: {
    url: string;
    expectedVersionCode: number;
  }): Promise<{ versionCode: number; versionName: string; sizeBytes: number }>;
  getPendingApk(): Promise<PendingApk>;
  installApk(): Promise<void>;
  canRequestPackageInstalls(): Promise<{ allowed: boolean }>;
  openInstallPermissionSettings(): Promise<void>;
  deletePendingApk(): Promise<void>;
  addListener(
    eventName: 'downloadProgress',
    listenerFunc: (progress: DownloadProgress) => void,
  ): Promise<PluginListenerHandle>;
}

export const NativeUpdate = registerPlugin<AirosUpdatePlugin>('AirosUpdate');
