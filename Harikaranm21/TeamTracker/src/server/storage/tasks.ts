/**
 * Task data access layer for TeamTracker.
 * @module server/storage/tasks
 */
import { getDb } from './db';
import type { Task, CreateTaskInput, UpdateTaskInput } from '../../shared/types';

const TASK_SELECT = `
  SELECT t.*,
    m.name as assignee_name,
    m.avatar_color as assignee_color,
    s.name as sprint_name
  FROM tasks t
  LEFT JOIN members m ON t.assignee_id = m.id
  LEFT JOIN sprints s ON t.sprint_id = s.id
`;

export function getAllTasks(): Task[] {
  const db = getDb();
  return db.prepare(`${TASK_SELECT} ORDER BY t.position ASC, t.id ASC`).all() as Task[];
}

export function getTasksByStatus(status: string): Task[] {
  const db = getDb();
  return db.prepare(`${TASK_SELECT} WHERE t.status = ? ORDER BY t.position ASC, t.id ASC`).all(status) as Task[];
}

export function getTaskById(id: number): Task | undefined {
  const db = getDb();
  return db.prepare(`${TASK_SELECT} WHERE t.id = ?`).get(id) as Task | undefined;
}

export function createTask(input: CreateTaskInput): Task {
  const db = getDb();
  const maxPos = (db.prepare('SELECT COALESCE(MAX(position),0) as m FROM tasks WHERE status = ?').get(input.status ?? 'todo') as { m: number }).m;
  const result = db.prepare(`
    INSERT INTO tasks (title, description, status, priority, assignee_id, sprint_id, labels, due_date, position)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).run(
    input.title,
    input.description ?? '',
    input.status ?? 'todo',
    input.priority ?? 'medium',
    input.assignee_id ?? null,
    input.sprint_id ?? null,
    input.labels ?? '',
    input.due_date ?? null,
    maxPos + 1
  );
  return getTaskById(result.lastInsertRowid as number)!;
}

export function updateTask(id: number, input: UpdateTaskInput): Task | undefined {
  const db = getDb();
  const existing = db.prepare('SELECT * FROM tasks WHERE id = ?').get(id) as Task | undefined;
  if (!existing) return undefined;

  const updated = {
    title: input.title ?? existing.title,
    description: input.description ?? existing.description,
    status: input.status ?? existing.status,
    priority: input.priority ?? existing.priority,
    assignee_id: input.assignee_id !== undefined ? input.assignee_id : existing.assignee_id,
    sprint_id: input.sprint_id !== undefined ? input.sprint_id : existing.sprint_id,
    labels: input.labels ?? existing.labels,
    due_date: input.due_date !== undefined ? input.due_date : existing.due_date,
    position: input.position ?? existing.position,
  };

  db.prepare(`
    UPDATE tasks SET
      title = ?, description = ?, status = ?, priority = ?,
      assignee_id = ?, sprint_id = ?, labels = ?, due_date = ?, position = ?,
      updated_at = datetime('now')
    WHERE id = ?
  `).run(
    updated.title, updated.description, updated.status, updated.priority,
    updated.assignee_id, updated.sprint_id, updated.labels, updated.due_date, updated.position,
    id
  );
  return getTaskById(id);
}

export function deleteTask(id: number): boolean {
  const db = getDb();
  const result = db.prepare('DELETE FROM tasks WHERE id = ?').run(id);
  return result.changes > 0;
}

export function moveTask(id: number, newStatus: string, newPosition: number): Task | undefined {
  const db = getDb();
  const task = db.prepare('SELECT * FROM tasks WHERE id = ?').get(id) as Task | undefined;
  if (!task) return undefined;

  // Shift other tasks in destination column
  db.prepare(`
    UPDATE tasks SET position = position + 1, updated_at = datetime('now')
    WHERE status = ? AND position >= ? AND id != ?
  `).run(newStatus, newPosition, id);

  db.prepare(`
    UPDATE tasks SET status = ?, position = ?, updated_at = datetime('now')
    WHERE id = ?
  `).run(newStatus, newPosition, id);

  return getTaskById(id);
}
