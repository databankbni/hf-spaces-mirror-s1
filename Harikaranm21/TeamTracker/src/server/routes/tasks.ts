/**
 * Task REST API routes for TeamTracker.
 * All routes require authentication. Task visibility and viewer writes are scoped by role.
 * @module server/routes/tasks
 */
import { Router } from 'express';
import * as TaskStore from '../storage/tasks';
import { requireAuth, requireEditor } from '../middleware/auth';
import * as UserStore from '../storage/users';
import * as MemberStore from '../storage/members';
import type { CreateTaskInput, UpdateTaskInput } from '../../shared/types';

const router = Router();

// Auth-required reads (viewers can see tasks)
router.get('/', requireAuth, (req, res) => {
  res.json(TaskStore.getTasksForUser(req.user!.id, req.user!.role));
});

router.get('/:id', requireAuth, (req, res) => {
  const task = TaskStore.getTaskById(Number(req.params.id), req.user!.id, req.user!.role);
  if (!task) return res.status(404).json({ error: 'Task not found' });
  res.json(task);
});

// Active users can create; viewer ownership is normalized below.
router.post('/', requireAuth, (req, res) => {
  if (req.user!.role !== 'viewer' && req.user!.role !== 'editor' && req.user!.role !== 'admin') {
    return res.status(403).json({ error: 'Task creation is not allowed' });
  }
  const user = UserStore.getUserById(req.user!.id);
  if (!user) return res.status(401).json({ error: 'User not found' });
  const member = MemberStore.getMemberByEmail(user.email);
  if (req.user!.role === 'viewer' && !member) return res.status(400).json({ error: 'No member profile found' });
  const requested = req.body as CreateTaskInput;
  const input: CreateTaskInput = req.user!.role === 'viewer'
    ? { ...requested, assignee_id: member!.id, team_id: user.team_id }
    : user.role === 'admin'
      ? requested
      : { ...requested, team_id: user.team_id };
  if (user.role !== 'admin' && input.assignee_id != null) {
    const assignee = MemberStore.getMemberById(input.assignee_id);
    if (!assignee || assignee.team_id !== user.team_id) {
      return res.status(403).json({ error: 'You may only assign tasks within your team' });
    }
  }
  if (!input.title?.trim()) {
    return res.status(400).json({ error: 'Title is required' });
  }
  const task = TaskStore.createTask(input);
  res.status(201).json(task);
});

router.patch('/:id', requireAuth, (req, res) => {
  if (!TaskStore.canAccessTask(Number(req.params.id), req.user!.id, req.user!.role)) {
    return res.status(404).json({ error: 'Task not found' });
  }
  if (req.user!.role === 'viewer') {
    const user = UserStore.getUserById(req.user!.id);
    const member = user && MemberStore.getMemberByEmail(user.email);
    if (!member || (req.body as CreateTaskInput).assignee_id !== undefined && (req.body as CreateTaskInput).assignee_id !== member.id) {
      return res.status(403).json({ error: 'Viewers may only edit their own tasks' });
    }
  }
  const requested = req.body as UpdateTaskInput;
  const currentUser = UserStore.getUserById(req.user!.id);
  if (!currentUser) return res.status(401).json({ error: 'User not found' });
  if (currentUser?.role !== 'admin' && requested.assignee_id != null) {
    const assignee = MemberStore.getMemberById(requested.assignee_id);
    if (!assignee || assignee.team_id !== currentUser.team_id) {
      return res.status(403).json({ error: 'You may only assign tasks within your team' });
    }
  }
  const input = currentUser.role === 'admin'
    ? requested
    : { ...requested, team_id: currentUser?.team_id };
  const task = TaskStore.updateTask(Number(req.params.id), input);
  if (!task) return res.status(404).json({ error: 'Task not found' });
  res.json(task);
});

router.patch('/:id/move', requireAuth, (req, res) => {
  if (!TaskStore.canAccessTask(Number(req.params.id), req.user!.id, req.user!.role)) {
    return res.status(404).json({ error: 'Task not found' });
  }
  const { status, position } = req.body as { status: string; position: number };
  const task = TaskStore.moveTask(Number(req.params.id), status, position);
  if (!task) return res.status(404).json({ error: 'Task not found' });
  res.json(task);
});

router.delete('/:id', requireEditor, (req, res) => {
  if (!TaskStore.canAccessTask(Number(req.params.id), req.user!.id, req.user!.role)) {
    return res.status(404).json({ error: 'Task not found' });
  }
  const deleted = TaskStore.deleteTask(Number(req.params.id));
  if (!deleted) return res.status(404).json({ error: 'Task not found' });
  res.status(204).send();
});

export default router;
