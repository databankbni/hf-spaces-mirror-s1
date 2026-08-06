// Leads: abandoned-booking / "email me this quote" capture for follow-up.
// Public quote capture + admin funnel. Email PII stored encrypted at rest via
// crypto.enc, decrypted on admin read. `selection` (chosen add-ons / config) is
// stored as JSON text and parsed back on admin read.
const express = require('express');
const { q, nowISO } = require('../lib/db');
const { enc, dec } = require('../lib/crypto');
const { requireAdmin } = require('../lib/auth');

const router = express.Router();

const STATUSES = ['new', 'contacted', 'converted', 'closed'];
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// POST /api/leads/quote  (public) — capture a quote lead for follow-up.
router.post('/quote', (req, res) => {
  try {
    const b = req.body || {};
    const email = (b.email || '').trim();
    if (!EMAIL_RE.test(email)) {
      return res.status(400).json({ ok: false, error: 'bad_email' });
    }
    // selection may arrive as an object (add-on map / config) — store as JSON text.
    let selection = b.selection;
    if (selection != null && typeof selection === 'object') {
      selection = JSON.stringify(selection);
    } else if (selection != null) {
      selection = String(selection);
    } else {
      selection = null;
    }
    if (selection != null && selection.length > 1000) {
      selection = selection.slice(0, 1000);
    }
    q.run(
      `INSERT INTO leads (email_enc, name, plan, date, time, pax, quote_total, selection, status, created_at)
       VALUES (?,?,?,?,?,?,?,?,?,?)`,
      enc(email),
      (b.name || '').trim() || null,
      b.plan || null,
      b.date || null,
      b.time || null,
      b.pax != null ? b.pax : null,
      parseInt(b.quote_total, 10) || 0,
      selection,
      'new',
      nowISO()
    );
    res.json({ ok: true });
  } catch (e) {
    console.error('[leads] quote capture failed:', e.message);
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// GET /api/leads/admin  (admin) — all leads, newest first, email decrypted,
// selection parsed back to its object form when it is valid JSON.
router.get('/admin', requireAdmin, (req, res) => {
  try {
    const rows = q.all('SELECT * FROM leads ORDER BY id DESC');
    const leads = rows.map((r) => {
      let selection = r.selection;
      if (selection) {
        try {
          selection = JSON.parse(selection);
        } catch (_) {
          /* leave as raw string */
        }
      }
      return {
        id: r.id,
        email: dec(r.email_enc),
        name: r.name,
        plan: r.plan,
        date: r.date,
        time: r.time,
        pax: r.pax,
        quote_total: r.quote_total,
        selection,
        status: r.status,
        created_at: r.created_at,
      };
    });
    res.json({ ok: true, leads });
  } catch (e) {
    console.error('[leads] admin list failed:', e.message);
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// POST /api/leads/admin/:id/status  (admin) — move a lead through the funnel.
router.post('/admin/:id/status', requireAdmin, (req, res) => {
  try {
    const status = ((req.body && req.body.status) || '').trim();
    if (!STATUSES.includes(status)) {
      return res.status(400).json({ ok: false, error: 'bad_status' });
    }
    const row = q.get('SELECT id FROM leads WHERE id = ?', req.params.id);
    if (!row) return res.status(404).json({ ok: false, error: 'not_found' });
    q.run('UPDATE leads SET status = ? WHERE id = ?', status, row.id);
    res.json({ ok: true });
  } catch (e) {
    console.error('[leads] status update failed:', e.message);
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// DELETE /api/leads/admin/:id  (admin) — remove a lead.
router.delete('/admin/:id', requireAdmin, (req, res) => {
  try {
    const row = q.get('SELECT id FROM leads WHERE id = ?', req.params.id);
    if (!row) return res.status(404).json({ ok: false, error: 'not_found' });
    q.run('DELETE FROM leads WHERE id = ?', row.id);
    res.json({ ok: true });
  } catch (e) {
    console.error('[leads] delete failed:', e.message);
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

module.exports = router;
