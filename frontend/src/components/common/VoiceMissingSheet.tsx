import React from 'react';
import { VolumeX, Settings, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Capacitor } from '@capacitor/core';
import { audioService } from '../../services/audio/AudioService';
import { languageName } from '../../i18n/languages';

/**
 * Bottom sheet shown when the selected audio language has no installed
 * device voice. Offers the Android TTS voice-install flow and points the
 * employee at Profile → Account Settings to pick another audio language.
 */
export const VoiceMissingSheet: React.FC<{ onClose: () => void }> = ({
  onClose,
}) => {
  const { t } = useTranslation();
  const lang = languageName(audioService.audioLanguage);

  return (
    <div
      className="fixed inset-0 z-[95] flex items-end justify-center bg-black/40"
      onClick={onClose}
      role="alertdialog"
      aria-label={t('audio.voiceMissingTitle')}
    >
      <div
        className="w-full max-w-[420px] bg-white rounded-t-3xl p-5 pb-[max(2rem,calc(env(safe-area-inset-bottom,0px)+1rem))]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="w-10 h-1 bg-[#E7E5E4] rounded-full mx-auto mb-4" />

        <div className="flex items-start justify-between gap-3 mb-3">
          <div className="flex items-center gap-3 min-w-0">
            <div className="p-2.5 rounded-xl bg-[#FAEBEB] text-[#D64545] flex-shrink-0">
              <VolumeX className="w-5 h-5" />
            </div>
            <h4 className="text-base font-bold text-[#0D1C42] font-['Satoshi']">
              {t('audio.voiceMissingTitle')}
            </h4>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-[#98A2B3] hover:bg-[#F6F4F2] transition-colors flex-shrink-0"
            aria-label={t('common.close')}
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <p className="text-xs text-[#667085] leading-relaxed mb-5">
          {t('audio.unavailable', { language: lang })}
        </p>

        {Capacitor.isNativePlatform() && (
          <button
            type="button"
            onClick={() => {
              void audioService.openVoiceInstall();
              onClose();
            }}
            className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-[#800020] text-white text-sm font-semibold hover:bg-[#0D1C42] active:scale-[0.99] transition-all shadow-sm mb-2.5"
          >
            <Settings className="w-4 h-4" />
            {t('audio.openVoiceSettings')}
          </button>
        )}

        <button
          type="button"
          onClick={onClose}
          className="w-full py-3 rounded-xl bg-[#F6F4F2] text-[#0D1C42] text-sm font-semibold hover:bg-[#E7E5E4] transition-colors"
        >
          {t('audio.changeAudioLanguage')}
        </button>
      </div>
    </div>
  );
};
