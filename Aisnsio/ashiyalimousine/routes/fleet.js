// Wave B fleet operations: chauffeur roster, vehicle maintenance, driver
// assignment + daily dispatch board. All routes are admin-only. Phone PII is
// stored encrypted (crypto.enc) and decrypted on read.
const express = require('express');
const router = express.Router();
const { q, nowISO } = require('../lib/db');
const { enc, dec } = require('../lib/crypto');
const { requireAdmin } = require('../lib/auth');
const { PLANS } = require('../lib/catalog');

const today = () => new Date().toISOString().slice(0, 10);

router.use(requireAdmin);

// ---- drivers --------------------------------------------------------------
router.get('/drivers', (req, res) => {
  try {
    const rows = q.all('SELECT id,name,phone_enc,license,status,notes FROM chauffeurs ORDER BY name ASC');
    const drivers = rows.map((r) => ({
      id: r.id,
      name: r.name,
      phone: dec(r.phone_enc),
      license: r.license,
      status: r.status,
      notes: r.notes,
    }));
    res.json({ ok: true, drivers });
  } catch (_) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

router.post('/drivers', (req, res) => {
  try {
    const { name, phone, license, status, notes } = req.body || {};
    if (!name) return res.status(400).json({ ok: false, error: 'name_required' });
    const info = q.run(
      'INSERT INTO chauffeurs (name,phone_enc,license,status,notes,created_at) VALUES (?,?,?,?,?,?)',
      name, enc(phone), license || null, status || 'active', notes || null, nowISO()
    );
    res.json({ ok: true, id: Number(info.lastInsertRowid) });
  } catch (_) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

router.patch('/drivers/:id', (req, res) => {
  try {
    const row = q.get('SELECT id FROM chauffeurs WHERE id = ?', req.params.id);
    if (!row) return res.status(404).json({ ok: false, error: 'not_found' });
    const b = req.body || {};
    const sets = [];
    const vals = [];
    if (b.name !== undefined) { sets.push('name = ?'); vals.push(b.name); }
    if (b.phone !== undefined) { sets.push('phone_enc = ?'); vals.push(enc(b.phone)); }
    if (b.license !== undefined) { sets.push('license = ?'); vals.push(b.license); }
    if (b.status !== undefined) { sets.push('status = ?'); vals.push(b.status); }
    if (b.notes !== undefined) { sets.push('notes = ?'); vals.push(b.notes); }
    if (sets.length) q.run(`UPDATE chauffeurs SET ${sets.join(', ')} WHERE id = ?`, ...vals, req.params.id);
    res.json({ ok: true });
  } catch (_) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

router.delete('/drivers/:id', (req, res) => {
  try {
    q.run('DELETE FROM chauffeurs WHERE id = ?', req.params.id);
    res.json({ ok: true });
  } catch (_) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// ---- maintenance ----------------------------------------------------------
router.get('/maintenance', (req, res) => {
  try {
    const t = today();
    const rows = q.all("SELECT * FROM maintenance ORDER BY COALESCE(due_date,'9999') ASC");
    const items = rows.map((r) => ({
      ...r,
      overdue: r.status !== 'done' && !!r.due_date && r.due_date < t,
    }));
    res.json({ ok: true, items });
  } catch (_) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

router.post('/maintenance', (req, res) => {
  try {
    const { veh, kind, due_date, notes, odo, cost } = req.body || {};
    if (!veh || !kind) return res.status(400).json({ ok: false, error: 'veh_kind_required' });
    const info = q.run(
      'INSERT INTO maintenance (veh,kind,due_date,odo,cost,status,notes,created_at) VALUES (?,?,?,?,?,?,?,?)',
      veh, kind, due_date || null,
      odo == null ? null : parseInt(odo, 10),
      cost == null ? null : parseInt(cost, 10),
      'scheduled', notes || null, nowISO()
    );
    res.json({ ok: true, id: Number(info.lastInsertRowid) });
  } catch (_) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

router.post('/maintenance/:id/done', (req, res) => {
  try {
    const row = q.get('SELECT id FROM maintenance WHERE id = ?', req.params.id);
    if (!row) return res.status(404).json({ ok: false, error: 'not_found' });
    const { done_date, odo, cost } = req.body || {};
    q.run(
      'UPDATE maintenance SET status = ?, done_date = ?, odo = ?, cost = ? WHERE id = ?',
      'done', done_date || today(),
      odo == null ? null : parseInt(odo, 10),
      cost == null ? null : parseInt(cost, 10),
      req.params.id
    );
    res.json({ ok: true });
  } catch (_) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

router.delete('/maintenance/:id', (req, res) => {
  try {
    q.run('DELETE FROM maintenance WHERE id = ?', req.params.id);
    res.json({ ok: true });
  } catch (_) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// ---- assignment + dispatch ------------------------------------------------
router.post('/assign', (req, res) => {
  try {
    const { ref, driver_id } = req.body || {};
    const row = q.get('SELECT id FROM bookings WHERE ref = ?', ref);
    if (!row) return res.status(404).json({ ok: false, error: 'not_found' });
    q.run('UPDATE bookings SET driver_id = ? WHERE ref = ?',
      driver_id == null ? null : driver_id, ref);
    res.json({ ok: true });
  } catch (_) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

router.get('/dispatch', (req, res) => {
  try {
    const date = req.query.date || today();
    const rows = q.all(
      `SELECT b.ref, b.time, b.veh, b.plan, b.pax, b.pickup, b.status, b.driver_id,
              c.name AS driver_name
         FROM bookings b
         LEFT JOIN chauffeurs c ON c.id = b.driver_id
        WHERE b.date = ? AND b.status IN ('pending','confirmed','completed')
        ORDER BY b.time ASC`,
      date
    );
    const jobs = rows.map((r) => ({
      ref: r.ref,
      time: r.time,
      veh: r.veh,
      plan_name_en: (PLANS[r.plan] && PLANS[r.plan].name_en) || r.plan,
      pax: r.pax,
      pickup: r.pickup,
      status: r.status,
      driver_id: r.driver_id,
      driver_name: r.driver_name || null,
      maps_url: r.pickup
        ? 'https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(r.pickup)
        : null,
    }));
    res.json({ ok: true, date, jobs });
  } catch (_) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

module.exports = router;
