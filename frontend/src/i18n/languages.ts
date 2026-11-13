/**
 * Centralized language registry — mirrors the backend's
 * `app/domain/languages.py`. The GET /mobile/employee/preferences/languages
 * endpoint serves the same metadata; this local copy keeps the UI working
 * offline and before the preferences fetch lands.
 */

export interface LanguageMeta {
  code: string;
  name: string;
  native_name: string;
  /** BCP-47 tag handed to device TTS. */
  locale: string;
}

export const SUPPORTED_LANGUAGES: LanguageMeta[] = [
  { code: 'en', name: 'English', native_name: 'English', locale: 'en-IN' },
  { code: 'hi', name: 'Hindi', native_name: 'हिन्दी', locale: 'hi-IN' },
  { code: 'mr', name: 'Marathi', native_name: 'मराठी', locale: 'mr-IN' },
];

export type LanguageCode = (typeof SUPPORTED_LANGUAGES)[number]['code'];

export const SUPPORTED_LANGUAGE_CODES = SUPPORTED_LANGUAGES.map(
  (l) => l.code
) as LanguageCode[];

export const DEFAULT_LANGUAGE: LanguageCode = 'en';

export const isSupportedLanguage = (code: unknown): code is LanguageCode =>
  typeof code === 'string' && SUPPORTED_LANGUAGE_CODES.includes(code as LanguageCode);

export const languageName = (code: string): string =>
  SUPPORTED_LANGUAGES.find((l) => l.code === code)?.name ?? code;

export const ttsLocale = (code: string): string =>
  SUPPORTED_LANGUAGES.find((l) => l.code === code)?.locale ??
  SUPPORTED_LANGUAGES[0].locale;
