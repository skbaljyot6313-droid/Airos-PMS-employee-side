/**
 * Employee language-preferences session service.
 *
 * - Server is the source of truth; localStorage is a per-employee cache that
 *   makes the first render after restart already localized.
 * - `loadForEmployee` is called once per authenticated session (from App.tsx
 *   when `user` changes); it applies the cached text language immediately
 *   then re-syncs with the backend in the background.
 * - `update` PATCHes the server, refreshes the cache, and swaps i18n's
 *   active language only after a successful save.
 * - `clear` (logout / identity change) drops the cache and resets to en.
 */
import {
  DEFAULT_PREFERENCES,
  EmployeePreferences,
  getPreferencesApi,
  updatePreferencesApi,
} from '../api/preferences';
import { setUiLanguage } from '../i18n';
import { DEFAULT_LANGUAGE, isSupportedLanguage, type LanguageCode } from '../i18n/languages';
import { audioService } from './audio/AudioService';

const cacheKey = (employeeUid: string) => `airos_employee_preferences:${employeeUid}`;

const readCache = (employeeUid: string): EmployeePreferences | null => {
  try {
    const raw = localStorage.getItem(cacheKey(employeeUid));
    if (!raw) return null;
    const p = JSON.parse(raw) as Partial<EmployeePreferences>;
    if (!isSupportedLanguage(p.text_language)) return null;
    return {
      text_language: p.text_language,
      audio_language: isSupportedLanguage(p.audio_language)
        ? p.audio_language
        : DEFAULT_LANGUAGE,
    };
  } catch {
    return null;
  }
};

const writeCache = (employeeUid: string, prefs: EmployeePreferences): void => {
  try {
    localStorage.setItem(cacheKey(employeeUid), JSON.stringify(prefs));
    // Legacy shared key — i18n bootstrap reads this before the employee id
    // is known (login screen / cold start).
    localStorage.setItem('airos_employee_preferences', JSON.stringify(prefs));
  } catch {
    /* quota/private mode — cache is best-effort */
  }
};

let current: EmployeePreferences = { ...DEFAULT_PREFERENCES };
let currentEmployeeUid: string | null = null;
let inflight: Promise<EmployeePreferences> | null = null;

export const preferencesService = {
  /** The last resolved preference set (never null — defaults when empty). */
  get prefs(): EmployeePreferences {
    return current;
  },
  get audioLanguage(): LanguageCode {
    return current.audio_language;
  },

  /**
   * Hydrate for a fresh session: apply cache synchronously, then reconcile
   * with the server. Never throws — a failed fetch leaves the cache/defaults
   * in place so login never breaks on preference availability.
   */
  async loadForEmployee(employeeUid: string | null): Promise<EmployeePreferences> {
    if (inflight && employeeUid === currentEmployeeUid) return inflight;
    currentEmployeeUid = employeeUid;

    const cached = employeeUid ? readCache(employeeUid) : null;
    if (cached) {
      current = cached;
      await setUiLanguage(cached.text_language);
      audioService.setLanguage(cached.audio_language);
    }

    inflight = (async () => {
      try {
        const server = await getPreferencesApi();
        current = { text_language: server.text_language, audio_language: server.audio_language };
        if (employeeUid) writeCache(employeeUid, current);
        await setUiLanguage(current.text_language);
        audioService.setLanguage(current.audio_language);
      } catch {
        /* offline / server down — cached or default prefs stay active */
      } finally {
        inflight = null;
      }
      return current;
    })();
    return inflight;
  },

  /**
   * PATCH one or both languages. Returns the server-confirmed preference
   * set; throws (to the caller's UI error path) when the PATCH fails — the
   * previous in-memory prefs stay active.
   */
  async update(patch: Partial<EmployeePreferences>): Promise<EmployeePreferences> {
    const server = await updatePreferencesApi(patch);
    current = { text_language: server.text_language, audio_language: server.audio_language };
    if (currentEmployeeUid) writeCache(currentEmployeeUid, current);
    await setUiLanguage(current.text_language);
    audioService.setLanguage(current.audio_language);
    return current;
  },

  /** Clear session preferences on logout or account switch. */
  clear(): void {
    current = { ...DEFAULT_PREFERENCES };
    currentEmployeeUid = null;
    inflight = null;
    try {
      localStorage.removeItem('airos_employee_preferences');
    } catch {
      /* best-effort */
    }
    void setUiLanguage(DEFAULT_LANGUAGE);
    audioService.setLanguage(DEFAULT_LANGUAGE);
  },
};
