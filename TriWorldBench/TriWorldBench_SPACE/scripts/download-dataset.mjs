import fs from "node:fs";
import path from "node:path";

const repository = process.env.HF_DATASET_REPO;
const fileName = process.env.HF_DATASET_FILE || "database.sqlite";
const revision = process.env.HF_REVISION || "main";
const token = process.env.HF_TOKEN;
const targetPath =
  process.env.TRIWORLDBENCH_DB_PATH ||
  path.join("/tmp", "triworldbench", fileName);

if (!repository) {
  console.error("A Hugging Face Dataset repository must be configured before startup.");
  process.exit(1);
}

const url = `https://huggingface.co/datasets/${repository}/resolve/${revision}/${fileName}`;
const headers = token ? { Authorization: `Bearer ${token}` } : {};
const response = await fetch(url, { headers });

if (!response.ok) {
  console.error(`Database download failed: ${response.status} ${response.statusText}`);
  process.exit(1);
}

const database = Buffer.from(await response.arrayBuffer());
if (database.length < 100 || database.subarray(0, 16).toString("binary") !== "SQLite format 3\u0000") {
  console.error("Database download returned a file that is not a valid SQLite database.");
  process.exit(1);
}
fs.mkdirSync(path.dirname(targetPath), { recursive: true });
const temporaryPath = `${targetPath}.download-${process.pid}`;
fs.writeFileSync(temporaryPath, database, { mode: 0o600 });
fs.renameSync(temporaryPath, targetPath);
console.log(`Downloaded the configured database revision ${revision}.`);
