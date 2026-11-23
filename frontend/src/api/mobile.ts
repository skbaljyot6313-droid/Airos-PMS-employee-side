/** Public mobile release metadata — GET /mobile/version. */

import { apiClient } from './client';

export interface MobileVersionInfo {
  platform: string;
  latest_version: string;
  latest_version_code: number;
  sha256?: string | null;
  file_size_bytes?: number | null;
  update_available?: boolean | null;
  mandatory_update?: boolean | null;
  /** Server-computed signer verdict — false means the active release can
   *  never install over this build (WRONG_SIGNATURE). null/absent = the
   *  server's verdict is unknown and the native signer check decides. */
  update_compatible?: boolean | null;
  incompatibility_reason?: string | null;
  /** Signing-cert fingerprint of the active release binary, when stored. */
  signer_sha256?: string | null;
  installed_signer_sha256?: string | null;
  minimum_version: string;
  minimum_version_code: number;
  download_url: string;
  release_notes: string | null;
  force_update: boolean;
}

/** Unauthenticated by design — an app too old to log in must still be
 *  able to learn that an update exists. Passing the installed
 *  versionCode lets the server withhold releases it knows this build
 *  can't install (signer rotation). */
export const getMobileVersion = (
  platform: string = 'android',
  installedVersionCode?: number,
): Promise<MobileVersionInfo> => {
  const installed =
    typeof installedVersionCode === 'number'
      ? `&installed_version_code=${installedVersionCode}`
      : '';
  return apiClient<MobileVersionInfo>(
    `/mobile/version?platform=${platform}${installed}`,
    { auth: false, timeoutMs: 10000 },
  );
};
