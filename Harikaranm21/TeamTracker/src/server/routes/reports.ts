/**
 * Reporting/metrics API routes for TeamTracker dashboard.
 * All endpoints accept an optional ?sprintId= query param to scope results to a single month.
 * @module server/routes/reports
 */
import { Router } from 'express';
import * as ReportStore from '../storage/reports';

const router = Router();

function parseSprintId(value: unknown): number | undefined {
  if (value === undefined || value === null || value === '') return undefined;
  const n = Number(value);
  return isNaN(n) ? undefined : n;
}

router.get('/stats', (req, res) => {
  const sprintId = parseSprintId(req.query.sprintId);
  res.json(ReportStore.getDashboardStats(sprintId));
});

router.get('/velocity', (_req, res) => {
  res.json(ReportStore.getVelocityData());
});

router.get('/assignee-distribution', (req, res) => {
  const sprintId = parseSprintId(req.query.sprintId);
  res.json(ReportStore.getAssigneeDistribution(sprintId));
});

router.get('/status-distribution', (req, res) => {
  const sprintId = parseSprintId(req.query.sprintId);
  res.json(ReportStore.getStatusDistribution(sprintId));
});

export default router;
