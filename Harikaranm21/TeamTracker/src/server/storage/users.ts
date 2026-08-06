/**
 * User data access layer — authentication & account management.
 * @module server/storage/users
 */
import bcrypt from 'bcryptjs';
import { getDb } from './db';
import type { User, CreateUserInput } from '../../shared/types';

export function getUserByUsername(username: string): User | undefined {
  const db = getDb();
  return db.prepare('SELECT * FROM users WHERE username = ?').get(username) as User | undefined;
}

export function getUserByEmail(email: string): User | undefined {
  const db = getDb();
  return db.prepare('SELECT * FROM users WHERE email = ?').get(email) as User | undefined;
}

export function getUserById(id: number): User | undefined {
  const db = getDb();
  return db.prepare('SELECT * FROM users WHERE id = ?').get(id) as User | undefined;
}

export function getAllUsers(): Omit<User, 'password_hash'>[] {
  const db = getDb();
  return db.prepare('SELECT id, username, email, role, created_at FROM users ORDER BY created_at ASC').all() as Omit<User, 'password_hash'>[];
}

export function getPendingUsers(): Omit<User, 'password_hash'>[] {
  const db = getDb();
  return db
    .prepare("SELECT id, username, email, role, created_at FROM users WHERE role = 'pending' ORDER BY created_at ASC")
    .all() as Omit<User, 'password_hash'>[];
}

export function createUser(input: CreateUserInput): Omit<User, 'password_hash'> {
  const db = getDb();
  const hash = bcrypt.hashSync(input.password, 12);

  // First registered user becomes admin automatically
  const count = (db.prepare('SELECT COUNT(*) as c FROM users').get() as { c: number }).c;
  const role = count === 0 ? 'admin' : 'pending';

  const result = db
    .prepare('INSERT INTO users (username, email, password_hash, role) VALUES (?, ?, ?, ?)')
    .run(input.username, input.email, hash, role);

  return getUserSafe(result.lastInsertRowid as number)!;
}

export function verifyPassword(user: User, password: string): boolean {
  return bcrypt.compareSync(password, user.password_hash);
}

export function updateUserRole(id: number, role: User['role']): Omit<User, 'password_hash'> | undefined {
  const db = getDb();
  db.prepare("UPDATE users SET role = ? WHERE id = ?").run(role, id);
  return getUserSafe(id);
}

export function deleteUser(id: number): boolean {
  const db = getDb();
  const result = db.prepare('DELETE FROM users WHERE id = ?').run(id);
  return result.changes > 0;
}

export function updateUserPassword(id: number, newPassword: string): Omit<User, 'password_hash'> | undefined {
  const db = getDb();
  const hash = bcrypt.hashSync(newPassword, 12);
  db.prepare('UPDATE users SET password_hash = ? WHERE id = ?').run(hash, id);
  return getUserSafe(id);
}

function getUserSafe(id: number): Omit<User, 'password_hash'> | undefined {
  const db = getDb();
  return db
    .prepare('SELECT id, username, email, role, created_at FROM users WHERE id = ?')
    .get(id) as Omit<User, 'password_hash'> | undefined;
}
