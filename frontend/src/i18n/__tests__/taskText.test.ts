import { describe, it, expect } from 'vitest';
import {
  getLocalizedTask,
  resolveTaskText,
  resolveSpeechText,
  ticketToSpeakable,
  identifierForSpeech,
  joinLabels,
  _clearTaskTextCache,
} from '../taskText';
import type { Task } from '../../types';

const mkTask = (over: Partial<Task> = {}): Task =>
  ({
    id: 't1',
    kind: 'task',
    title: 'Clean room 205',
    instructions: 'Mop the floor and change the sheets.',
    category: 'Cleaning',
    work_type: 'cleaning',
    location_name: 'Room 205',
    room_number: '205',
    zone_name: 'Wing A',
    priority: 'medium',
    status: 'assigned',
    ...over,
  }) as Task;

const mkBedTask = (labels = ['P2-01', 'P2-03', 'P2-05', 'P2-08', 'P2-10']): Task =>
  mkTask({
    id: 'bed-task',
    title: 'Cleaning — Dorm P2 (P2-01, P2-03, P2-05, P2-08, P2-10)',
    instructions: null,
    location_name: 'Dorm P2 · 5 beds',
    dorm_name: 'Dorm P2',
    room_number: null,
    resources: labels.map((label, i) => ({
      id: `bed-${i}`,
      label,
      kind: 'bed' as const,
      status: 'cleaning',
    })),
  });

describe('getLocalizedTask', () => {
  it('returns source strings for English', () => {
    const r = getLocalizedTask(mkTask(), 'en');
    expect(r.title).toBe('Clean room 205');
    expect(r.description).toBe('Mop the floor and change the sheets.');
    expect(r.localized).toBe(false);
  });

  it('prefers server-provided translated variants', () => {
    const t = {
      ...mkTask(),
      title_translations: { hi: 'कमरा 205 साफ़ करें' },
      description_translations: { hi: 'फ़र्श पोंछें।' },
    } as Task;
    const r = getLocalizedTask(t, 'hi');
    expect(r.title).toBe('कमरा 205 साफ़ करें');
    expect(r.description).toBe('फ़र्श पोंछें।');
    expect(r.localized).toBe(true);
    expect(r.descriptionLocalized).toBe(true);
  });

  it('localizes a room-cleaning task into Hindi', () => {
    const r = getLocalizedTask(mkTask(), 'hi');
    expect(r.title).toBe('रूम 205 सफ़ाई');
    expect(r.description).toBe('रूम 205 साफ़ करें।');
    expect(r.descriptionLocalized).toBe(true);
  });

  it('localizes a room-cleaning task into Marathi', () => {
    const r = getLocalizedTask(mkTask(), 'mr');
    expect(r.title).toBe('रूम 205 स्वच्छता');
    expect(r.description).toBe('रूम 205 स्वच्छ करा.');
  });

  it('names every bed in a grouped cleaning task (hi)', () => {
    const r = getLocalizedTask(mkBedTask(), 'hi');
    expect(r.title).toBe('बेड सफ़ाई — डॉर्म P2');
    expect(r.description).toBe(
      'डॉर्म P2 में बेड P2-01, P2-03, P2-05, P2-08 और P2-10 की सफ़ाई करें।',
    );
    // Identifiers pass through verbatim — display never rewrites them.
    expect(r.description).toContain('P2-01');
  });

  it('names every bed in a grouped cleaning task (mr)', () => {
    const r = getLocalizedTask(mkBedTask(), 'mr');
    expect(r.description).toBe(
      'डॉर्म P2 मधील बेड P2-01, P2-03, P2-05, P2-08 आणि P2-10 स्वच्छ करा.',
    );
  });

  it('names every bed in a grouped cleaning task (en)', () => {
    const r = getLocalizedTask(mkBedTask(), 'en');
    expect(r.description).toBe(
      'Clean beds P2-01, P2-03, P2-05, P2-08 and P2-10 in Dorm P2.',
    );
  });

  it('keeps English title for en even when a template fills the description', () => {
    const r = getLocalizedTask(mkBedTask(), 'en');
    expect(r.title).toBe(mkBedTask().title); // source title preserved
    expect(r.descriptionLocalized).toBe(true);
  });

  it('falls back to source text for unknown work types', () => {
    const r = getLocalizedTask(
      mkTask({ category: 'Deep Polish', work_type: 'deep_polish' }),
      'mr',
    );
    expect(r.title).toBe('Clean room 205');
    expect(r.localized).toBe(false);
  });

  it('never fake-translates free-form descriptions for unknown types', () => {
    const r = getLocalizedTask(
      mkTask({ work_type: 'other', instructions: 'Polish the brass rail.' }),
      'hi',
    );
    expect(r.description).toBe('Polish the brass rail.');
    expect(r.descriptionLocalized).toBe(false);
  });

  it('keeps maintenance tickets in source text', () => {
    const r = getLocalizedTask(mkTask({ kind: 'maintenance' }), 'hi');
    expect(r.title).toBe('Clean room 205');
    expect(r.localized).toBe(false);
  });

  it('handles washroom + fixture context', () => {
    const t = mkTask({
      room_number: null,
      location_name: 'W-01 · sink 2',
      washroom_name: 'W-01',
      washroom_fixture_label: 'sink 2',
    });
    const r = getLocalizedTask(t, 'hi');
    expect(r.description).toBe('वॉशरूम W-01 साफ़ करें।');
  });

  it('is memoized across repeated calls', () => {
    const t = mkTask();
    const first = getLocalizedTask(t, 'hi');
    expect(getLocalizedTask(t, 'hi')).toBe(first); // same object from cache
    _clearTaskTextCache();
    const recomputed = getLocalizedTask(t, 'hi');
    expect(recomputed).toEqual(first); // same content
    expect(recomputed).not.toBe(first); // recomputed instance
  });
});

