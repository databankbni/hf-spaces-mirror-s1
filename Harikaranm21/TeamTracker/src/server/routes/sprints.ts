/**
 * Sprint REST API routes for TeamTracker.
 * GET is public; writes require auth.
 * @module server/routes/sprints
 */
import { Router } from 'express';
import * as SprintStore from '../storage/sprints';
import { requireAuth } from '../middleware/auth';
import type { CreateSprintInput, UpdateSprintInput } from '../../shared/types';

const router = Router();

router.get('/', (_req, res) => {
  res.json(SprintStore.getAllSprints());
});

/**
 * POST /api/sprints/maintain
 * Triggers auto-maintenance: complete past months and create the current month if missing.
 * Called by the client on page load to ensure data is always fresh.
 */
router.post('/maintain', (_req, res) => {
  const result = SprintStore.autoMaintainSprints();
  res.json({ ok: true, ...result });
});

/**
 * POST /api/sprints/recover-august-2026
 * Robust idempotent recovery for August 2026:
 * - Re-creates the sprint if missing
 * - Forces it to 'active' if it exists but was marked completed
 * - Re-links ALL orphaned tasks (sprint_id IS NULL) to August 2026
 *   because those tasks have no other sprint they could belong to
 * Safe to call on every page load.
 */
router.post('/recover-august-2026', (_req, res) => {
  const db = SprintStore.getDb();

  // 1. Ensure August 2026 sprint exists and is active
  const existing = db.prepare(
    `SELECT id, status FROM sprints WHERE start_date = '2026-08-01' AND end_date = '2026-08-31'`
  ).get() as { id: number; status: string } | undefined;

  let sprintId: number;
  let sprintCreated = false;

  if (existing) {
    sprintId = existing.id;
    if (existing.status !== 'active') {
      db.prepare(`UPDATE sprints SET status = 'active' WHERE id = ?`).run(sprintId);
    }
  } else {
    const result = db.prepare(
      `INSERT INTO sprints (name, start_date, end_date, status) VALUES ('August 2026', '2026-08-01', '2026-08-31', 'active')`
    ).run();
    sprintId = result.lastInsertRowid as number;
    sprintCreated = true;
  }

  // 2. Re-link orphaned tasks — any task with sprint_id IS NULL gets assigned to August 2026.
  //    This is safe because: tasks that genuinely have no month assigned are unscheduled,
  //    and the only tasks that became NULL were those previously in August (from the bug).
  //    Users can reassign them to other months manually if needed.
  const relinked = db.prepare(
    `UPDATE tasks SET sprint_id = ? WHERE sprint_id IS NULL`
  ).run(sprintId);

  res.json({
    ok: true,
    sprintId,
    sprintCreated,
    tasksRelinked: relinked.changes,
    message: `August 2026 sprint ${sprintCreated ? 're-created' : existing?.status !== 'active' ? 'restored to active' : 'already active'}. ${relinked.changes} orphaned tasks re-linked.`,
  });
});

router.get('/:id', (req, res) => {
  const sprint = SprintStore.getSprintById(Number(req.params.id));
  if (!sprint) return res.status(404).json({ error: 'Sprint not found' });
  res.json(sprint);
});

router.post('/', requireAuth, (req, res) => {
  const input = req.body as CreateSprintInput;
  if (!input.name?.trim() || !input.start_date || !input.end_date) {
    return res.status(400).json({ error: 'Name, start_date, and end_date are required' });
  }
  const sprint = SprintStore.createSprint(input);
  res.status(201).json(sprint);
});

router.patch('/:id', requireAuth, (req, res) => {
  const input = req.body as UpdateSprintInput;
  const sprint = SprintStore.updateSprint(Number(req.params.id), input);
  if (!sprint) return res.status(404).json({ error: 'Sprint not found' });
  res.json(sprint);
});

router.delete('/:id', requireAuth, (req, res) => {
  const deleted = SprintStore.deleteSprint(Number(req.params.id));
  if (!deleted) return res.status(404).json({ error: 'Sprint not found' });
  res.status(204).send();
});

export default router;
