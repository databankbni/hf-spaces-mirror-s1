/**
 * Admin data management routes — bulk delete old data.
 * All routes require admin role.
 * @module server/routes/admin
 */
import { Router } from 'express';
import { requireAdmin } from '../middleware/auth';
import { getDb } from '../storage/db';

const router = Router();
router.use(requireAdmin);

// GET /api/admin/stats — storage overview
router.get('/stats', (_req, res) => {
  const db = getDb();
  const tasks    = (db.prepare('SELECT COUNT(*) as c FROM tasks').get() as { c: number }).c;
  const done     = (db.prepare("SELECT COUNT(*) as c FROM tasks WHERE status='done'").get() as { c: number }).c;
  const events   = (db.prepare('SELECT COUNT(*) as c FROM calendar_events').get() as { c: number }).c;
  const sprints  = (db.prepare('SELECT COUNT(*) as c FROM sprints').get() as { c: number }).c;
  const completed = (db.prepare("SELECT COUNT(*) as c FROM sprints WHERE status='completed'").get() as { c: number }).c;
  const members  = (db.prepare('SELECT COUNT(*) as c FROM members').get() as { c: number }).c;
  const users    = (db.prepare('SELECT COUNT(*) as c FROM users').get() as { c: number }).c;
  res.json({ tasks, doneTasks: done, calendarEvents: events, months: sprints, completedMonths: completed, members, users });
});

// DELETE /api/admin/cleanup/done-tasks — delete all tasks with status=done
router.delete('/cleanup/done-tasks', (_req, res) => {
  const db = getDb();
  const result = db.prepare("DELETE FROM tasks WHERE status='done'").run();
  res.json({ deleted: result.changes, message: `Deleted ${result.changes} completed tasks` });
});

// DELETE /api/admin/cleanup/completed-months — delete completed months (and unassign their tasks)
router.delete('/cleanup/completed-months', (_req, res) => {
  const db = getDb();
  // Unassign tasks from completed months first
  const unassign = db.prepare(`
    UPDATE tasks SET sprint_id = NULL WHERE sprint_id IN (
      SELECT id FROM sprints WHERE status = 'completed'
    )
  `).run();
  const result = db.prepare("DELETE FROM sprints WHERE status='completed'").run();
  res.json({ deleted: result.changes, unassigned: unassign.changes, message: `Deleted ${result.changes} completed months, unassigned ${unassign.changes} tasks` });
});

// DELETE /api/admin/cleanup/old-calendar — delete calendar events older than N months
router.delete('/cleanup/old-calendar', (req, res) => {
  const months = Number(req.query.months) || 3;
  const db = getDb();
  const cutoff = new Date();
  cutoff.setMonth(cutoff.getMonth() - months);
  const cutoffStr = cutoff.toISOString().slice(0, 10);
  const result = db.prepare('DELETE FROM calendar_events WHERE date < ?').run(cutoffStr);
  res.json({ deleted: result.changes, message: `Deleted ${result.changes} calendar events older than ${months} months` });
});

// DELETE /api/admin/cleanup/all-done — delete everything completed (done tasks + completed months + old calendar)
router.delete('/cleanup/all', (req, res) => {
  const calendarMonths = Number(req.query.calendarMonths) || 3;
  const db = getDb();

  const doneTasks = db.prepare("DELETE FROM tasks WHERE status='done'").run();

  const unassign = db.prepare(`
    UPDATE tasks SET sprint_id = NULL WHERE sprint_id IN (
      SELECT id FROM sprints WHERE status = 'completed'
    )
  `).run();
  const completedMonths = db.prepare("DELETE FROM sprints WHERE status='completed'").run();

  const cutoff = new Date();
  cutoff.setMonth(cutoff.getMonth() - calendarMonths);
  const cutoffStr = cutoff.toISOString().slice(0, 10);
  const oldCalendar = db.prepare('DELETE FROM calendar_events WHERE date < ?').run(cutoffStr);

  res.json({
    doneTasks: doneTasks.changes,
    completedMonths: completedMonths.changes,
    unassignedTasks: unassign.changes,
    oldCalendarEvents: oldCalendar.changes,
    message: `Cleanup complete: ${doneTasks.changes} done tasks, ${completedMonths.changes} completed months, ${oldCalendar.changes} old calendar events deleted`,
  });
});

export default router;
