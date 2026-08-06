// B2B corporate account applications with monthly invoicing.
// Mounted at /api/corporate. Table: corporate(id, company, contact_name,
// email_enc, phone_enc, monthly_est, note, status('new'|'approved'|'declined'), created_at).
const express = require('express');
const { q, nowISO } = require('../lib/db');
const { enc, dec } = require('../lib/crypto');
const { requireAdmin } = require('../lib/auth');

const router = express.Router();

const STATUSES = ['new', 'approved', 'declined'];

// POST / (public) — submit a corporate account application.
router.post('/', (req, res) => {
  try {
    const b = req.body || {};
    const company = (b.company || '').trim();
    const contact_name = (b.contact_name || '').trim();
    const email = (b.email || '').trim();
    const phone = (b.phone || '').trim();
    const monthly_est = (b.monthly_est == null ? '' : String(b.monthly_est)).trim();
    const note = (b.note || '').trim();

    if (!company || (!email && !phone)) {
      return res.status(400).json({ ok: false, error: 'company and email or phone required' });
    }

    q.run(
      `INSERT INTO corporate (company, contact_name, email_enc, phone_enc, monthly_est, note, status, created_at)
       VALUES (?,?,?,?,?,?,?,?)`,
      company, contact_name, enc(email), enc(phone), monthly_est, note, 'new', nowISO()
    );
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// GET /admin (requireAdmin) — all applications, newest first, PII decrypted.
router.get('/admin', requireAdmin, (req, res) => {
  try {
    const rows = q.all('SELECT * FROM corporate ORDER BY id DESC');
    const accounts = rows.map((r) => ({
      id: r.id,
      company: r.company,
      contact_name: r.contact_name,
      email: dec(r.email_enc),
      phone: dec(r.phone_enc),
      monthly_est: r.monthly_est,
      note: r.note,
      status: r.status,
      created_at: r.created_at,
    }));
    res.json({ ok: true, accounts });
  } catch (e) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// POST /admin/:id/status (requireAdmin) — set status.
router.post('/admin/:id/status', requireAdmin, (req, res) => {
  try {
    const status = ((req.body && req.body.status) || '').trim();
    if (!STATUSES.includes(status)) {
      return res.status(400).json({ ok: false, error: 'bad_status' });
    }
    const row = q.get('SELECT id FROM corporate WHERE id = ?', req.params.id);
    if (!row) return res.status(404).json({ ok: false, error: 'not_found' });
    q.run('UPDATE corporate SET status = ? WHERE id = ?', status, row.id);
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// DELETE /admin/:id (requireAdmin) — delete an application.
router.delete('/admin/:id', requireAdmin, (req, res) => {
  try {
    const row = q.get('SELECT id FROM corporate WHERE id = ?', req.params.id);
    if (!row) return res.status(404).json({ ok: false, error: 'not_found' });
    q.run('DELETE FROM corporate WHERE id = ?', row.id);
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

module.exports = router;
