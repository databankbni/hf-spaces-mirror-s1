/**
 * Task REST API routes for TeamTracker.
 * GET routes are public; write routes require authentication.
 * @module server/routes/tasks
 */
import { Router } from 'express';
import * as TaskStore from '../storage/tasks';
import { requireAuth } from '../middleware/auth';
import type { CreateTaskInput, UpdateTaskInput } from '../../shared/types';

const router = Router();

// Public reads
router.get('/', (_req, res) => {
  res.json(TaskStore.getAllTasks());
});

router.get('/:id', (req, res) => {
  const task = TaskStore.getTaskById(Number(req.params.id));
  if (!task) return res.status(404).json({ error: 'Task not found' });
  res.json(task);
});

// Auth-required writes
router.post('/', requireAuth, (req, res) => {
  const input = req.body as CreateTaskInput;
  if (!input.title?.trim()) {
    return res.status(400).json({ error: 'Title is required' });
  }
  const task = TaskStore.createTask(input);
  res.status(201).json(task);
});

router.patch('/:id', requireAuth, (req, res) => {
  const input = req.body as UpdateTaskInput;
  const task = TaskStore.updateTask(Number(req.params.id), input);
  if (!task) return res.status(404).json({ error: 'Task not found' });
  res.json(task);
});

router.patch('/:id/move', requireAuth, (req, res) => {
  const { status, position } = req.body as { status: string; position: number };
  const task = TaskStore.moveTask(Number(req.params.id), status, position);
  if (!task) return res.status(404).json({ error: 'Task not found' });
  res.json(task);
});

router.delete('/:id', requireAuth, (req, res) => {
  const deleted = TaskStore.deleteTask(Number(req.params.id));
  if (!deleted) return res.status(404).json({ error: 'Task not found' });
  res.status(204).send();
});

export default router;
