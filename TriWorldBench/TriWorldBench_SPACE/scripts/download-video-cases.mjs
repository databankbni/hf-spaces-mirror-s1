import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const manifest = JSON.parse(
  await fs.readFile(path.join(scriptDirectory, "video-cases-manifest.json"), "utf8")
);
const repository = (process.env.HF_VIDEO_DATASET_REPO || process.env.HF_DATASET_REPO || "").trim();
const revision = (process.env.HF_VIDEO_REVISION || process.env.HF_REVISION || "main").trim();
const prefix = (process.env.HF_VIDEO_DATASET_PREFIX || "video-cases").trim().replace(/^\/+|\/+$/g, "");
const token = process.env.HF_TOKEN;
const targetRoot = path.resolve(
  process.env.TRIWORLDBENCH_VIDEO_ROOT || path.join("/tmp", "triworldbench", "video-cases")
);

if (!repository || repository.split("/").length !== 2) {
  throw new Error("HF_VIDEO_DATASET_REPO or HF_DATASET_REPO must use owner/repository format.");
}
if (!token) {
  throw new Error("HF_TOKEN is required to download private Dataset videos.");
}
if (!prefix || prefix.split("/").some((part) => !part || part === "." || part === "..")) {
  throw new Error("HF_VIDEO_DATASET_PREFIX must be a safe relative Dataset path.");
}
if (!Array.isArray(manifest.files) || !manifest.files.length) {
  throw new Error("The video-cases manifest is empty or invalid.");
}

function validateRelativeVideo(value) {
  if (typeof value !== "string" || !/^(clean|random)\/[a-zA-Z0-9()[\]._ -]+\.mp4$/.test(value)) {
    throw new Error(`Unsafe video manifest entry: ${String(value)}`);
  }
  return value;
}

function encodedPath(value) {
  return value.split("/").map(encodeURIComponent).join("/");
}

function videoUrl(relativePath) {
  const repo = repository.split("/").map(encodeURIComponent).join("/");
  return `https://huggingface.co/datasets/${repo}/resolve/${encodeURIComponent(revision)}/${encodedPath(`${prefix}/${relativePath}`)}`;
}

function assertMp4(contents, relativePath) {
  if (contents.length < 12 || contents.subarray(4, 8).toString("ascii") !== "ftyp") {
    throw new Error(`Downloaded file is not a valid MP4 container: ${relativePath}`);
  }
}

async function download(relativePath) {
  const response = await fetch(videoUrl(relativePath), {
    headers: { Authorization: `Bearer ${token}` },
    redirect: "follow",
  });
  if (!response.ok) {
    throw new Error(`Video download failed for ${relativePath}: ${response.status} ${response.statusText}`);
  }
  const contents = Buffer.from(await response.arrayBuffer());
  assertMp4(contents, relativePath);

  const targetPath = path.resolve(targetRoot, relativePath);
  if (!targetPath.startsWith(targetRoot + path.sep)) {
    throw new Error(`Video target escaped the configured root: ${relativePath}`);
  }
  await fs.mkdir(path.dirname(targetPath), { recursive: true, mode: 0o700 });
  const temporaryPath = `${targetPath}.download-${process.pid}`;
  await fs.writeFile(temporaryPath, contents, { mode: 0o600 });
  await fs.rename(temporaryPath, targetPath);
}

const files = manifest.files.map(validateRelativeVideo);
const concurrency = Math.min(4, files.length);
let cursor = 0;
await Promise.all(Array.from({ length: concurrency }, async () => {
  while (cursor < files.length) {
    const index = cursor;
    cursor += 1;
    await download(files[index]);
  }
}));

console.log(`Downloaded ${files.length} private video cases to the runtime volume.`);
