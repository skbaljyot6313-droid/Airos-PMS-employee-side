/**
 * Central task-speech service.
 *
 * One active utterance at a time, owned here — components never touch the
 * TTS plugin. `speakTask` resolves the speech text in the employee's audio
 * language, verifies the voice exists, flushes any prior playback, then
 * speaks. Callers observe `state` via `subscribe` for the speaker-icon UI.
 *
 * Lifecycle policy: stop on new speak, stop on navigation/unmount, stop on
 * logout (`reset`), stop on app backgrounding (App 'pause' listener wired in
 * App.tsx).
 */
import type { Task } from '../../types';
import { resolveSpeechText } from '../../i18n/taskText';
import { DEFAULT_LANGUAGE, type LanguageCode } from '../../i18n/languages';
import { capacitorTTSProvider, localeForLanguage, VoiceUnavailableError, type TTSProvider } from './TTSProvider';

export type SpeechStatus =
  | { kind: 'idle' }
  | { kind: 'preparing'; taskId: string }
  | { kind: 'speaking'; taskId: string }
  | { kind: 'completed'; taskId: string }
  | { kind: 'error'; taskId: string | null; reason: 'voice_missing' | 'failed' };

type Listener = (s: SpeechStatus) => void;

export class AudioService {
  provider: TTSProvider = capacitorTTSProvider;

  private language: LanguageCode = DEFAULT_LANGUAGE;
  private status: SpeechStatus = { kind: 'idle' };
  private listeners = new Set<Listener>();
  /** Monotonic token — a stale speak completion can't clobber a newer one. */
  private generation = 0;

  setLanguage(code: LanguageCode): void {
    if (code === this.language) return;
    this.language = code;
    void this.stop();
  }

  get audioLanguage(): LanguageCode {
    return this.language;
  }

  get state(): SpeechStatus {
    return this.status;
  }

  isSpeaking(taskId?: string): boolean {
    return (
      (this.status.kind === 'speaking' || this.status.kind === 'preparing') &&
      (taskId === undefined || this.status.taskId === taskId)
    );
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private emit(s: SpeechStatus): void {
    this.status = s;
    this.listeners.forEach((fn) => fn(s));
  }

  /**
   * Speak one task once. Clicking a different card stops the current task;
   * clicking the same card while it speaks toggles it off.
   * Returns true when speech started; false when it toggled off.
   */
  async speakTask(task: Task): Promise<boolean> {
    if (this.isSpeaking(task.id)) {
      await this.stop();
      return false;
    }

    const gen = ++this.generation;
    const locale = localeForLanguage(this.language);
    const text = resolveSpeechText(task, this.language);

    try {
      this.emit({ kind: 'preparing', taskId: task.id });
      await this.provider.stop(); // belt-and-braces alongside queueStrategy flush
      this.emit({ kind: 'speaking', taskId: task.id });
      await this.provider.speak(text, locale);
      if (this.generation === gen) {
        // Brief "completed" beat so the button can show a subtle done
        // flash before settling back to idle.
        this.emit({ kind: 'completed', taskId: task.id });
        setTimeout(() => {
          if (this.generation === gen) this.emit({ kind: 'idle' });
        }, 1200);
      }
      return true;
    } catch (err) {
      if (this.generation === gen) {
        this.emit({
          kind: 'error',
          taskId: task.id,
          reason: err instanceof VoiceUnavailableError ? 'voice_missing' : 'failed',
        });
      }
      return false;
    }
  }

  async stop(): Promise<void> {
    ++this.generation;
    try {
      await this.provider.stop();
    } catch {
      /* stop is best-effort */
    }
    if (this.status.kind !== 'idle') this.emit({ kind: 'idle' });
  }

  /** Logout / account-switch: kill playback and forget the language. */
  async reset(): Promise<void> {
    await this.stop();
    this.language = DEFAULT_LANGUAGE;
  }

  /** Whether a voice exists for the current audio language. */
  async checkLanguageSupport(): Promise<boolean> {
    try {
      return await this.provider.isLanguageSupported(localeForLanguage(this.language));
    } catch {
      return false;
    }
  }

  /** Open the OS voice-install flow (Android TTS settings) when supported. */
  async openVoiceInstall(): Promise<void> {
    await this.provider.openInstall?.();
  }
}

export const audioService = new AudioService();
