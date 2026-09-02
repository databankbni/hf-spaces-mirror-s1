/**
 * Reporting/metrics API routes for TeamTracker dashboard.
 * All endpoints require authentication (viewer+ can see stats).
 * Accept optional ?sprintId= to scope results to a single month.
 * @module server/routes/reports
 */
import { Router } from 'express';
import * as ReportStore from '../storage/reports';
import { requireAuth } from '../middleware/auth';

const router = Router();

function parseSprintId(value: unknown): number | undefined {
  if (value === undefined || value === null || value === '') return undefined;
  const n = Number(value);
  return isNaN(n) ? undefined : n;
}

function parseTeamId(value: unknown, role: string): number | undefined {
  if (role !== 'admin' || value === undefined || value === null || value === '') return undefined;
  const n = Number(value);
  return Number.isInteger(n) ? n : undefined;
}

router.get('/stats', requireAuth, (req, res) => {
  const sprintId = parseSprintId(req.query.sprintId);
  const teamId = parseTeamId(req.query.teamId, req.user!.role);
  res.json(ReportStore.getDashboardStats(req.user!.id, req.user!.role, sprintId, teamId));
});

router.get('/velocity', requireAuth, (req, res) => {
  const teamId = parseTeamId(req.query.teamId, req.user!.role);
  res.json(ReportStore.getVelocityData(req.user!.id, req.user!.role, teamId));
});

router.get('/assignee-distribution', requireAuth, (req, res) => {
  const sprintId = parseSprintId(req.query.sprintId);
  const teamId = parseTeamId(req.query.teamId, req.user!.role);
  res.json(ReportStore.getAssigneeDistribution(req.user!.id, req.user!.role, sprintId, teamId));
});

router.get('/status-distribution', requireAuth, (req, res) => {
  const sprintId = parseSprintId(req.query.sprintId);
  const teamId = parseTeamId(req.query.teamId, req.user!.role);
  res.json(ReportStore.getStatusDistribution(req.user!.id, req.user!.role, sprintId, teamId));
});

export default router;
