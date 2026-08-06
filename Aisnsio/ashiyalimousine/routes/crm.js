// CRM notes & tags — staff attach VIP/Repeat/Corporate/Watch tags and free-text
// notes to a customer identity (cust_key = lowercased email or phone). Admin only.
const express = require('express');
const { q, nowISO } = require('../lib/db');
const { requireAdmin } = require('../lib/auth');

const router = express.Router();
router.use(requireAdmin);

// GET /?key=<cust_key> — all notes for one customer, newest first.
router.get('/', (req, res) => {
  try {
    const key = (req.query.key || '').trim();
    if (!key) return res.status(400).json({ ok: false, error: 'missing_key' });
    const notes = q.all('SELECT * FROM crm_notes WHERE cust_key = ? ORDER BY id DESC', key);
    res.json({ ok: true, notes });
  } catch (_) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// GET /tags — distinct non-empty tags per cust_key (for the customer directory).
router.get('/tags', (req, res) => {
  try {
    const rows = q.all("SELECT cust_key, tag FROM crm_notes WHERE tag IS NOT NULL AND tag != ''");
    const map = new Map();
    for (const r of rows) {
      if (!map.has(r.cust_key)) map.set(r.cust_key, new Set());
      map.get(r.cust_key).add(r.tag);
    }
    const tags = [...map].map(([cust_key, set]) => ({ cust_key, tags: [...set] }));
    res.json({ ok: true, tags });
  } catch (_) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// POST / — add a note/tag. Body: {cust_key, booking_ref, tag, note}.
router.post('/', (req, res) => {
  try {
    const b = req.body || {};
    const cust_key = (b.cust_key || '').trim();
    const tag = (b.tag || '').trim();
    const note = (b.note || '').trim();
    if (!cust_key || (!tag && !note)) {
      return res.status(400).json({ ok: false, error: 'missing_fields' });
    }
    const r = q.run(
      'INSERT INTO crm_notes (cust_key,booking_ref,tag,note,author,created_at) VALUES (?,?,?,?,?,?)',
      cust_key, b.booking_ref || null, tag || null, note || null, req.user.email, nowISO()
    );
    res.json({ ok: true, id: Number(r.lastInsertRowid) });
  } catch (_) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// DELETE /:id — remove a note.
router.delete('/:id', (req, res) => {
  try {
    q.run('DELETE FROM crm_notes WHERE id = ?', req.params.id);
    res.json({ ok: true });
  } catch (_) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

module.exports = router;
