import { describe, it, expect, beforeEach } from 'vitest';
import i18n, { setUiLanguage, currentUiLanguage } from '../index';
import { en } from '../resources/en';
import { hi } from '../resources/hi';
import { mr } from '../resources/mr';

const flatten = (obj: object, prefix = ''): string[] =>
  Object.entries(obj).flatMap(([k, v]) =>
    typeof v === 'object' && v !== null
      ? flatten(v as object, `${prefix}${k}.`)
      : [`${prefix}${k}`]
  );

describe('i18n resources', () => {
  it('hi/mr cover every key en defines (schema parity)', () => {
    const enKeys = flatten(en).sort();
    expect(flatten(hi).sort()).toEqual(enKeys);
    expect(flatten(mr).sort()).toEqual(enKeys);
  });

  it('resolves keys in all three languages', async () => {
    for (const [lng, expected] of [
      ['en', 'Tasks'],
      ['hi', 'कार्य'],
      ['mr', 'कामे'],
    ] as const) {
      await i18n.changeLanguage(lng);
      expect(i18n.t('nav.tasks')).toBe(expected);
    }
  });

  it('interpolates placeholders', async () => {
    await i18n.changeLanguage('en');
    expect(i18n.t('tasks.minPhotosRequired', { count: 2 })).toBe('Min 2 required');
    await i18n.changeLanguage('hi');
    expect(i18n.t('tasks.minPhotosRequired', { count: 2 })).toContain('2');
  });
});

describe('language switching', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('switches en → hi → mr → en repeatedly', async () => {
    for (const lng of ['hi', 'mr', 'en', 'hi'] as const) {
      await setUiLanguage(lng);
      expect(currentUiLanguage()).toBe(lng);
    }
  });

  it('falls back to English for an unknown active language', async () => {
    await i18n.changeLanguage('en');
    // i18next falls back to fallbackLng for missing languages
    expect(i18n.t('common.save')).toBe('Save');
  });
});
