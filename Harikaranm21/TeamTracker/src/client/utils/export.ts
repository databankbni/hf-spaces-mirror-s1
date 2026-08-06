/**
 * CSV export utility — no external dependencies needed.
 * @module utils/export
 */
import type { CalendarEvent } from '../../shared/types';

function to12h(h: number): string {
  if (h === 0) return '12am';
  if (h === 12) return '12pm';
  return h < 12 ? `${h}am` : `${h - 12}pm`;
}

function formatTime(t: string | null | undefined): string {
  if (!t) return '';
  const h = parseInt(t, 10);
  return isNaN(h) ? t : to12h(h);
}

function escapeCsv(val: string | null | undefined): string {
  if (!val) return '';
  const str = String(val);
  if (str.includes(',') || str.includes('"') || str.includes('\n')) {
    return `"${str.replace(/"/g, '""')}"`;
  }
  return str;
}

/** Downloads a CSV file of the user's calendar events for a given month. */
export function exportCalendarToExcel(
  events: CalendarEvent[],
  year: number,
  month: number
): void {
  const monthName = new Date(year, month - 1, 1).toLocaleString('default', { month: 'long' });
  const filename = `TeamTracker-Calendar-${monthName}-${year}.csv`;

  const headers = ['Date', 'Type', 'Title', 'Description', 'Start', 'End'];
  const rows = events
    .sort((a, b) => a.date.localeCompare(b.date) || (a.start_time ?? '').localeCompare(b.start_time ?? ''))
    .map(ev => [
      ev.date,
      ev.event_type,
      ev.title,
      ev.description,
      formatTime(ev.start_time),
      formatTime(ev.end_time),
    ].map(escapeCsv).join(','));

  const csv = [headers.join(','), ...rows].join('\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
