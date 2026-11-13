import React, { useState } from 'react';
import { Settings2, Type, Volume2, Loader2, Check, AlertCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { SUPPORTED_LANGUAGES, type LanguageCode } from '../../i18n/languages';
import { preferencesService } from '../../services/preferencesService';
import type { EmployeePreferences } from '../../api/preferences';

type PrefKey = keyof EmployeePreferences;
type SaveState = 'idle' | 'saving' | 'saved' | 'error';

/**
 * Account Settings — independent Text/UI and Audio/TTS language pickers.
 * Changes auto-save through preferencesService (server is source of truth);
 * the UI language swap applies only after the PATCH succeeds.
 */
const LanguageRow: React.FC<{
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  value: LanguageCode;
  onChange: (code: LanguageCode) => void;
  saveState: SaveState;
}> = ({ icon, title, subtitle, value, onChange, saveState }) => (
  <div className="flex items-center gap-3 py-3 first:pt-0 last:pb-0">
    <div className="w-9 h-9 rounded-xl bg-[#F0F2F1] text-[#667174] flex items-center justify-center flex-shrink-0">
      {icon}
    </div>
    <div className="flex-1 min-w-0">
      <span className="block text-[13px] font-semibold text-[#20292C] leading-tight">
        {title}
      </span>
      <span className="block text-[11px] text-[#8D999C] mt-0.5">{subtitle}</span>
    </div>
    <div className="relative flex-shrink-0">
      {saveState === 'saving' ? (
        <Loader2 className="w-4 h-4 animate-spin text-[#8D999C] absolute -left-6 top-1/2 -translate-y-1/2" />
      ) : saveState === 'saved' ? (
        <Check className="w-4 h-4 text-[#33B059] absolute -left-6 top-1/2 -translate-y-1/2" />
      ) : null}
      <select
        value={value}
        disabled={saveState === 'saving'}
        onChange={(e) => onChange(e.target.value as LanguageCode)}
        aria-label={title}
        className="appearance-none bg-[#F7F8F6] border border-[#E4E8E6] rounded-xl text-xs font-semibold text-[#20292C] pl-3 pr-7 py-2 focus:outline-none focus:border-[#33B059] disabled:opacity-60"
      >
        {SUPPORTED_LANGUAGES.map((l) => (
          <option key={l.code} value={l.code}>
            {l.native_name}
          </option>
        ))}
      </select>
      <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-[#8D999C] text-[10px]">
        ▼
      </span>
    </div>
  </div>
);

export const AccountSettingsCard: React.FC = () => {
  const { t } = useTranslation();
  const [prefs, setPrefs] = useState<EmployeePreferences>(preferencesService.prefs);
  const [saveState, setSaveState] = useState<Record<PrefKey, SaveState>>({
    text_language: 'idle',
    audio_language: 'idle',
  });
  const [error, setError] = useState<string | null>(null);

  const change = async (key: PrefKey, code: LanguageCode) => {
    if (prefs[key] === code) return;
    setSaveState((s) => ({ ...s, [key]: 'saving' }));
    setError(null);
    try {
      const next = await preferencesService.update({ [key]: code });
      setPrefs(next);
      setSaveState((s) => ({ ...s, [key]: 'saved' }));
      setTimeout(
        () => setSaveState((s) => (s[key] === 'saved' ? { ...s, [key]: 'idle' } : s)),
        1500
      );
    } catch {
      setSaveState((s) => ({ ...s, [key]: 'error' }));
      setError(t('profile.prefSaveError'));
      setTimeout(
        () => setSaveState((s) => (s[key] === 'error' ? { ...s, [key]: 'idle' } : s)),
        3000
      );
    }
  };

  return (
    <div className="bg-white rounded-2xl p-4 border border-[#E4E8E6] shadow-sm">
      <div className="flex items-center gap-2 mb-1">
        <Settings2 className="w-4 h-4 text-[#33B059]" />
        <h3 className="text-xs font-bold text-[#20292C] uppercase tracking-wider font-['Space_Grotesk']">
          {t('profile.accountSettings')}
        </h3>
      </div>
      <p className="text-[11px] text-[#8D999C] mb-2">
        {t('profile.accountSettingsSub')}
      </p>

      <div className="divide-y divide-[#F0F2F1]">
        <LanguageRow
          icon={<Type className="w-4 h-4" />}
          title={t('profile.textLanguage')}
          subtitle={t('profile.textLanguageSub')}
          value={prefs.text_language}
          onChange={(c) => void change('text_language', c)}
          saveState={saveState.text_language}
        />
        <LanguageRow
          icon={<Volume2 className="w-4 h-4" />}
          title={t('profile.audioLanguage')}
          subtitle={t('profile.audioLanguageSub')}
          value={prefs.audio_language}
          onChange={(c) => void change('audio_language', c)}
          saveState={saveState.audio_language}
        />
      </div>

      {error && (
        <div className="flex items-center gap-1.5 mt-3 p-2.5 bg-[#FCEBEA] text-[11px] text-[#D9534F] rounded-xl">
          <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}
    </div>
  );
};
