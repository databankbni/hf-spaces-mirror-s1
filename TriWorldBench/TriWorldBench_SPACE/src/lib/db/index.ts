import { DatabaseSync } from "node:sqlite";
import fs from "fs";
import path from "path";

function defaultDbPath(): string {
  const candidates = [
    path.resolve(process.cwd(), "..", "..", "database", "database.sqlite"),
    path.resolve(process.cwd(), "database", "database.sqlite"),
  ];
  return candidates.find((candidate) => fs.existsSync(candidate)) || candidates[0];
}

const DB_PATH = process.env.TRIWORLDBENCH_DB_PATH || defaultDbPath();
const READ_ONLY_DB = true;

let db: DatabaseSync | null = null;

export function getDb(): DatabaseSync {
  if (!db) {
    if (!fs.existsSync(DB_PATH)) {
      throw new Error("TriWorldBench database was not found at " + DB_PATH);
    }

    db = new DatabaseSync(DB_PATH, { readOnly: true });
    db.exec("PRAGMA busy_timeout = 5000");
    db.exec("PRAGMA foreign_keys = ON");
  }
  return db;
}

export function closeDb(): void {
  if (db) {
    db.close();
    db = null;
  }
}

export { DB_PATH, READ_ONLY_DB };
