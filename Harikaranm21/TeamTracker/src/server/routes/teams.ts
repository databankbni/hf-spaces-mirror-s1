import { Router } from 'express';
import * as TeamStore from '../storage/teams';
import { requireAdmin } from '../middleware/auth';

const router = Router();
router.use(requireAdmin);

router.get('/', (_req, res) => res.json(TeamStore.getAllTeams()));

router.post('/', (req, res) => {
  const name = String(req.body?.name ?? '').trim();
  if (!name) return res.status(400).json({ error: 'Team name is required' });
  try {
    res.status(201).json(TeamStore.createTeam({ name }));
  } catch (err: unknown) {
    if (String(err).includes('UNIQUE')) return res.status(409).json({ error: 'Team name already exists' });
    res.status(500).json({ error: 'Failed to create team' });
  }
});

router.patch('/:id', (req, res) => {
  const name = String(req.body?.name ?? '').trim();
  if (!name) return res.status(400).json({ error: 'Team name is required' });
  const team = TeamStore.updateTeam(Number(req.params.id), name);
  if (!team) return res.status(404).json({ error: 'Team not found' });
  res.json(team);
});

router.delete('/:id', (req, res) => {
  if (!TeamStore.deleteTeam(Number(req.params.id))) return res.status(404).json({ error: 'Team not found' });
  res.status(204).send();
});

export default router;