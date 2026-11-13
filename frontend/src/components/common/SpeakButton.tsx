import React, { useEffect, useState } from 'react';
import { Volume2, VolumeX, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { audioService } from '../../services/audio/AudioService';
import { languageName } from '../../i18n/languages';
import { VoiceMissingSheet } from './VoiceMissingSheet';
import type { Task } from '../../types';

/**
 * Per-task speaker control — top-right of task cards. One tap speaks the
 * task in the employee's audio language; tapping the active task stops it.
 * Subtle icon, 40px touch target, never lets the card's onClick fire.
 */
export const SpeakButton: React.FC<{ task: Task; className?: string }> = ({
  task,
  className = '',
}) => {
  const { t } = useTranslation();
  const [state, setState] = useState(audioService.state);
  const [pending, setPending] = useState(false);
  const [showVoiceSheet, setShowVoiceSheet] = useState(false);

  useEffect(() => audioService.subscribe(setState), []);
  useEffect(
    () => () => {
      if (audioService.isSpeaking(task.id)) void audioService.stop();
    },
    [task.id]
  );

  const speakingThis = state.kind === 'speaking' && state.taskId === task.id;
  const missingVoice =
    state.kind === 'error' && state.reason === 'voice_missing' && state.taskId === task.id;

  // Surface the localized voice-missing sheet as soon as the provider
  // reports the selected audio language has no installed voice.
  useEffect(() => {
    if (missingVoice) setShowVoiceSheet(true);
  }, [missingVoice]);

  const onClick = async (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    if (pending) return;
    setPending(true);
    try {
      await audioService.speakTask(task);
    } finally {
      setPending(false);
    }
  };

  return (
    <>
    <button
      type="button"
      onClick={onClick}
      aria-label={speakingThis ? t('audio.stopSpeaking') : t('audio.listen')}
      title={
      missingVoice
        ? t('audio.unavailable', { language: languageName(audioService.audioLanguage) })
        : undefined
    }
      className={`w-10 h-10 -m-1.5 flex items-center justify-center rounded-xl transition-colors flex-shrink-0 ${
        speakingThis
          ? 'text-[#33B059] bg-[#E8F7ED]'
          : missingVoice
            ? 'text-[#D9534F] hover:bg-[#FCEBEA]'
            : 'text-[#8D999C] hover:bg-[#F0F2F1] hover:text-[#667174]'
      } ${className}`}
    >
      {pending ? (
        <Loader2 className="w-[18px] h-[18px] animate-spin" />
      ) : speakingThis ? (
        <Volume2 className="w-[18px] h-[18px] animate-pulse" />
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
