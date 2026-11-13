import React, { useEffect, useState } from 'react';
import { Volume2, VolumeX, Loader2, Check } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { audioService } from '../../services/audio/AudioService';
import { languageName } from '../../i18n/languages';
import { VoiceMissingSheet } from './VoiceMissingSheet';
import type { Task } from '../../types';

/**
 * Per-task speaker control — top-right of task cards. One tap speaks the
 * task in the employee's audio language; tapping the active task stops it.
 *
 * States: idle → preparing (spinner) → speaking (animated bars) →
 * completed (brief check) → idle; error → muted speaker + voice sheet.
 * Compact 40px touch target, never fires the card's onClick.
 */
export const SpeakButton: React.FC<{ task: Task; className?: string }> = ({
  task,
  className = '',
}) => {
  const { t } = useTranslation();
  const [state, setState] = useState(audioService.state);
  const [showVoiceSheet, setShowVoiceSheet] = useState(false);

  useEffect(() => audioService.subscribe(setState), []);
  useEffect(
    () => () => {
      if (audioService.isSpeaking(task.id)) void audioService.stop();
    },
    [task.id]
  );

  const own = 'taskId' in state && state.taskId === task.id;
  const preparing = state.kind === 'preparing' && own;
  const speakingThis = state.kind === 'speaking' && own;
  const completed = state.kind === 'completed' && own;
  const missingVoice =
    state.kind === 'error' && state.reason === 'voice_missing' && own;

  // Surface the localized voice-missing sheet as soon as the provider
  // reports the selected audio language has no installed voice.
  useEffect(() => {
    if (missingVoice) setShowVoiceSheet(true);
  }, [missingVoice]);

  const onClick = async (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    await audioService.speakTask(task);
  };

  const ariaLabel = speakingThis
    ? t('audio.stopSpeaking')
    : completed
      ? t('audio.completed')
      : t('audio.listen');

  return (
    <>
    <button
      type="button"
      onClick={onClick}
      aria-label={ariaLabel}
      aria-pressed={speakingThis}
      title={
      missingVoice
        ? t('audio.unavailable', { language: languageName(audioService.audioLanguage) })
        : undefined
    }
      className={`w-10 h-10 -m-1.5 flex items-center justify-center rounded-xl transition-colors flex-shrink-0 ${
        speakingThis
          ? 'text-[#33B059] bg-[#E8F7ED]'
          : completed
            ? 'text-[#278B46] bg-[#E8F7ED]'
            : missingVoice
              ? 'text-[#D9534F] hover:bg-[#FCEBEA]'
              : 'text-[#8D999C] hover:bg-[#F0F2F1] hover:text-[#667174]'
      } ${className}`}
    >
      {preparing ? (
        <Loader2 className="w-[18px] h-[18px] animate-spin" />
      ) : speakingThis ? (
        <span className="flex items-end gap-[2px] h-[14px]" aria-hidden="true">
          <span className="w-[3px] bg-current rounded-sm animate-[speakbar_0.9s_ease-in-out_infinite]" style={{ height: '60%' }} />
          <span className="w-[3px] bg-current rounded-sm animate-[speakbar_0.9s_ease-in-out_0.15s_infinite]" style={{ height: '100%' }} />
          <span className="w-[3px] bg-current rounded-sm animate-[speakbar_0.9s_ease-in-out_0.3s_infinite]" style={{ height: '45%' }} />
        </span>
      ) : completed ? (
        <Check className="w-[18px] h-[18px]" />
      ) : missingVoice ? (
        <VolumeX className="w-[18px] h-[18px]" />
      ) : (
        <Volume2 className="w-[18px] h-[18px]" />
      )}
    </button>
    {showVoiceSheet && (
      <VoiceMissingSheet onClose={() => setShowVoiceSheet(false)} />
    )}
    </>
  );
};
