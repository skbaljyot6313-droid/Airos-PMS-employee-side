/**
 * TTS provider abstraction + the Capacitor text-to-speech implementation.
 *
 * `@capacitor-community/text-to-speech` ships a web SpeechSynthesis
 * implementation alongside the Android TextToSpeech bridge, so one provider
 * covers every target. Tests substitute `AudioService.provider` with a fake.
 */
import { TextToSpeech } from '@capacitor-community/text-to-speech';
import type { LanguageCode } from '../../i18n/languages';
import { ttsLocale } from '../../i18n/languages';

export class VoiceUnavailableError extends Error {
  constructor(public readonly locale: string) {
    super(`TTS voice not available for ${locale}`);
    this.name = 'VoiceUnavailableError';
  }
}

export interface TTSProvider {
  /** Resolve → speak `text` once in `locale`. Rejects VoiceUnavailableError
   *  when no voice for the locale is installed. */
  speak(text: string, locale: string): Promise<void>;
  stop(): Promise<void>;
  /** true when a voice for the locale is installed. */
  isLanguageSupported(locale: string): Promise<boolean>;
  /** Open the OS voice-install flow (Android TTS settings). */
  openInstall?(): Promise<void>;
}

/**
 * Locale support check: the plugin's `isLanguageSupported` can return false
 * positives on some Android engines, so we cross-check the installed voice
 * list — a locale counts as supported only when a matching voice exists.
 */
const localeMatches = (voiceLang: string, locale: string): boolean => {
  const v = voiceLang.toLowerCase().replace('_', '-');
  const l = locale.toLowerCase();
  return v === l || v.split('-')[0] === l.split('-')[0];
};

class CapacitorTTSProvider implements TTSProvider {
  private supportedCache = new Map<string, boolean>();

  async isLanguageSupported(locale: string): Promise<boolean> {
    const hit = this.supportedCache.get(locale);
    if (hit !== undefined) return hit;
    try {
      const { voices } = await TextToSpeech.getSupportedVoices();
      const supported = voices.some((v) => localeMatches(v.lang, locale));
      this.supportedCache.set(locale, supported);
      return supported;
    } catch {
      // Fall back to the plugin's own coarse check.
      try {
        const { supported } = await TextToSpeech.isLanguageSupported({ lang: locale });
        this.supportedCache.set(locale, supported);
        return supported;
      } catch {
        this.supportedCache.set(locale, false);
        return false;
      }
    }
  }

  async speak(text: string, locale: string): Promise<void> {
    if (!(await this.isLanguageSupported(locale))) {
      throw new VoiceUnavailableError(locale);
    }
    await TextToSpeech.speak({
      text,
      lang: locale,
      rate: 1.0,
      pitch: 1.0,
      volume: 1.0,
      category: 'ambient',
      // Flush: a new utterance replaces anything still queued/playing —
      // overlapping task speech is impossible by construction.
      queueStrategy: 0,
    });
  }

  async stop(): Promise<void> {
    await TextToSpeech.stop();
  }

  async openInstall(): Promise<void> {
    await TextToSpeech.openInstall();
  }
}

export const capacitorTTSProvider: TTSProvider = new CapacitorTTSProvider();

/** Map a preference code → the BCP-47 tag handed to the provider. */
export const localeForLanguage = (code: LanguageCode): string => ttsLocale(code);
