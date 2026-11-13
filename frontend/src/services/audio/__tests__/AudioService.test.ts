import { describe, it, expect, beforeEach, vi } from 'vitest';
import { AudioService } from '../AudioService';
import { VoiceUnavailableError, type TTSProvider } from '../TTSProvider';
import type { Task } from '../../../types';

const mkTask = (id: string, title = 'Task'): Task =>
  ({
    id,
    kind: 'task',
    title,
    instructions: 'Do the thing.',
    category: 'Cleaning',
    location_name: 'Room 1',
    zone_name: null,
    priority: 'medium',
    status: 'assigned',
  }) as Task;

class FakeProvider implements TTSProvider {
  spoken: { text: string; locale: string }[] = [];
  stopped = 0;
  supported = true;
  throwOnSpeak: Error | null = null;

  async speak(text: string, locale: string) {
    if (this.throwOnSpeak) throw this.throwOnSpeak;
    this.spoken.push({ text, locale });
  }
  async stop() {
    this.stopped++;
  }
  async isLanguageSupported() {
    return this.supported;
  }
}

describe('AudioService', () => {
  let svc: InstanceType<typeof AudioService>;
  let provider: FakeProvider;

  beforeEach(() => {
    svc = new AudioService();
    provider = new FakeProvider();
    svc.provider = provider;
    svc.setLanguage('en');
  });

  it('speaks a task once in the selected audio locale', async () => {
    await svc.speakTask(mkTask('a'));
    expect(provider.spoken).toEqual([
      { text: 'Task. Do the thing.', locale: 'en-IN' },
    ]);
    expect(svc.state.kind).toBe('idle'); // speak() resolved → back to idle
  });

  it('maps hi/mr to the correct TTS locales', async () => {
    svc.setLanguage('hi');
    await svc.speakTask(mkTask('a'));
    svc.setLanguage('mr');
    await svc.speakTask(mkTask('b'));
    expect(provider.spoken[0].locale).toBe('hi-IN');
    expect(provider.spoken[1].locale).toBe('mr-IN');
  });

  it('stops previous playback before speaking a different task', async () => {
    await svc.speakTask(mkTask('a'));
    await svc.speakTask(mkTask('b'));
    // provider.stop() is invoked before each new speak (a and b) → 2+ stops
    expect(provider.stopped).toBeGreaterThanOrEqual(2);
    expect(provider.spoken).toHaveLength(2);
    expect(provider.spoken[1].text).toContain('Task');
  });

  it('toggles off when the same task is clicked while speaking', async () => {
    // Keep speak() pending so the service stays in 'speaking'.
    let release!: () => void;
    provider.speak = () => new Promise<void>((r) => { release = r; });
    const p = svc.speakTask(mkTask('a'));
    await Promise.resolve();
    expect(svc.isSpeaking('a')).toBe(true);
    const toggled = await svc.speakTask(mkTask('a'));
    expect(toggled).toBe(false);
    expect(svc.state.kind).toBe('idle');
    release();
    await p;
  });

  it('repeated rapid clicks cannot overlap playback', async () => {
    const t1 = mkTask('a');
    const t2 = mkTask('b');
    await Promise.all([svc.speakTask(t1), svc.speakTask(t2)]);
    // Both resolve; each speak flushes the queue — one utterance at a time.
    expect(svc.state.kind).toBe('idle');
  });

  it('emits voice_missing when the selected voice is unavailable', async () => {
    provider.throwOnSpeak = new VoiceUnavailableError('mr-IN');
    const seen: string[] = [];
    svc.subscribe((s) => seen.push(s.kind === 'error' ? s.reason : s.kind));
    await svc.speakTask(mkTask('a'));
    expect(svc.state).toEqual({ kind: 'error', taskId: 'a', reason: 'voice_missing' });
    expect(seen).toContain('voice_missing');
  });

  it('emits failed for generic provider errors', async () => {
    provider.throwOnSpeak = new Error('engine crashed');
    await svc.speakTask(mkTask('a'));
    expect(svc.state).toEqual({ kind: 'error', taskId: 'a', reason: 'failed' });
  });

  it('stop() kills playback and returns to idle', async () => {
    let release!: () => void;
    provider.speak = () => new Promise<void>((r) => { release = r; });
    void svc.speakTask(mkTask('a'));
    await Promise.resolve();
    expect(svc.isSpeaking()).toBe(true);
    await svc.stop();
    expect(svc.state.kind).toBe('idle');
    release();
  });

  it('reset() stops playback and restores the default language', async () => {
    svc.setLanguage('hi');
    await svc.reset();
    expect(svc.audioLanguage).toBe('en');
    expect(svc.state.kind).toBe('idle');
  });

  it('a stale completion cannot clobber a newer state', async () => {
    // gen-1 speak hangs; gen-2 speak finishes. gen-1 resolving later must
    // not reset the status.
    let release1!: () => void;
    const orig = provider.speak.bind(provider);
    let call = 0;
    provider.speak = (text: string, locale: string) => {
      call++;
      if (call === 1) return new Promise<void>((r) => { release1 = r; });
      return orig(text, locale);
    };
    void svc.speakTask(mkTask('a'));
    await Promise.resolve();
    await svc.speakTask(mkTask('b'));
    expect(svc.state.kind).toBe('idle');
    release1();
    await new Promise((r) => setTimeout(r, 0));
    expect(svc.state.kind).toBe('idle');
  });
});
