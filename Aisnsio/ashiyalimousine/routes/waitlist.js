// Waitlist for fully-booked dates. Public sign-up + admin review/status.
// PII (phone, mail) stored encrypted at rest via crypto.enc / decrypted on admin read.
const express = require('express');
const { q, nowISO } = require('../lib/db');
const { enc, dec } = require('../lib/crypto');
const { requireAdmin } = require('../lib/auth');

const router = express.Router();

const STATUSES = ['waiting', 'offered', 'converted', 'closed'];

// POST /api/waitlist  (public) — join the waitlist for a full date.
router.post('/', (req, res) => {
  try {
    const b = req.body || {};
    const name = (b.name || '').trim();
    const phone = (b.phone || '').trim();
    const date = (b.date || '').trim();
    if (!name || !phone || !date) {
      return res.status(400).json({ ok: false, error: 'missing_fields' });
    }
    q.run(
      `INSERT INTO waitlist (name, phone_enc, mail_enc, plan, date, time, pax, notes, status, created_at)
       VALUES (?,?,?,?,?,?,?,?,?,?)`,
      name,
      enc(phone),
      enc(b.mail),
      b.plan || null,
      date,
      b.time || null,
      b.pax != null ? b.pax : null,
      b.notes || null,
      'waiting',
      nowISO()
    );
    res.json({ ok: true });
  } catch (e) {
    console.error('[waitlist] create failed:', e.message);
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// GET /api/waitlist/admin  (admin) — all entries, newest first, PII decrypted.
router.get('/admin', requireAdmin, (req, res) => {
  try {
    const rows = q.all('SELECT * FROM waitlist ORDER BY id DESC');
    const entries = rows.map((r) => ({
      id: r.id,
      name: r.name,
      phone: dec(r.phone_enc),
      mail: dec(r.mail_enc),
      plan: r.plan,
      date: r.date,
      time: r.time,
      pax: r.pax,
      notes: r.notes,
      status: r.status,
      created_at: r.created_at,
    }));
    res.json({ ok: true, entries });
  } catch (e) {
    console.error('[waitlist] admin list failed:', e.message);
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// POST /api/waitlist/admin/:id/status  (admin) — move an entry through the funnel.
router.post('/admin/:id/status', requireAdmin, (req, res) => {
  try {
    const status = (req.body && req.body.status || '').trim();
    if (!STATUSES.includes(status)) {
      return res.status(400).json({ ok: false, error: 'bad_status' });
    }
    const row = q.get('SELECT id FROM waitlist WHERE id = ?', req.params.id);
    if (!row) return res.status(404).json({ ok: false, error: 'not_found' });
    q.run('UPDATE waitlist SET status = ? WHERE id = ?', status, row.id);
    res.json({ ok: true });
  } catch (e) {
    console.error('[waitlist] status update failed:', e.message);
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

module.exports = router;
