/**
 * Date formatting utilities.
 * @module utils/date
 */

/** Returns 'Today', 'Tomorrow', 'Overdue', or a formatted date string. */
export function formatDueDate(dateStr: string | null | undefined): string | null {
  if (!dateStr) return null;
  const due = new Date(dateStr);
  if (isNaN(due.getTime())) return null;

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  due.setHours(0, 0, 0, 0);

  const diffDays = Math.round((due.getTime() - today.getTime()) / 86_400_000);

  if (diffDays === 0) return 'Today';
  if (diffDays === 1) return 'Tomorrow';
  if (diffDays === -1) return 'Yesterday';
  if (diffDays < 0) return `Overdue (${due.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })})`;
  return due.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export function isDueOverdue(dateStr: string | null | undefined): boolean {
  if (!dateStr) return false;
  const due = new Date(dateStr);
  if (isNaN(due.getTime())) return false;
  due.setHours(0, 0, 0, 0);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return due < today;
}

export function isDueSoon(dateStr: string | null | undefined, withinDays = 2): boolean {
  if (!dateStr) return false;
  const due = new Date(dateStr);
  if (isNaN(due.getTime())) return false;
  due.setHours(0, 0, 0, 0);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diffDays = Math.round((due.getTime() - today.getTime()) / 86_400_000);
  return diffDays >= 0 && diffDays <= withinDays;
}
