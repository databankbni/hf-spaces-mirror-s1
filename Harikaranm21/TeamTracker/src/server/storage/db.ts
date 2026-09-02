/**
 * SQLite database initialization and schema management for TeamTracker.
 * @module server/storage/db
 */
import Database from 'better-sqlite3';
import path from 'path';
import fs from 'fs';

const DB_PATH =
  process.env.DB_PATH ??
  (process.env.NODE_ENV === 'production'
    ? '/data/teamtracker.db'
    : path.join(process.cwd(), 'data', 'teamtracker.db'));
const DB_DIR = path.dirname(DB_PATH);

let _db: Database.Database | null = null;

/**
 * Returns the singleton database instance, creating it if needed.
 */
export function getDb(): Database.Database {
  if (_db) return _db;
  fs.mkdirSync(DB_DIR, { recursive: true });
  _db = new Database(DB_PATH);
  _db.pragma('journal_mode = WAL');
  _db.pragma('foreign_keys = ON');
  initSchema(_db);
  return _db;
}

function initSchema(db: Database.Database): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS teams (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL UNIQUE,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS members (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      email TEXT NOT NULL UNIQUE,
      avatar_color TEXT NOT NULL DEFAULT '#6E56CF',
      team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS sprints (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      start_date TEXT NOT NULL,
      end_date TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'planning' CHECK(status IN ('planning', 'active', 'completed')),
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS tasks (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT 'todo' CHECK(status IN ('todo', 'in_progress', 'review', 'done')),
      priority TEXT NOT NULL DEFAULT 'medium' CHECK(priority IN ('high', 'medium', 'low')),
      assignee_id INTEGER REFERENCES members(id) ON DELETE SET NULL,
      team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL,
      sprint_id INTEGER REFERENCES sprints(id) ON DELETE SET NULL,
      labels TEXT NOT NULL DEFAULT '',
      due_date TEXT,
      position INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT NOT NULL UNIQUE,
      email TEXT NOT NULL UNIQUE,
      password_hash TEXT NOT NULL,
      role TEXT NOT NULL DEFAULT 'pending' CHECK(role IN ('pending', 'viewer', 'editor', 'admin')),
      team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS calendar_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      title TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '',
      event_type TEXT NOT NULL DEFAULT 'task' CHECK(event_type IN ('task', 'meeting', 'reminder', 'other')),
      date TEXT NOT NULL,
      start_time TEXT,
      end_time TEXT,
      color TEXT NOT NULL DEFAULT '#6E56CF',
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
    CREATE INDEX IF NOT EXISTS idx_tasks_sprint ON tasks(sprint_id);
    CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assignee_id);
    CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
    CREATE INDEX IF NOT EXISTS idx_calendar_user_date ON calendar_events(user_id, date);
  `);

  // Migrations: safely add columns to existing databases
  const taskCols = db.pragma('table_info(tasks)') as { name: string }[];
  const colNames = taskCols.map((c) => c.name);
  if (!colNames.includes('due_date')) {
    db.exec('ALTER TABLE tasks ADD COLUMN due_date TEXT');
  }
  if (!colNames.includes('team_id')) {
    db.exec('ALTER TABLE tasks ADD COLUMN team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL');
  }

  const memberCols = db.pragma('table_info(members)') as { name: string }[];
  if (!memberCols.some((c) => c.name === 'team_id')) {
    db.exec('ALTER TABLE members ADD COLUMN team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL');
  }
  db.exec('CREATE INDEX IF NOT EXISTS idx_tasks_team ON tasks(team_id)');
  db.exec('CREATE INDEX IF NOT EXISTS idx_members_team ON members(team_id)');

  // Migration: create calendar_events table if it doesn't exist on older DBs
  db.exec(`
    CREATE TABLE IF NOT EXISTS calendar_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      title TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '',
      event_type TEXT NOT NULL DEFAULT 'task' CHECK(event_type IN ('task', 'meeting', 'reminder', 'other')),
      date TEXT NOT NULL,
      start_time TEXT,
      end_time TEXT,
      color TEXT NOT NULL DEFAULT '#6E56CF',
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
  `);
  db.exec(`CREATE INDEX IF NOT EXISTS idx_calendar_user_date ON calendar_events(user_id, date)`);

  // Migration: create task_comments table
  db.exec(`
    CREATE TABLE IF NOT EXISTS task_comments (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      username TEXT NOT NULL,
      body TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
  `);
  db.exec(`CREATE INDEX IF NOT EXISTS idx_comments_task ON task_comments(task_id)`);

  // Migration: expand users.role CHECK constraint to include 'viewer'
  // SQLite doesn't support ALTER COLUMN, so we recreate the table if needed.
  const userRoleInfo = db.pragma('table_info(users)') as { name: string; type: string }[];
  const hasUserTeam = userRoleInfo.some(c => c.name === 'team_id');
  const roleColExists = userRoleInfo.find(c => c.name === 'role');
  // Check if the current constraint already allows 'viewer' by trying to find it in sqlite_master
  const userTableDef = (db.prepare("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").get() as { sql: string } | undefined)?.sql ?? '';
  if (roleColExists && !userTableDef.includes("'viewer'")) {
    // Recreate users table with updated CHECK constraint
    db.exec(`
      PRAGMA foreign_keys = OFF;

      CREATE TABLE IF NOT EXISTS users_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'pending' CHECK(role IN ('pending', 'viewer', 'editor', 'admin')),
        team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
      );

      INSERT INTO users_new (id, username, email, password_hash, role, team_id, created_at)
        SELECT id, username, email, password_hash, role, ${hasUserTeam ? 'team_id' : 'NULL'}, created_at FROM users;

      DROP TABLE users;
      ALTER TABLE users_new RENAME TO users;

      CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

      PRAGMA foreign_keys = ON;
    `);
  }

  const finalUserCols = db.pragma('table_info(users)') as { name: string }[];
  if (!finalUserCols.some((c) => c.name === 'team_id')) {
    db.exec('ALTER TABLE users ADD COLUMN team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL');
  }
  db.exec('CREATE INDEX IF NOT EXISTS idx_users_team ON users(team_id)');
}
