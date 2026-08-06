// Content API: blog + help-center posts. Public listing (published, no full body) and
// single published post by slug (with body), plus admin CRUD (list all incl unpublished,
// create with slug derivation/uniqueness, patch, delete). Mounted at /api/content.
// No express.json() — JSON body parsing is done app-wide.
const express = require('express');
const { q, nowISO } = require('../lib/db');
const { requireAdmin } = require('../lib/auth');

const router = express.Router();

// slugify: lowercase, non-alnum -> '-', collapse + trim dashes.
function slugify(s) {
  return String(s)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

// GET /?kind=blog|help (public) — published posts of that kind (or all kinds), newest
// first, WITHOUT the full body.
router.get('/', (req, res) => {
  try {
    const kind = req.query.kind;
    let posts;
    if (kind === 'blog' || kind === 'help') {
      posts = q.all(
        `SELECT id, slug, kind, title, excerpt, created_at
           FROM posts WHERE published = 1 AND kind = ?
          ORDER BY created_at DESC, id DESC`,
        kind
      );
    } else {
      posts = q.all(
        `SELECT id, slug, kind, title, excerpt, created_at
           FROM posts WHERE published = 1
          ORDER BY created_at DESC, id DESC`
      );
    }
    res.json({ ok: true, posts });
  } catch (_e) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// GET /admin/all (requireAdmin) — every post incl unpublished, newest first.
// Declared before /:slug so the literal path wins.
router.get('/admin/all', requireAdmin, (_req, res) => {
  try {
    const posts = q.all('SELECT * FROM posts ORDER BY created_at DESC, id DESC');
    res.json({ ok: true, posts });
  } catch (_e) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// POST /admin (requireAdmin) — create a post. Requires title; derives/uniquifies slug.
router.post('/admin', requireAdmin, (req, res) => {
  try {
    const b = req.body || {};
    const title = typeof b.title === 'string' ? b.title.trim() : '';
    if (!title) return res.status(400).json({ ok: false, error: 'title_required' });

    const kind = b.kind === 'help' ? 'help' : 'blog';
    const lang = typeof b.lang === 'string' && b.lang ? b.lang : 'en';
    const published = b.published === undefined ? 1 : b.published ? 1 : 0;

    const explicit = typeof b.slug === 'string' && b.slug.trim();
    let slug = slugify(explicit ? b.slug : title) || 'post';

    if (explicit) {
      // An explicit slug that collides is a hard 409.
      if (q.get('SELECT 1 FROM posts WHERE slug = ?', slug)) {
        return res.status(409).json({ ok: false, error: 'code_taken' });
      }
    } else {
      // Derived slug: ensure uniqueness by appending -2, -3, …
      const base = slug;
      let n = 2;
      while (q.get('SELECT 1 FROM posts WHERE slug = ?', slug)) {
        slug = `${base}-${n}`;
        n += 1;
      }
    }

    const info = q.run(
      `INSERT INTO posts (slug, kind, title, excerpt, body, lang, published, created_at)
       VALUES (?,?,?,?,?,?,?,?)`,
      slug,
      kind,
      title,
      b.excerpt || null,
      b.body || null,
      lang,
      published,
      nowISO()
    );
    res.json({ ok: true, id: Number(info.lastInsertRowid), slug });
  } catch (_e) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// PATCH /admin/:id (requireAdmin) — update any of the provided fields.
router.patch('/admin/:id', requireAdmin, (req, res) => {
  try {
    const id = req.params.id;
    const existing = q.get('SELECT id FROM posts WHERE id = ?', id);
    if (!existing) return res.status(404).json({ ok: false, error: 'not_found' });

    const b = req.body || {};
    const sets = [];
    const vals = [];
    const setField = (col, val) => {
      sets.push(`${col} = ?`);
      vals.push(val);
    };

    if (b.title !== undefined) setField('title', b.title);
    if (b.excerpt !== undefined) setField('excerpt', b.excerpt);
    if (b.body !== undefined) setField('body', b.body);
    if (b.kind !== undefined) setField('kind', b.kind === 'help' ? 'help' : 'blog');
    if (b.lang !== undefined) setField('lang', b.lang);
    if (b.published !== undefined) setField('published', b.published ? 1 : 0);

    if (sets.length) {
      q.run(`UPDATE posts SET ${sets.join(', ')} WHERE id = ?`, ...vals, id);
    }
    res.json({ ok: true });
  } catch (_e) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// DELETE /admin/:id (requireAdmin) — delete a post.
router.delete('/admin/:id', requireAdmin, (req, res) => {
  try {
    q.run('DELETE FROM posts WHERE id = ?', req.params.id);
    res.json({ ok: true });
  } catch (_e) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// GET /:slug (public) — a single published post with its full body.
router.get('/:slug', (req, res) => {
  try {
    const post = q.get(
      'SELECT * FROM posts WHERE slug = ? AND published = 1',
      req.params.slug
    );
    if (!post) return res.status(404).json({ ok: false, error: 'not_found' });
    res.json({ ok: true, post });
  } catch (_e) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

module.exports = router;
