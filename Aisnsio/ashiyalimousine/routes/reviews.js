// Reviews API: public listing (approved, no booking_ref) + submission (moderation
// queue, approved=0), and admin moderation (list all, approve/unapprove, delete).
// Mounted at /api/reviews. No express.json() — JSON body parsing is done app-wide.
const express = require('express');
const { q, nowISO } = require('../lib/db');
const { requireAdmin, optionalAuth } = require('../lib/auth');

const router = express.Router();

// GET / (public) — approved reviews, newest first, without booking_ref, + count & average.
router.get('/', (_req, res) => {
  try {
    const reviews = q.all(
      `SELECT id, author_name, rating, title, body, occasion, approved, created_at
         FROM reviews WHERE approved = 1 ORDER BY created_at DESC, id DESC`
    );
    const count = reviews.length;
    const average = count
      ? Math.round((reviews.reduce((s, r) => s + r.rating, 0) / count) * 10) / 10
      : 0;
    res.json({ ok: true, reviews, count, average });
  } catch (_e) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// POST / (public, optionalAuth) — submit a review; enters moderation queue (approved=0).
router.post('/', optionalAuth, (req, res) => {
  try {
    const b = req.body || {};
    const author_name = typeof b.author_name === 'string' ? b.author_name.trim() : '';
    const rating = b.rating;
    if (!author_name || !Number.isInteger(rating) || rating < 1 || rating > 5) {
      return res.status(400).json({ ok: false, error: 'bad_review' });
    }
    q.run(
      `INSERT INTO reviews (booking_ref, author_name, rating, title, body, occasion, approved, created_at)
       VALUES (?,?,?,?,?,?,0,?)`,
      b.booking_ref || null,
      author_name,
      rating,
      b.title || null,
      b.body || null,
      b.occasion || null,
      nowISO()
    );
    res.json({ ok: true });
  } catch (_e) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// GET /admin (requireAdmin) — all reviews, newest first.
router.get('/admin', requireAdmin, (_req, res) => {
  try {
    const reviews = q.all('SELECT * FROM reviews ORDER BY created_at DESC, id DESC');
    res.json({ ok: true, reviews });
  } catch (_e) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// POST /admin/:id/approve (requireAdmin) — set approved 0/1 from body truthiness.
router.post('/admin/:id/approve', requireAdmin, (req, res) => {
  try {
    const row = q.get('SELECT id FROM reviews WHERE id = ?', req.params.id);
    if (!row) return res.status(404).json({ ok: false, error: 'not_found' });
    const approved = (req.body && req.body.approved) ? 1 : 0;
    q.run('UPDATE reviews SET approved = ? WHERE id = ?', approved, row.id);
    res.json({ ok: true });
  } catch (_e) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// DELETE /admin/:id (requireAdmin) — remove a review.
router.delete('/admin/:id', requireAdmin, (req, res) => {
  try {
    q.run('DELETE FROM reviews WHERE id = ?', req.params.id);
    res.json({ ok: true });
  } catch (_e) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

module.exports = router;
