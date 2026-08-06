'use strict';

/**
 * routes/newsletter.js — newsletter subscribe + admin broadcast for Ashiya Limousine.
 *
 * Mounted at /api/newsletter (Express Router, CommonJS).
 * Table: newsletter(id, email UNIQUE, lang, created_at).
 *
 * Endpoints:
 *   POST   /subscribe        (public)       {email, lang} -> {ok:true}   (idempotent)
 *   GET    /admin            (requireAdmin) -> {ok:true, subscribers:[...], count}
 *   POST   /admin/broadcast  (requireAdmin) {subject, message, lang} -> {ok:true, queued, providers}
 *   DELETE /admin/:id        (requireAdmin) -> {ok:true}
 *
 * No express.json() here — body parsing is done by the app. Only express + lib modules.
 */

const express = require('express');
const { q, nowISO } = require('../lib/db');
const { requireAdmin } = require('../lib/auth');
const notify = require('../lib/notify');

const router = express.Router();

// Reasonable email sanity check — not RFC-perfect, just "looks valid".
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// POST /subscribe (public) — dedupe by unique email, idempotent.
router.post('/subscribe', (req, res) => {
  try {
    const body = req.body || {};
    const email = String(body.email == null ? '' : body.email).trim().toLowerCase();
    if (!email || email.length > 254 || !EMAIL_RE.test(email)) {
      return res.status(400).json({ ok: false, error: 'bad_email' });
    }
    const lang = body.lang === 'ja' ? 'ja' : 'en';
    // INSERT OR IGNORE => already-subscribed emails are a no-op (unique index on email).
    q.run(
      'INSERT OR IGNORE INTO newsletter (email, lang, created_at) VALUES (?, ?, ?)',
      email, lang, nowISO()
    );
    return res.json({ ok: true });
  } catch (e) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// GET /admin (requireAdmin) — all subscribers newest first.
router.get('/admin', requireAdmin, (req, res) => {
  try {
    const subscribers = q.all(
      'SELECT id, email, lang, created_at FROM newsletter ORDER BY id DESC'
    );
    return res.json({ ok: true, subscribers, count: subscribers.length });
  } catch (e) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// POST /admin/broadcast (requireAdmin) — fire-and-forget email fan-out, return immediately.
router.post('/admin/broadcast', requireAdmin, (req, res) => {
  try {
    const body = req.body || {};
    const subject = String(body.subject == null ? '' : body.subject);
    const message = String(body.message == null ? '' : body.message);
    const lang = body.lang === 'ja' || body.lang === 'en' ? body.lang : null;

    const recipients = lang
      ? q.all('SELECT email FROM newsletter WHERE lang = ? ORDER BY id DESC', lang)
      : q.all('SELECT email FROM newsletter ORDER BY id DESC');

    const html =
      '<div style="font-family:sans-serif">' +
      escapeHtml(message).replace(/\n/g, '<br>') +
      '</div>';

    // Fire-and-forget: never block the response, never throw on a failed send.
    Promise.all(
      recipients.map((r) =>
        notify.sendEmail(r.email, subject, { text: message, html }).catch(() => null)
      )
    ).catch(() => {});

    return res.json({ ok: true, queued: recipients.length, providers: notify.enabled() });
  } catch (e) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// DELETE /admin/:id (requireAdmin) — remove a subscriber.
router.delete('/admin/:id', requireAdmin, (req, res) => {
  try {
    q.run('DELETE FROM newsletter WHERE id = ?', req.params.id);
    return res.json({ ok: true });
  } catch (e) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

module.exports = router;
