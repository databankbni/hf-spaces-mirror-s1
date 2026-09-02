import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";

const targetPath = path.resolve(
  process.env.TRIWORLDBENCH_DB_PATH || path.join(os.tmpdir(), "triworldbench", "database.sqlite")
);
const temporaryRoot = path.resolve(os.tmpdir());

if (process.env.TRIWORLDBENCH_PUBLIC_READONLY !== "1") {
  throw new Error("Refusing to sanitize a database outside public read-only mode.");
}
if (targetPath !== temporaryRoot && !targetPath.startsWith(`${temporaryRoot}${path.sep}`)) {
  throw new Error(`Refusing to sanitize a database outside the temporary directory: ${targetPath}`);
}
if (!fs.existsSync(targetPath)) {
  throw new Error(`Downloaded public database was not found: ${targetPath}`);
}

const database = new DatabaseSync(targetPath);
try {
  database.exec(`
    BEGIN IMMEDIATE;
    UPDATE teams
       SET slug = 'public-team-' || id,
           name = 'Private participant',
           participant_email = 'private-' || id || '@invalid.local',
           affiliation = NULL,
           country_region = NULL,
           strengths = NULL,
           updated_at = CURRENT_TIMESTAMP;
    UPDATE models
       SET model_card_url = NULL,
           brief_introduction = NULL;
    UPDATE submissions
       SET artifact_uri = NULL,
           notes = NULL;
    COMMIT;
    PRAGMA wal_checkpoint(TRUNCATE);
  `);
  const integrity = database.prepare("PRAGMA integrity_check").get();
  if (integrity.integrity_check !== "ok") {
    throw new Error(`Public database integrity check failed: ${integrity.integrity_check}`);
  }
} catch (error) {
  try {
    database.exec("ROLLBACK");
  } catch {
    // No active transaction remains after a successful commit.
  }
  throw error;
} finally {
  database.close();
}

console.log("Public runtime database identity fields sanitized.");
