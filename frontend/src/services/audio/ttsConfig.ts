/**
 * Central TTS tuning — single place to adjust naturalness without touching
 * the provider, service or buttons.
 *
 * `rate` is the plugin's 0–1 speech-rate scale (1.0 = engine default).
 * 0.88 is slower and clearer for field instructions without dragging.
 * `pitch` 1.0 keeps the voice's natural register.
 *
 * Voice preference: within voices matching the locale we prefer locally
 * installed voices (no network round-trip per utterance, keep working on
 * poor connectivity) and Google Speech Services voices, which carry the
 * most natural hi-IN/mr-IN delivery on typical Android devices. Voices
 * are never auto-downloaded — missing voices surface the install sheet.
 */
export const TTS_CONFIG = {
  /** Speech rate on the plugin's 0–1 scale (engine-multiplied). */
  rate: 0.88,
  pitch: 1.0,
  volume: 1.0,
  /** iOS audio-session category passed through to the plugin. */
  category: 'ambient' as const,
  /** Flush: a new utterance replaces anything queued/playing — no overlap. */
  queueStrategy: 0,
  /** Preferred engine markers, most-preferred first. */
  preferredVoiceHints: ['google', 'com.google.android.tts'],
} as const;
