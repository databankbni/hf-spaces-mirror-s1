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

function taskScope(userId: number, role: string, teamId?: number, alias = 't'): { sql: string; params: number[] } {
  if (role === 'admin' && teamId == null) return { sql: '', params: [] };
  if (role === 'admin' && teamId != null) {
    return {
      sql: `(${alias}.team_id = ? OR (${alias}.team_id IS NULL AND ${alias}.assignee_id IN (SELECT id FROM members WHERE team_id = ?)))`,
      params: [teamId, teamId],
    };
  }
  const ownMember = `(SELECT m.id FROM members m JOIN users u ON u.email = m.email WHERE u.id = ?)`;
  if (role === 'viewer') return { sql: `${alias}.assignee_id = ${ownMember}`, params: [userId] };
  return {
    sql: `(
      ${alias}.team_id = (SELECT team_id FROM users WHERE id = ?)
      OR (${alias}.team_id IS NULL AND ${alias}.assignee_id IN (
        SELECT m.id FROM members m
        WHERE m.team_id = (SELECT team_id FROM users WHERE id = ?)
      ))
      OR ${alias}.assignee_id = ${ownMember}
    )`,
    params: [userId, userId, userId],
  };
}

export function getVelocityData(userId: number, role: string, teamId?: number): VelocityDataPoint[] {
  const db = getDb();
  const sprints = db.prepare('SELECT * FROM sprints ORDER BY start_date ASC').all() as Array<{
    id: number; name: string;
  }>;

  return sprints.map((sprint) => {
    const scope = taskScope(userId, role, teamId);
    const total = (db.prepare(`SELECT COUNT(*) as c FROM tasks t WHERE t.sprint_id = ?${scope.sql ? ` AND ${scope.sql}` : ''}`).get(sprint.id, ...scope.params) as { c: number }).c;
    const completed = (db.prepare(`SELECT COUNT(*) as c FROM tasks t WHERE t.sprint_id = ? AND t.status = 'done'${scope.sql ? ` AND ${scope.sql}` : ''}`).get(sprint.id, ...scope.params) as { c: number }).c;
    return { sprint_name: sprint.name, completed, total };
  });
}

export function getAssigneeDistribution(userId: number, role: string, sprintId?: number, teamId?: number): AssigneeDistribution[] {
  const db = getDb();
  const scope = taskScope(userId, role, teamId);
  const taskFilter = scope.sql ? ` AND ${scope.sql}` : '';
  const memberFilter = role === 'admin' && teamId == null
    ? ''
    : role === 'admin'
      ? ' WHERE m.team_id = ?'
      : ` WHERE m.team_id = (SELECT team_id FROM users WHERE id = ?) OR m.email = (SELECT email FROM users WHERE id = ?)`;
  if (sprintId != null) {
    return db.prepare(`
      SELECT m.name, m.avatar_color as color, COUNT(t.id) as count
      FROM members m
      LEFT JOIN tasks t ON t.assignee_id = m.id AND t.sprint_id = ?${taskFilter}
      ${memberFilter}
      GROUP BY m.id
      ORDER BY count DESC
    `).all(sprintId, ...scope.params, ...(role === 'admin' ? (teamId == null ? [] : [teamId]) : [userId, userId])) as AssigneeDistribution[];
  }
  return db.prepare(`
    SELECT m.name, m.avatar_color as color, COUNT(t.id) as count
    FROM members m
    LEFT JOIN tasks t ON t.assignee_id = m.id${taskFilter}
    ${memberFilter}
    GROUP BY m.id
    ORDER BY count DESC
  `).all(...scope.params, ...(role === 'admin' ? (teamId == null ? [] : [teamId]) : [userId, userId])) as AssigneeDistribution[];
}

export function getStatusDistribution(userId: number, role: string, sprintId?: number, teamId?: number): StatusDistribution[] {
  const db = getDb();
  const scope = taskScope(userId, role, teamId);
  const taskFilter = scope.sql ? ` AND ${scope.sql}` : '';
  if (sprintId != null) {
    return db.prepare(
      `SELECT status, COUNT(*) as count FROM tasks t WHERE sprint_id = ?${taskFilter} GROUP BY status`
    ).all(sprintId, ...scope.params) as StatusDistribution[];
  }
  return db.prepare(
    `SELECT status, COUNT(*) as count FROM tasks t${scope.sql ? ` WHERE ${scope.sql}` : ''} GROUP BY status`
  ).all(...scope.params) as StatusDistribution[];
}

export function getDashboardStats(userId: number, role: string, sprintId?: number, teamId?: number): DashboardStats {
  const db = getDb();
  const scope = taskScope(userId, role, teamId);
  const members = role === 'admin'
    ? (db.prepare('SELECT COUNT(*) as c FROM members').get() as { c: number }).c
    : (db.prepare('SELECT COUNT(*) as c FROM members m WHERE m.team_id = (SELECT team_id FROM users WHERE id = ?) OR m.email = (SELECT email FROM users WHERE id = ?)').get(userId, userId) as { c: number }).c;
  const activeSprints = (db.prepare("SELECT COUNT(*) as c FROM sprints WHERE status = 'active'").get() as { c: number }).c;

  let total: number;
  let completed: number;
  let inProgress: number;

  if (sprintId != null) {
    total = (db.prepare(`SELECT COUNT(*) as c FROM tasks t WHERE sprint_id = ?${scope.sql ? ` AND ${scope.sql}` : ''}`).get(sprintId, ...scope.params) as { c: number }).c;
    completed = (db.prepare(`SELECT COUNT(*) as c FROM tasks t WHERE sprint_id = ? AND status = 'done'${scope.sql ? ` AND ${scope.sql}` : ''}`).get(sprintId, ...scope.params) as { c: number }).c;
    inProgress = (db.prepare(`SELECT COUNT(*) as c FROM tasks t WHERE sprint_id = ? AND status = 'in_progress'${scope.sql ? ` AND ${scope.sql}` : ''}`).get(sprintId, ...scope.params) as { c: number }).c;
  } else {
    total = (db.prepare(`SELECT COUNT(*) as c FROM tasks t${scope.sql ? ` WHERE ${scope.sql}` : ''}`).get(...scope.params) as { c: number }).c;
    completed = (db.prepare(`SELECT COUNT(*) as c FROM tasks t WHERE status = 'done'${scope.sql ? ` AND ${scope.sql}` : ''}`).get(...scope.params) as { c: number }).c;
    inProgress = (db.prepare(`SELECT COUNT(*) as c FROM tasks t WHERE status = 'in_progress'${scope.sql ? ` AND ${scope.sql}` : ''}`).get(...scope.params) as { c: number }).c;
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
