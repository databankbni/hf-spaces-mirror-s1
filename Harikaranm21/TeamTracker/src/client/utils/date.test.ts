import { describe, it, expect, beforeEach, vi } from 'vitest';
import { formatDueDate, isDueOverdue, isDueSoon } from './date';

describe('formatDueDate', () => {
  beforeEach(() => {
    // Fix "today" to 2026-06-25
    vi.setSystemTime(new Date('2026-06-25T12:00:00Z'));
  });

  it('returns null for null input', () => {
    expect(formatDueDate(null)).toBeNull();
  });

  it('returns null for undefined input', () => {
    expect(formatDueDate(undefined)).toBeNull();
  });

  it('returns null for invalid date string', () => {
    expect(formatDueDate('not-a-date')).toBeNull();
  });

  it('returns "Today" for today\'s date', () => {
    expect(formatDueDate('2026-06-25')).toBe('Today');
  });

  it('returns "Tomorrow" for tomorrow', () => {
    expect(formatDueDate('2026-06-26')).toBe('Tomorrow');
  });

  it('returns "Yesterday" for yesterday', () => {
    expect(formatDueDate('2026-06-24')).toBe('Yesterday');
  });

  it('returns overdue string for past dates', () => {
    const result = formatDueDate('2026-06-10');
    expect(result).toMatch(/Overdue/);
  });

  it('returns a formatted date for future dates', () => {
    const result = formatDueDate('2026-07-15');
    expect(result).toBeTruthy();
    expect(result).not.toMatch(/Overdue/);
  });
});

describe('isDueOverdue', () => {
  beforeEach(() => {
    vi.setSystemTime(new Date('2026-06-25T12:00:00Z'));
  });

  it('returns true for past dates', () => {
    expect(isDueOverdue('2026-06-10')).toBe(true);
  });

  it('returns false for today', () => {
    expect(isDueOverdue('2026-06-25')).toBe(false);
  });

  it('returns false for future dates', () => {
    expect(isDueOverdue('2026-07-01')).toBe(false);
  });

  it('returns false for null', () => {
    expect(isDueOverdue(null)).toBe(false);
  });
});

describe('isDueSoon', () => {
  beforeEach(() => {
    vi.setSystemTime(new Date('2026-06-25T12:00:00Z'));
  });

  it('returns true for today', () => {
    expect(isDueSoon('2026-06-25')).toBe(true);
  });

  it('returns true for tomorrow', () => {
    expect(isDueSoon('2026-06-26')).toBe(true);
  });

  it('returns false for a date beyond the window', () => {
    expect(isDueSoon('2026-06-28')).toBe(false);
  });

  it('returns false for overdue dates', () => {
    expect(isDueSoon('2026-06-10')).toBe(false);
  });
});
