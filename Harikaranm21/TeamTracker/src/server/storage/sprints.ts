/**
 * Sprint data access layer for TeamTracker.
 * @module server/storage/sprints
 */
import { getDb } from './db';
import type { Sprint, CreateSprintInput, UpdateSprintInput } from '../../shared/types';

// Re-export getDb so recovery routes can access the db directly
export { getDb };

/**
 * Auto-maintenance for sprints/months:
 *  1. Any sprint whose end_date is in the past and status != 'completed' → mark completed.
 *  2. If today is the 1st of the month AND no sprint exists that covers today → create one.
 *
 * Should be called on server startup and on a periodic schedule.
 */
export function autoMaintainSprints(): { completed: number; created: boolean } {
  const db = getDb();
  const pad = (n: number) => String(n).padStart(2, '0');

  // Use UTC date to avoid timezone surprises on the server
  const now = new Date();
  const yearUTC = now.getUTCFullYear();
  const monthUTC = now.getUTCMonth() + 1; // 1-based
  const dayUTC = now.getUTCDate();

  // "First day of the current month" — any sprint whose end_date is BEFORE
  // this is fully in the past and safe to mark completed.
  // This means a sprint for the current month is NEVER auto-completed mid-month.
  const firstOfCurrentMonth = `${yearUTC}-${pad(monthUTC)}-01`;

  // 1. Only mark sprints completed if their entire month is already past
  //    (end_date is before the 1st of this month)
  const completedResult = db.prepare(
    `UPDATE sprints SET status = 'completed'
     WHERE end_date < ? AND status != 'completed'`
  ).run(firstOfCurrentMonth);

  // 2. On the 1st of the month (UTC), auto-create a sprint for this month if missing
  let created = false;
  if (dayUTC === 1) {
    const monthStart = `${yearUTC}-${pad(monthUTC)}-01`;
    const lastDay = new Date(Date.UTC(yearUTC, monthUTC, 0)).getUTCDate();
    const monthEnd = `${yearUTC}-${pad(monthUTC)}-${pad(lastDay)}`;

    // Check if a sprint already covers this exact month range
    const existing = db.prepare(
      `SELECT id FROM sprints WHERE start_date = ? AND end_date = ?`
    ).get(monthStart, monthEnd);

    if (!existing) {
      // Build month name in UTC (e.g. "September 2026")
      const monthName = new Date(Date.UTC(yearUTC, monthUTC - 1, 1))
        .toLocaleDateString('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' });
      db.prepare(
        `INSERT INTO sprints (name, start_date, end_date, status) VALUES (?, ?, ?, 'active')`
      ).run(monthName, monthStart, monthEnd);
      created = true;
    }
  }

  return { completed: completedResult.changes, created };
}

export function getAllSprints(): Sprint[] {
  const db = getDb();
  return db.prepare('SELECT * FROM sprints ORDER BY start_date DESC').all() as Sprint[];
}

export function getSprintById(id: number): Sprint | undefined {
  const db = getDb();
  return db.prepare('SELECT * FROM sprints WHERE id = ?').get(id) as Sprint | undefined;
}

export function createSprint(input: CreateSprintInput): Sprint {
  const db = getDb();
  const result = db.prepare(
    'INSERT INTO sprints (name, start_date, end_date, status) VALUES (?, ?, ?, ?)'
  ).run(input.name, input.start_date, input.end_date, input.status ?? 'planning');
  return getSprintById(result.lastInsertRowid as number)!;
}

export function updateSprint(id: number, input: UpdateSprintInput): Sprint | undefined {
  const db = getDb();
  const existing = getSprintById(id);
  if (!existing) return undefined;
  db.prepare(
    'UPDATE sprints SET name = ?, start_date = ?, end_date = ?, status = ? WHERE id = ?'
  ).run(
    input.name ?? existing.name,
    input.start_date ?? existing.start_date,
    input.end_date ?? existing.end_date,
    input.status ?? existing.status,
    id
  );
  return getSprintById(id);
}

export function deleteSprint(id: number): boolean {
  const db = getDb();
  const result = db.prepare('DELETE FROM sprints WHERE id = ?').run(id);
  return result.changes > 0;
}
