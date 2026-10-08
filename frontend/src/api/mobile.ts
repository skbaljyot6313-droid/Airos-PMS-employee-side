/** Public mobile release metadata — GET /mobile/version. */

import { apiClient } from './client';

export interface MobileVersionInfo {
  platform: string;
  latest_version: string;
  latest_version_code: number;
  minimum_version: string;
  minimum_version_code: number;
  download_url: string;
  release_notes: string | null;
  force_update: boolean;
}

/** Unauthenticated by design — an app too old to log in must still be
 *  able to learn that an update exists. */
export const getMobileVersion = (
  platform: string = 'android',
): Promise<MobileVersionInfo> =>
  apiClient<MobileVersionInfo>(`/mobile/version?platform=${platform}`, {
    auth: false,
    timeoutMs: 10000,
  });
