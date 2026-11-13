/**
 * Employee language-preference API — thin wire layer over
 * `/mobile/employee/preferences`. Follows the same request()/wire-mapping
 * conventions as the other api/* modules.
 */
import { apiClient } from './client';
import type { LanguageCode } from '../i18n/languages';
import { DEFAULT_LANGUAGE, isSupportedLanguage, SUPPORTED_LANGUAGES } from '../i18n/languages';

export interface EmployeePreferences {
  text_language: LanguageCode;
  audio_language: LanguageCode;
}

export interface PreferencesResponse extends EmployeePreferences {
  available_languages: { code: string; name: string; native_name: string }[];
}

export const DEFAULT_PREFERENCES: EmployeePreferences = {
  text_language: DEFAULT_LANGUAGE,
  audio_language: DEFAULT_LANGUAGE,
};

const normalize = (raw: Partial<PreferencesResponse> | null | undefined): EmployeePreferences => ({
  text_language: isSupportedLanguage(raw?.text_language)
    ? raw.text_language
    : DEFAULT_LANGUAGE,
  audio_language: isSupportedLanguage(raw?.audio_language)
    ? raw.audio_language
    : DEFAULT_LANGUAGE,
});

export const getPreferencesApi = async (): Promise<PreferencesResponse> => {
  const data = await apiClient<PreferencesResponse>('/mobile/employee/preferences');
  return {
    ...normalize(data),
    available_languages: data.available_languages?.length
      ? data.available_languages
      : SUPPORTED_LANGUAGES,
  };
};

export const updatePreferencesApi = async (
  patch: Partial<EmployeePreferences>
): Promise<PreferencesResponse> => {
  const data = await apiClient<PreferencesResponse>('/mobile/employee/preferences', {
    method: 'PATCH',
    body: JSON.stringify(patch),
  });
  return {
    ...normalize(data),
    available_languages: data.available_languages?.length
      ? data.available_languages
      : SUPPORTED_LANGUAGES,
  };
};
