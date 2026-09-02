import { getDb } from './db';
import type { CreateTeamInput, Team } from '../../shared/types';

export function getAllTeams(): Team[] {
  return getDb().prepare('SELECT * FROM teams ORDER BY name ASC').all() as Team[];
}

export function getTeamById(id: number): Team | undefined {
  return getDb().prepare('SELECT * FROM teams WHERE id = ?').get(id) as Team | undefined;
}

export function createTeam(input: CreateTeamInput): Team {
  const result = getDb().prepare('INSERT INTO teams (name) VALUES (?)').run(input.name.trim());
  return getTeamById(result.lastInsertRowid as number)!;
}

export function updateTeam(id: number, name: string): Team | undefined {
  const team = getTeamById(id);
  if (!team) return undefined;
  getDb().prepare('UPDATE teams SET name = ? WHERE id = ?').run(name.trim(), id);
  return getTeamById(id);
}

export function deleteTeam(id: number): boolean {
  const result = getDb().prepare('DELETE FROM teams WHERE id = ?').run(id);
  return result.changes > 0;
}
