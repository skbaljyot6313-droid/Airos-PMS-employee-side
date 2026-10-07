import { describe, it, expect } from 'vitest';
import { normalizeError, mediaUrl, errorMessage, API_BASE, API_ORIGIN } from '../client';

describe('normalizeError', () => {
  it('maps a detail string', () => {
    const e = normalizeError(401, { detail: 'Bad credentials' });
    expect(e.status).toBe(401);
    expect(e.message).toBe('Bad credentials');
  });

  it('maps a detail object with message/code/field', () => {
    const e = normalizeError(422, {
      detail: { message: 'Too few photos', code: 'VALIDATION_ERROR', field: 'photo_urls' },
    });
    expect(e.message).toBe('Too few photos');
    expect(e.code).toBe('VALIDATION_ERROR');
    expect(e.fieldErrors).toEqual([{ field: 'photo_urls', message: 'Too few photos' }]);
  });

  it('maps a 422 detail array using loc[-1] as the field', () => {
    const e = normalizeError(422, {
      detail: [
        { loc: ['body', 'photo_urls'], msg: 'at least 1 image required', type: 'value_error' },
        { loc: ['body', 'note'], msg: 'too long', type: 'value_error' },
      ],
      error: { code: 'VALIDATION_ERROR', message: 'invalid' },
    });
    expect(e.message).toBe('at least 1 image required');
    expect(e.code).toBe('VALIDATION_ERROR');
    expect(e.fieldErrors?.[0]).toMatchObject({ field: 'photo_urls' });
    expect(e.fieldErrors).toHaveLength(2);
  });

  it('maps an error-only envelope (500/503 path with no detail)', () => {
    const e = normalizeError(503, { error: { code: 'DATABASE_UNAVAILABLE', message: 'db down' } });
    expect(e.status).toBe(503);
    expect(e.code).toBe('DATABASE_UNAVAILABLE');
    expect(e.message).toBe('db down');
  });

  it('falls back per status for unknown bodies', () => {
    expect(normalizeError(429, null).message).toMatch(/Too many requests/);
    expect(normalizeError(400, {}).message).toMatch(/invalid/i);
    expect(normalizeError(404, undefined).message).toBe('Not found.');
    expect(normalizeError(499, 'weird').message).toBe('Request failed (499).');
  });
});

describe('mediaUrl', () => {
  it('passes absolute URLs through untouched', () => {
    expect(mediaUrl('https://cdn.example.com/x.jpg')).toBe('https://cdn.example.com/x.jpg');
    expect(mediaUrl('http://example.com/x.jpg')).toBe('http://example.com/x.jpg');
  });

  it('prefixes relative paths with the API origin', () => {
    expect(API_BASE).toMatch(/\/api\/v1$/);
    expect(mediaUrl('/uploads/a.jpg')).toBe(`${API_ORIGIN}/uploads/a.jpg`);
    expect(mediaUrl('uploads/a.jpg')).toBe(`${API_ORIGIN}/uploads/a.jpg`);
  });
});

describe('errorMessage', () => {
  it('extracts .message from Error-like values', () => {
    expect(errorMessage(new Error('boom'), 'fb')).toBe('boom');
    expect(errorMessage({ message: 'api msg' }, 'fb')).toBe('api msg');
  });
  it('uses the fallback otherwise', () => {
    expect(errorMessage('nope', 'fb')).toBe('fb');
    expect(errorMessage(null, 'fb')).toBe('fb');
    expect(errorMessage({ message: 42 }, 'fb')).toBe('fb');
  });
});
