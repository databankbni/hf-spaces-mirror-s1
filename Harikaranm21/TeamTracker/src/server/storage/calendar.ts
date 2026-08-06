/**
 * Calendar event data access layer.
 * All queries are scoped to a specific user_id — users only see their own events.
 * @module server/storage/calendar
 */
import { getDb } from './db';
import type { CalendarEvent, CreateCalendarEventInput, UpdateCalendarEventInput } from '../../shared/types';

export function getEventsByMonth(userId: number, year: number, month: number): CalendarEvent[] {
  const db = getDb();
  // month is 1-indexed; pad to YYYY-MM
  const prefix = `${year}-${String(month).padStart(2, '0')}`;
  return db
    .prepare("SELECT * FROM calendar_events WHERE user_id = ? AND date LIKE ? ORDER BY date ASC, start_time ASC")
    .all(userId, `${prefix}%`) as CalendarEvent[];
}

export function getEventsByDate(userId: number, date: string): CalendarEvent[] {
  const db = getDb();
  return db
    .prepare("SELECT * FROM calendar_events WHERE user_id = ? AND date = ? ORDER BY start_time ASC")
    .all(userId, date) as CalendarEvent[];
}

export function getEventById(id: number, userId: number): CalendarEvent | undefined {
  const db = getDb();
  return db
    .prepare("SELECT * FROM calendar_events WHERE id = ? AND user_id = ?")
    .get(id, userId) as CalendarEvent | undefined;
}

export function createEvent(userId: number, input: CreateCalendarEventInput): CalendarEvent {
  const db = getDb();
  const result = db.prepare(`
    INSERT INTO calendar_events (user_id, title, description, event_type, date, start_time, end_time, color)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
  `).run(
    userId,
    input.title,
    input.description ?? '',
    input.event_type ?? 'task',
    input.date,
    input.start_time ?? null,
    input.end_time ?? null,
    input.color ?? '#6E56CF'
  );
  return getEventById(result.lastInsertRowid as number, userId)!;
}

export function updateEvent(id: number, userId: number, input: UpdateCalendarEventInput): CalendarEvent | undefined {
  const db = getDb();
  const existing = getEventById(id, userId);
  if (!existing) return undefined;
  db.prepare(`
    UPDATE calendar_events SET
      title = ?, description = ?, event_type = ?, date = ?,
      start_time = ?, end_time = ?, color = ?,
      updated_at = datetime('now')
    WHERE id = ? AND user_id = ?
  `).run(
    input.title ?? existing.title,
    input.description ?? existing.description,
    input.event_type ?? existing.event_type,
    input.date ?? existing.date,
    input.start_time !== undefined ? input.start_time : existing.start_time,
    input.end_time !== undefined ? input.end_time : existing.end_time,
    input.color ?? existing.color,
    id, userId
  );
  return getEventById(id, userId);
}

export function deleteEvent(id: number, userId: number): boolean {
  const db = getDb();
  const result = db.prepare("DELETE FROM calendar_events WHERE id = ? AND user_id = ?").run(id, userId);
  return result.changes > 0;
}
