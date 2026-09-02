/**
 * Member REST API routes for TeamTracker.
 * All routes require authentication. Viewers can read their visible team members;
 * writes require editor+.
 * @module server/routes/members
 */
import { Router } from 'express';
import * as MemberStore from '../storage/members';
import { requireAuth, requireEditor } from '../middleware/auth';
import type { CreateMemberInput } from '../../shared/types';

const router = Router();

// All active users can view the members in their visible team scope.
router.get('/', requireAuth, (req, res) => {
  res.json(MemberStore.getMembersForUser(req.user!.id, req.user!.role));
});

router.post('/', requireEditor, (req, res) => {
  const input = req.body as CreateMemberInput;
  if (!input.name?.trim() || !input.email?.trim()) {
    return res.status(400).json({ error: 'Name and email are required' });
  }
  try {
    const member = MemberStore.createMember(input);
    res.status(201).json(member);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    if (msg.includes('UNIQUE')) {
      return res.status(409).json({ error: 'Email already exists' });
    }
    res.status(500).json({ error: 'Failed to create member' });
  }
});

router.patch('/:id', requireEditor, (req, res) => {
  const member = MemberStore.updateMember(Number(req.params.id), req.body);
  if (!member) return res.status(404).json({ error: 'Member not found' });
  res.json(member);
});

router.delete('/:id', requireEditor, (req, res) => {
  const deleted = MemberStore.deleteMember(Number(req.params.id));
  if (!deleted) return res.status(404).json({ error: 'Member not found' });
  res.status(204).send();
});

export default router;
