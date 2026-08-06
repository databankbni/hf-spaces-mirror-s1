/**
 * Task comments routes.
 * GET is public; POST/DELETE require auth.
 * @module server/routes/comments
 */
import { Router, Request } from 'express';
import { requireAuth } from '../middleware/auth';
import { getDb } from '../storage/db';

const router = Router({ mergeParams: true });

interface Comment {
  id: number;
  task_id: number;
  user_id: number;
  username: string;
  body: string;
  created_at: string;
}

type TaskParams = { taskId: string };
type TaskCommentParams = { taskId: string; id: string };

// GET /api/tasks/:taskId/comments
router.get('/', (req: Request<TaskParams>, res) => {
  const db = getDb();
  const comments = db
    .prepare('SELECT * FROM task_comments WHERE task_id = ? ORDER BY created_at ASC')
    .all(Number(req.params.taskId)) as Comment[];
  res.json(comments);
});

// POST /api/tasks/:taskId/comments
router.post('/', requireAuth, (req: Request<TaskParams>, res) => {
  const { body } = req.body as { body: string };
  if (!body?.trim()) return res.status(400).json({ error: 'Comment body is required' });
  const db = getDb();
  const result = db
    .prepare('INSERT INTO task_comments (task_id, user_id, username, body) VALUES (?, ?, ?, ?)')
    .run(Number(req.params.taskId), req.user!.id, req.user!.username, body.trim());
  const comment = db.prepare('SELECT * FROM task_comments WHERE id = ?').get(result.lastInsertRowid) as Comment;
  res.status(201).json(comment);
});

// DELETE /api/tasks/:taskId/comments/:id
router.delete('/:id', requireAuth, (req: Request<TaskCommentParams>, res) => {
  const db = getDb();
  const comment = db
    .prepare('SELECT * FROM task_comments WHERE id = ? AND task_id = ?')
    .get(Number(req.params.id), Number(req.params.taskId)) as Comment | undefined;
  if (!comment) return res.status(404).json({ error: 'Comment not found' });
  if (comment.user_id !== req.user!.id && req.user!.role !== 'admin') {
    return res.status(403).json({ error: 'Not allowed' });
  }
  db.prepare('DELETE FROM task_comments WHERE id = ?').run(Number(req.params.id));
  res.status(204).send();
});

export default router;
