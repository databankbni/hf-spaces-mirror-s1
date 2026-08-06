import fs from "node:fs/promises";
import path from "node:path";

const pointerPrefix = "version https://git-lfs.github.com/spec/v1";
const publicRoot = path.join(process.cwd(), "public");
const spaceRepo = process.env.TRIWORLDBENCH_SPACE_REPO?.trim();
const revision = process.env.HF_REVISION?.trim() || "main";
const assetExtensions = new Set([".gif", ".jpeg", ".jpg", ".mp4", ".pdf", ".png", ".svg", ".webp"]);

async function collectFiles(directory) {
  const entries = await fs.readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const entryPath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...await collectFiles(entryPath));
    } else if (entry.isFile() && assetExtensions.has(path.extname(entry.name).toLowerCase())) {
      files.push(entryPath);
    }
  }
  return files;
}

async function isLfsPointer(filePath) {
  const contents = await fs.readFile(filePath, "utf8").catch(() => "");
  return contents.startsWith(pointerPrefix);
}

function assetUrl(relativePath) {
  const encodedRepo = spaceRepo.split("/").map(encodeURIComponent).join("/");
  const encodedPath = relativePath.split("/").map(encodeURIComponent).join("/");
  return `https://huggingface.co/spaces/${encodedRepo}/resolve/${encodeURIComponent(revision)}/public/${encodedPath}`;
}

const files = await collectFiles(publicRoot);
const pointerFiles = [];
for (const filePath of files) {
  if (await isLfsPointer(filePath)) {
    pointerFiles.push(filePath);
  }
}

if (!pointerFiles.length) {
  console.log("No Git LFS public assets need restoration.");
  process.exit(0);
}

if (!spaceRepo || spaceRepo.split("/").length !== 2) {
  throw new Error("TRIWORLDBENCH_SPACE_REPO is required to restore Git LFS public assets.");
}

for (const filePath of pointerFiles) {
  const relativePath = path.relative(publicRoot, filePath).split(path.sep).join("/");
  const response = await fetch(assetUrl(relativePath));
  if (!response.ok) {
    throw new Error(`Could not restore ${relativePath}: ${response.status} ${response.statusText}`);
  }
  const contents = Buffer.from(await response.arrayBuffer());
  if (contents.subarray(0, pointerPrefix.length).toString("utf8") === pointerPrefix) {
    throw new Error(`Resolved asset is still a Git LFS pointer: ${relativePath}`);
  }
  const temporaryPath = `${filePath}.restore-${process.pid}`;
  await fs.writeFile(temporaryPath, contents);
  await fs.rename(temporaryPath, filePath);
  console.log(`Restored public asset: ${relativePath}`);
}
