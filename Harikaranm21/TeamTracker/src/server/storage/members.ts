/**
 * Member data access layer for TeamTracker.
 * @module server/storage/members
 */
import { getDb } from './db';
import type { Member, CreateMemberInput } from '../../shared/types';

const COLORS = [
  '#6E56CF', '#E5484D', '#46A758', '#0091FF', '#F76B15',
  '#AB4ABA', '#0096A2', '#D6409F', '#99543B', '#587164'
];

export function getAllMembers(): Member[] {
  const db = getDb();
  return db.prepare('SELECT * FROM members ORDER BY name ASC').all() as Member[];
}

export function getMemberById(id: number): Member | undefined {
  const db = getDb();
  return db.prepare('SELECT * FROM members WHERE id = ?').get(id) as Member | undefined;
}

export function getMemberByEmail(email: string): Member | undefined {
  return getDb().prepare('SELECT * FROM members WHERE email = ?').get(email) as Member | undefined;
}

export function getMembersForUser(userId: number, role: string): Member[] {
  if (role === 'admin') return getAllMembers();
  return getDb().prepare(`
    SELECT m.* FROM members m
    WHERE m.team_id = (SELECT team_id FROM users WHERE id = ?)
       OR m.email = (SELECT email FROM users WHERE id = ?)
    ORDER BY m.name ASC
  `).all(userId, userId) as Member[];
}

export function createMember(input: CreateMemberInput): Member {
  const db = getDb();
  const count = (db.prepare('SELECT COUNT(*) as c FROM members').get() as { c: number }).c;
  const color = input.avatar_color ?? COLORS[count % COLORS.length];
  const result = db.prepare(
    'INSERT INTO members (name, email, avatar_color, team_id) VALUES (?, ?, ?, ?)'
  ).run(input.name, input.email, color, input.team_id ?? null);
  return getMemberById(result.lastInsertRowid as number)!;
}

export function updateMember(id: number, input: Partial<CreateMemberInput>): Member | undefined {
  const db = getDb();
  const existing = getMemberById(id);
  if (!existing) return undefined;
  db.prepare('UPDATE members SET name = ?, email = ?, avatar_color = ?, team_id = ? WHERE id = ?').run(
    input.name ?? existing.name,
    input.email ?? existing.email,
    input.avatar_color ?? existing.avatar_color,
    input.team_id !== undefined ? input.team_id : existing.team_id,
    id
  );
  return getMemberById(id);
}

export function deleteMember(id: number): boolean {
  const db = getDb();
  const result = db.prepare('DELETE FROM members WHERE id = ?').run(id);
  return result.changes > 0;
}
