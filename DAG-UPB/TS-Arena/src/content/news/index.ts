import fs from 'node:fs';
import path from 'node:path';

import matter from 'gray-matter';
import { marked } from 'marked';

import type { NewsPost } from './types';

/**
 * News posts are NOT checked into this repo. They live in a separate content
 * repository that is shallow-cloned into `content/news/` at image build time
 * (see `NEWS_CONTENT_REPO` in the Dockerfile and the README). That keeps
 * TS-Arena's own announcements out of the open-source framework — anyone
 * running their own instance points the build at their own content repo, or
 * at none at all.
 *
 * Consequence: the directory is legitimately absent (local dev) or empty
 * (fork with no content repo). Both are normal, not errors — the loader
 * returns `[]` and the `/news` route disappears from the navigation.
 *
 * Adding a post = add `<slug>.md` to the content repo, push, redeploy.
 */
const NEWS_DIR = path.join(process.cwd(), 'content', 'news');

/**
 * Files the content repo keeps at its root for its own sake, not as posts.
 * Without this they get parsed as candidate posts and warn on every build.
 */
const NOT_POSTS = new Set(['readme.md', 'claude.md', 'license.md', 'contributing.md']);

function readPosts(): NewsPost[] {
  let fileNames: string[];
  try {
    fileNames = fs.readdirSync(NEWS_DIR);
  } catch {
    // No content repo wired up — expected for forks and local dev.
    return [];
  }

  const posts: NewsPost[] = [];

  for (const fileName of fileNames) {
    if (!fileName.endsWith('.md') || fileName.startsWith('.')) continue;
    if (NOT_POSTS.has(fileName.toLowerCase())) continue;

    const slug = fileName.replace(/\.md$/, '');
    const raw = fs.readFileSync(path.join(NEWS_DIR, fileName), 'utf8');
    const { data, content } = matter(raw);

    const title = typeof data.title === 'string' ? data.title.trim() : '';
    // gray-matter parses an unquoted `date: 2026-07-23` into a Date, so
    // normalise both shapes back to a plain ISO day string.
    const date =
      data.date instanceof Date
        ? data.date.toISOString().slice(0, 10)
        : typeof data.date === 'string'
          ? data.date.trim()
          : '';

    if (!title || !date) {
      console.warn(
        `[news] skipping content/news/${fileName}: frontmatter needs both "title" and "date"`,
      );
      continue;
    }

    // Drafts stay in the content repo but never reach the site. Not rendered
    // and not routed, so there is no unlisted URL to stumble onto either.
    if (data.draft === true) {
      console.log(`[news] skipping draft content/news/${fileName}`);
      continue;
    }

    posts.push({
      slug,
      title,
      date,
      summary: typeof data.summary === 'string' ? data.summary.trim() : undefined,
      author: typeof data.author === 'string' ? data.author.trim() : undefined,
      // Content is authored by the operator of the instance in a repo they
      // control, so it is trusted the same way this repo's own JSX is.
      html: marked.parse(content, { async: false }),
    });
  }

  // Newest first; ties broken by slug so the order is stable across builds.
  return posts.sort((a, b) =>
    a.date === b.date ? a.slug.localeCompare(b.slug) : b.date.localeCompare(a.date),
  );
}

/**
 * Posts are read once per server process — the content directory is baked
 * into the image and cannot change while the container runs.
 */
let cached: NewsPost[] | null = null;

export function getAllPosts(): NewsPost[] {
  cached ??= readPosts();
  return cached;
}

export function findPost(slug: string): NewsPost | null {
  return getAllPosts().find((p) => p.slug === slug) ?? null;
}

/** Whether this instance has any news at all — drives the nav item. */
export function hasNews(): boolean {
  return getAllPosts().length > 0;
}

/** Formats an ISO day as e.g. "23 July 2026". */
export function formatPostDate(date: string): string {
  const parsed = new Date(`${date}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return date;
  return parsed.toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  });
}

export type { NewsPost, NewsPostMetadata } from './types';