describe('identifierForSpeech', () => {
  it('de-hyphenates identifiers for English', () => {
    expect(identifierForSpeech('P2-05', 'en')).toBe('P2 05');
  });

  it('transliterates letters and digits into Devanagari (hi)', () => {
    expect(identifierForSpeech('P2-01', 'hi')).toBe('पी टू ज़ीरो वन');
  });

  it('uses Marathi zero (झिरो) for mr', () => {
    expect(identifierForSpeech('P2-10', 'mr')).toBe('पी टू वन झिरो');
  });
});

describe('joinLabels', () => {
  it('uses language-specific conjunctions', () => {
    expect(joinLabels(['A', 'B', 'C'], 'en')).toBe('A, B and C');
    expect(joinLabels(['A', 'B', 'C'], 'hi')).toBe('A, B और C');
    expect(joinLabels(['A', 'B', 'C'], 'mr')).toBe('A, B आणि C');
    expect(joinLabels(['A'], 'en')).toBe('A');
  });
});

describe('resolveSpeechText', () => {
  it('joins title and instructions once for source text', () => {
    const s = resolveSpeechText(mkTask(), 'en');
    expect(s).toBe('Clean room 205. Mop the floor and change the sheets.');
  });

  it('speaks every bed identifier in English', () => {
    const s = resolveSpeechText(mkBedTask(), 'en');
    expect(s).toBe(
      'Clean beds P2 01, P2 03, P2 05, P2 08 and P2 10 in Dorm P2.',
    );
  });

  it('speaks every bed identifier in Hindi with transliterated ids', () => {
    const s = resolveSpeechText(mkBedTask(), 'hi');
    expect(s).toContain('डॉर्म पी टू में बेड');
    expect(s).toContain('पी टू ज़ीरो वन');
    expect(s).toContain('पी टू वन ज़ीरो'); // P2-10 → पी टू वन ज़ीरो
    expect(s).toContain('की सफ़ाई करें');
    // No raw hyphens survive into Devanagari speech.
    expect(s).not.toContain('P2-01');
  });

  it('speaks every bed identifier in Marathi', () => {
    const s = resolveSpeechText(mkBedTask(), 'mr');
    expect(s).toContain('डॉर्म पी टू मधील बेड');
    expect(s).toContain('पी टू वन झिरो');
    expect(s).toContain('स्वच्छ करा');
  });

  it('speaks a translated variant in the audio language', () => {
    const t = {
      ...mkTask(),
      description_translations: { mr: 'स्वच्छता करा.' },
    } as Task;
    const s = resolveSpeechText(t, 'mr');
    expect(s).toContain('स्वच्छता करा.');
  });

  it('uses a template for a bare structured task', () => {
    const s = resolveSpeechText(mkTask({ instructions: null }), 'hi');
    expect(s).toBe('रूम 205 साफ़ करें।');
  });

  it('never returns empty speech', () => {
    const s = resolveSpeechText(mkTask({ instructions: null }), 'en');
    expect(s.length).toBeGreaterThan(0);
  });
});

describe('ticketToSpeakable', () => {
  it('maps issue → title and description → instructions', () => {
    const t = ticketToSpeakable({
      id: 'tk1',
      issue: 'AC not cooling',
      description: 'Room 205 AC blows warm air',
      category: 'HVAC',
      location_name: 'Room 205',
    });
    const s = resolveSpeechText(t, 'en');
    expect(s).toContain('AC not cooling');
    expect(s).toContain('Room 205 AC blows warm air');
  });
});

// Keep resolveTaskText API surface — thin wrapper over getLocalizedTask.
describe('resolveTaskText', () => {
  it('delegates to the localization service', () => {
    const r = resolveTaskText(mkTask(), 'hi');
    expect(r.title).toBe('रूम 205 सफ़ाई');
    expect(r.instructions).toBe('रूम 205 साफ़ करें।');
  });
});
