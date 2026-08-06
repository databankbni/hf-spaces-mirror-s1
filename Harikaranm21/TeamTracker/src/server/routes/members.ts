/**
 * Member REST API routes for TeamTracker.
 * GET is public; writes require auth.
 * @module server/routes/members
 */
import { Router } from 'express';
import * as MemberStore from '../storage/members';
import { requireAuth } from '../middleware/auth';
import type { CreateMemberInput } from '../../shared/types';

const router = Router();

router.get('/', (_req, res) => {
  res.json(MemberStore.getAllMembers());
});

router.post('/', requireAuth, (req, res) => {
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

router.patch('/:id', requireAuth, (req, res) => {
  const member = MemberStore.updateMember(Number(req.params.id), req.body);
  if (!member) return res.status(404).json({ error: 'Member not found' });
  res.json(member);
});

router.delete('/:id', requireAuth, (req, res) => {
  const deleted = MemberStore.deleteMember(Number(req.params.id));
  if (!deleted) return res.status(404).json({ error: 'Member not found' });
  res.status(204).send();
});

export default router;
