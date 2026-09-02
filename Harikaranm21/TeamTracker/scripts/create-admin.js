#!/usr/bin/env node
const fs = require('fs');
const path = require('path');
const bcrypt = require('bcryptjs');
const Database = require('better-sqlite3');
require('dotenv').config();

const dbPath = process.env.DB_PATH || (process.env.NODE_ENV === 'production' ? '/data/teamtracker.db' : path.join(process.cwd(), 'data', 'teamtracker.db'));
const dbDir = path.dirname(dbPath);

fs.mkdirSync(dbDir, { recursive: true });
const db = new Database(dbPath);

db.exec(`
  CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'pending' CHECK(role IN ('pending', 'viewer', 'editor', 'admin')),
    team_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
  );
`);

const count = db.prepare('SELECT COUNT(*) as c FROM users').get().c;
if (count > 0) {
  console.log(`Admin account already exists. Database: ${dbPath}`);
  process.exit(0);
}

const username = process.env.ADMIN_USERNAME || 'admin';
const email = process.env.ADMIN_EMAIL || 'admin@teamtracker.local';
const password = process.env.ADMIN_PASSWORD || 'admin123';
const hash = bcrypt.hashSync(password, 12);

db.prepare('INSERT INTO users (username, email, password_hash, role) VALUES (?, ?, ?, ?)').run(username, email, hash, 'admin');

console.log(`Created fresh admin user.`);
console.log(`Username: ${username}`);
console.log(`Email: ${email}`);
console.log(`Password: ${password}`);
console.log(`DB path: ${dbPath}`);
