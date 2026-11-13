/**
 * Centralized i18n bootstrap — i18next + react-i18next.
 *
 * Language source of truth is the backend preference record; this file only
 * restores the *cached* copy written by `services/preferencesService` so the
 * first authenticated render is already in the right language (no flash of
 * English before the preferences fetch resolves). The service then
 * re-synchronizes with the server and calls `setUiLanguage` if it differs.
 */
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import {
  SUPPORTED_LANGUAGES,
  DEFAULT_LANGUAGE,
  isSupportedLanguage,
  type LanguageCode,
} from './languages';
import { en } from './resources/en';
import { hi } from './resources/hi';
import { mr } from './resources/mr';

const resources = {
  en: { translation: en },
  hi: { translation: hi },
  mr: { translation: mr },
};

export const PREF_CACHE_KEY = 'airos_employee_preferences';

interface CachedPrefs {
  text_language?: string;
  audio_language?: string;
}

const cachedTextLanguage = (): LanguageCode => {
  try {
    const raw = localStorage.getItem(PREF_CACHE_KEY);
    const parsed = raw ? (JSON.parse(raw) as CachedPrefs) : null;
    return isSupportedLanguage(parsed?.text_language)
      ? parsed.text_language
      : DEFAULT_LANGUAGE;
  } catch {
    return DEFAULT_LANGUAGE;
  }
};

void i18n.use(initReactI18next).init({
  resources,
  lng: cachedTextLanguage(),
  fallbackLng: DEFAULT_LANGUAGE,
  supportedLngs: SUPPORTED_LANGUAGES.map((l) => l.code),
  nonExplicitSupportedLngs: false,
  interpolation: { escapeValue: false },
  returnNull: false,
  missingKeyHandler: (_lngs, _ns, key) => {
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.warn(`[i18n] missing translation key: ${key}`);
    }
  },
});

export const setUiLanguage = async (code: LanguageCode): Promise<void> => {
  if (i18n.language !== code) await i18n.changeLanguage(code);
};

export const currentUiLanguage = (): LanguageCode => {
  const lng = (i18n.language ?? '').split('-')[0];
  return isSupportedLanguage(lng) ? lng : DEFAULT_LANGUAGE;
};

export { i18n };
export default i18n;
