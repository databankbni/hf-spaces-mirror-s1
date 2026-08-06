import { describe, it, expect } from 'vitest';
import { parseLabels, serializeLabels } from './labels';

describe('parseLabels', () => {
  it('returns empty array for null', () => {
    expect(parseLabels(null)).toEqual([]);
  });

  it('returns empty array for empty string', () => {
    expect(parseLabels('')).toEqual([]);
  });

  it('splits comma-separated labels', () => {
    expect(parseLabels('frontend, bug, feature')).toEqual(['frontend', 'bug', 'feature']);
  });

  it('trims whitespace', () => {
    expect(parseLabels('  bug  ,  frontend  ')).toEqual(['bug', 'frontend']);
  });

  it('deduplicates labels', () => {
    expect(parseLabels('bug, bug, feature')).toEqual(['bug', 'feature']);
  });

  it('filters empty segments', () => {
    expect(parseLabels('bug,,feature')).toEqual(['bug', 'feature']);
  });
});

describe('serializeLabels', () => {
  it('joins labels with comma-space', () => {
    expect(serializeLabels(['bug', 'feature'])).toBe('bug, feature');
  });

  it('returns empty string for empty array', () => {
    expect(serializeLabels([])).toBe('');
  });

  it('trims each label', () => {
    expect(serializeLabels(['  bug  ', ' feature '])).toBe('bug, feature');
  });
});
