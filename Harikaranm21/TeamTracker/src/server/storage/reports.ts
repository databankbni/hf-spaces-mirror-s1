/**
 * Reporting queries for TeamTracker dashboard.
 * All functions accept an optional sprintId to scope results to a single month.
 * @module server/storage/reports
 */
import { getDb } from './db';
import type {
  VelocityDataPoint,
  AssigneeDistribution,
  StatusDistribution,
  DashboardStats
} from '../../shared/types';

export function getVelocityData(): VelocityDataPoint[] {
  const db = getDb();
  const sprints = db.prepare('SELECT * FROM sprints ORDER BY start_date ASC').all() as Array<{
    id: number; name: string;
  }>;

  return sprints.map((sprint) => {
    const total = (db.prepare('SELECT COUNT(*) as c FROM tasks WHERE sprint_id = ?').get(sprint.id) as { c: number }).c;
    const completed = (db.prepare("SELECT COUNT(*) as c FROM tasks WHERE sprint_id = ? AND status = 'done'").get(sprint.id) as { c: number }).c;
    return { sprint_name: sprint.name, completed, total };
  });
}

export function getAssigneeDistribution(sprintId?: number): AssigneeDistribution[] {
  const db = getDb();
  if (sprintId != null) {
    return db.prepare(`
      SELECT m.name, m.avatar_color as color, COUNT(t.id) as count
      FROM members m
      LEFT JOIN tasks t ON t.assignee_id = m.id AND t.sprint_id = ?
      GROUP BY m.id
      ORDER BY count DESC
    `).all(sprintId) as AssigneeDistribution[];
  }
  return db.prepare(`
    SELECT m.name, m.avatar_color as color, COUNT(t.id) as count
    FROM members m
    LEFT JOIN tasks t ON t.assignee_id = m.id
    GROUP BY m.id
    ORDER BY count DESC
  `).all() as AssigneeDistribution[];
}

export function getStatusDistribution(sprintId?: number): StatusDistribution[] {
  const db = getDb();
  if (sprintId != null) {
    return db.prepare(
      "SELECT status, COUNT(*) as count FROM tasks WHERE sprint_id = ? GROUP BY status"
    ).all(sprintId) as StatusDistribution[];
  }
  return db.prepare(
    "SELECT status, COUNT(*) as count FROM tasks GROUP BY status"
  ).all() as StatusDistribution[];
}

export function getDashboardStats(sprintId?: number): DashboardStats {
  const db = getDb();
  const members = (db.prepare('SELECT COUNT(*) as c FROM members').get() as { c: number }).c;
  const activeSprints = (db.prepare("SELECT COUNT(*) as c FROM sprints WHERE status = 'active'").get() as { c: number }).c;

  let total: number;
  let completed: number;
  let inProgress: number;

  if (sprintId != null) {
    total = (db.prepare('SELECT COUNT(*) as c FROM tasks WHERE sprint_id = ?').get(sprintId) as { c: number }).c;
    completed = (db.prepare("SELECT COUNT(*) as c FROM tasks WHERE sprint_id = ? AND status = 'done'").get(sprintId) as { c: number }).c;
    inProgress = (db.prepare("SELECT COUNT(*) as c FROM tasks WHERE sprint_id = ? AND status = 'in_progress'").get(sprintId) as { c: number }).c;
  } else {
    total = (db.prepare('SELECT COUNT(*) as c FROM tasks').get() as { c: number }).c;
    completed = (db.prepare("SELECT COUNT(*) as c FROM tasks WHERE status = 'done'").get() as { c: number }).c;
    inProgress = (db.prepare("SELECT COUNT(*) as c FROM tasks WHERE status = 'in_progress'").get() as { c: number }).c;
  }

  return {
    totalTasks: total,
    openTasks: total - completed,
    completedTasks: completed,
    inProgressTasks: inProgress,
    totalMembers: members,
    activeSprints,
  };
}
