import { describe, it, expect } from 'vitest';
import { resolveTaskText, resolveSpeechText, ticketToSpeakable } from '../taskText';
import type { Task } from '../../types';

const mkTask = (over: Partial<Task> = {}): Task =>
  ({
    id: 't1',
    kind: 'task',
    title: 'Clean room 205',
    instructions: 'Mop the floor and change the sheets.',
    category: 'Cleaning',
    location_name: 'Room 205',
    zone_name: 'Wing A',
    priority: 'medium',
    status: 'assigned',
    ...over,
  }) as Task;

describe('resolveTaskText', () => {
  it('returns source strings for English', () => {
    const r = resolveTaskText(mkTask(), 'en');
    expect(r.title).toBe('Clean room 205');
    expect(r.instructions).toBe('Mop the floor and change the sheets.');
  });

  it('prefers server-provided translated variants', () => {
    const t = {
      ...mkTask(),
      title_translations: { hi: 'कमरा 205 साफ़ करें' },
      description_translations: { hi: 'फ़र्श पोंछें।' },
    } as Task;
    const r = resolveTaskText(t, 'hi');
    expect(r.title).toBe('कमरा 205 साफ़ करें');
    expect(r.instructions).toBe('फ़र्श पोंछें।');
    expect(r.localized).toBe(true);
  });

  it('uses a registered work-type template when no description exists', () => {
    const r = resolveTaskText(mkTask({ instructions: null }), 'hi');
    expect(r.title).toBe('Room 205 साफ़ करें।');
    expect(r.localized).toBe(true);
  });

  it('falls back to the source text for unknown categories', () => {
    const r = resolveTaskText(mkTask({ category: 'Deep Polish' }), 'mr');
    expect(r.title).toBe('Clean room 205');
    expect(r.localized).toBe(false);
  });

  it('never returns empty fields for legacy tasks', () => {
    const r = resolveTaskText(mkTask({ instructions: null }), 'mr');
    expect(r.title).toBe('Room 205 स्वच्छ करा.');
    expect(r.title.length).toBeGreaterThan(0);
  });
});

describe('resolveSpeechText', () => {
  it('joins title and instructions once', () => {
    const s = resolveSpeechText(mkTask(), 'en');
    expect(s).toBe('Clean room 205. Mop the floor and change the sheets.');
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
    expect(s).toBe('Room 205 साफ़ करें।');
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
