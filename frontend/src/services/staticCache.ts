/**
 * Persistent static cache (Phase 3) — NON-SENSITIVE reference data only.
 *
 * Backed by @capacitor/preferences (localStorage on web, SharedPreferences
 * on Android). Keys are versioned and user-namespaced:
 *   airos:static:v{SCHEMA}:{user_uid}:{entry}
 * A schema bump or a user switch invalidates by key shape alone.
 *
 * HARD RULES
 *  - whitelist only: zones / company / shift / profile — enforced by
 *    STATIC_KEYS; anything else throws.
 *  - NEVER store tokens, credentials, GPS/location data, or work content.
 *  - profile = display fields only (name/job_title/zone_uid/property_uid).
 *  - purgeStaticCaches() on logout AND on account switch.
 */

import { Preferences } from '@capacitor/preferences';

export const STATIC_SCHEMA_VERSION = 1;
const PREFIX = `airos:static:v${STATIC_SCHEMA_VERSION}`;

/** The complete allowed key set — anything outside this throws. */
export const STATIC_KEYS = ['zones', 'company', 'shift', 'profile'] as const;
export type StaticKey = (typeof STATIC_KEYS)[number];

const key = (uid: string, entry: StaticKey): string =>
  `${PREFIX}:${uid}:${entry}`;

const assertKey = (entry: string): void => {
  if (!(STATIC_KEYS as readonly string[]).includes(entry)) {
    throw new Error(`staticCache refuses non-whitelisted key: ${entry}`);
  }
};

export async function staticGet<T>(
  uid: string,
  entry: StaticKey,
): Promise<T | undefined> {
  assertKey(entry);
  const { value } = await Preferences.get({ key: key(uid, entry) });
  if (value === null || value === undefined) return undefined;
  try {
    return JSON.parse(value) as T;
  } catch {
    return undefined;
  }
}

export async function staticSet(
  uid: string,
  entry: StaticKey,
  value: unknown,
): Promise<void> {
  assertKey(entry);
  await Preferences.set({
    key: key(uid, entry),
    value: JSON.stringify(value),
  });
}

export async function staticRemove(
  uid: string,
  entry: StaticKey,
): Promise<void> {
  assertKey(entry);
  await Preferences.remove({ key: key(uid, entry) });
}

/** Drop every versioned static entry — logout / account switch. */
export async function purgeStaticCaches(): Promise<void> {
  const { keys } = await Preferences.keys();
  await Promise.all(
    keys
      .filter((k) => k.startsWith('airos:static:'))
      .map((k) => Preferences.remove({ key: k })),
  );
}

/** Drop only one user's entries (e.g. session expiry for a known uid). */
export async function purgeStaticUser(uid: string): Promise<void> {
  const { keys } = await Preferences.keys();
  await Promise.all(
    keys
      .filter((k) => k.startsWith(`${PREFIX}:${uid}:`))
      .map((k) => Preferences.remove({ key: k })),
  );
}
