#!/usr/bin/env node
/**
 * Populates `content/news/` before `next build` (wired up as the `prebuild`
 * npm script, so it runs on every build regardless of who invokes it).
 *
 * News posts are not committed to this repo — they come from a separate
 * content repository, so an instance run by someone else does not inherit
 * TS-Arena's announcements. Configure it with:
 *
 *   NEWS_CONTENT_REPO   clone URL of the content repo (unset = no news)
 *   NEWS_CONTENT_REF    branch or tag to clone (default: main)
 *
 * For a private repo, put the access token in the URL. TS-Arena's own deploys
 * are internal-only and anyone with Docker access on those hosts can read the
 * content repo anyway, so the token ending up in the image is acceptable there.
 *
 * Deliberately lives in npm-script land rather than in the Dockerfile: the
 * Coolify apps build with Nixpacks, which never reads the Dockerfile. Hooking
 * into `prebuild` is the one place both build paths go through.
 */
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const TARGET = path.join(process.cwd(), 'content', 'news');
const repo = process.env.NEWS_CONTENT_REPO?.trim();
const ref = process.env.NEWS_CONTENT_REF?.trim() || 'main';

if (!repo) {
  // No content repo configured: leave whatever is there (local drafts) and
  // make sure the directory exists so the loader has something to read.
  fs.mkdirSync(TARGET, { recursive: true });
  console.log('[news] NEWS_CONTENT_REPO not set — building without news posts');
  process.exit(0);
}

console.log(`[news] cloning news content (ref: ${ref})`);

// Clone into a staging directory and only swap it in once it succeeds, so a
// failed fetch leaves whatever was already there untouched (locally, that is
// somebody's unpushed drafts).
const staging = `${TARGET}.tmp`;
fs.rmSync(staging, { recursive: true, force: true });
fs.mkdirSync(path.dirname(TARGET), { recursive: true });

try {
  execFileSync('git', ['clone', '--depth', '1', '--branch', ref, repo, staging], {
    stdio: ['ignore', 'inherit', 'pipe'],
    // Bad credentials should fail the build, not hang it on a username prompt.
    env: { ...process.env, GIT_TERMINAL_PROMPT: '0' },
  });
} catch (err) {
  // Fail the build loudly. A silent fallback to "no news" would ship a site
  // that quietly lost its announcements.
  console.error(
    `[news] failed to clone the news content repo at ref "${ref}". ` +
      'Check NEWS_CONTENT_REPO / NEWS_CONTENT_REF and that git is available.',
  );
  console.error(err.stderr?.toString().trim() || err.message);
  fs.rmSync(staging, { recursive: true, force: true });
  process.exit(1);
}

fs.rmSync(path.join(staging, '.git'), { recursive: true, force: true });
fs.rmSync(TARGET, { recursive: true, force: true });
fs.renameSync(staging, TARGET);

const count = fs.readdirSync(TARGET).filter((f) => f.endsWith('.md')).length;
console.log(`[news] fetched ${count} post${count === 1 ? '' : 's'}`);
