// Incidents: post-ride damage / cleaning / delay / complaint reports with an
// optional deposit action. All endpoints are admin-only. Mounted at /api/incidents.
const express = require('express');
const { q, nowISO } = require('../lib/db');
const { requireAdmin } = require('../lib/auth');

const router = express.Router();
router.use(requireAdmin);

// GET / — list all incidents, newest first.
router.get('/', (_req, res) => {
  try {
    const incidents = q.all('SELECT * FROM incidents ORDER BY id DESC');
    res.json({ ok: true, incidents });
  } catch (_e) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// POST / — create an incident.
router.post('/', (req, res) => {
  try {
    const { booking_ref, veh, kind, description, cost, deposit_action } = req.body || {};
    if (!kind || !description) {
      return res.status(400).json({ ok: false, error: 'kind and description required' });
    }
    const r = q.run(
      `INSERT INTO incidents (booking_ref, veh, kind, description, cost, deposit_action, status, created_at)
       VALUES (?,?,?,?,?,?,?,?)`,
      booking_ref || null, veh || null, kind, description,
      parseInt(cost, 10) || 0, deposit_action || null, 'open', nowISO()
    );
    res.json({ ok: true, id: Number(r.lastInsertRowid) });
  } catch (_e) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// POST /:id/resolve — mark resolved.
router.post('/:id/resolve', (req, res) => {
  try {
    const row = q.get('SELECT id FROM incidents WHERE id = ?', req.params.id);
    if (!row) return res.status(404).json({ ok: false, error: 'not_found' });
    q.run('UPDATE incidents SET status = ? WHERE id = ?', 'resolved', req.params.id);
    res.json({ ok: true });
  } catch (_e) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// PATCH /:id — update any provided fields.
router.patch('/:id', (req, res) => {
  try {
    const row = q.get('SELECT id FROM incidents WHERE id = ?', req.params.id);
    if (!row) return res.status(404).json({ ok: false, error: 'not_found' });
    const body = req.body || {};
    const fields = [];
    const vals = [];
    for (const col of ['kind', 'description', 'cost', 'deposit_action', 'veh', 'booking_ref']) {
      if (body[col] !== undefined) {
        fields.push(`${col} = ?`);
        vals.push(col === 'cost' ? (parseInt(body[col], 10) || 0) : body[col]);
      }
    }
    if (fields.length) {
      vals.push(req.params.id);
      q.run(`UPDATE incidents SET ${fields.join(', ')} WHERE id = ?`, ...vals);
    }
    res.json({ ok: true });
  } catch (_e) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// DELETE /:id — remove an incident.
router.delete('/:id', (req, res) => {
  try {
    q.run('DELETE FROM incidents WHERE id = ?', req.params.id);
    res.json({ ok: true });
  } catch (_e) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

module.exports = router;
