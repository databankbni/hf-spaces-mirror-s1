// Consumables inventory (champagne, balloons, cakes, red carpet, …). Admin-only.
// Each row can link to a booking add-on via addon_id so stock can auto-decrement.
const express = require('express');
const { q, nowISO } = require('../lib/db');
const { requireAdmin } = require('../lib/auth');

const router = express.Router();

// Fields a client may set on create / patch.
const FIELDS = ['item', 'unit', 'stock', 'threshold', 'per_booking', 'addon_id'];

// GET /api/inventory — all items, each flagged `low` (stock <= threshold) + lowCount.
router.get('/', requireAdmin, (req, res) => {
  try {
    const rows = q.all('SELECT * FROM inventory ORDER BY id ASC');
    let lowCount = 0;
    const items = rows.map((r) => {
      const low = r.stock <= r.threshold;
      if (low) lowCount++;
      return { ...r, low };
    });
    res.json({ ok: true, items, lowCount });
  } catch (e) {
    console.error('[inventory] list failed:', e.message);
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// POST /api/inventory — create an item. `item` required.
router.post('/', requireAdmin, (req, res) => {
  try {
    const b = req.body || {};
    const item = (b.item || '').trim();
    if (!item) return res.status(400).json({ ok: false, error: 'missing_item' });
    const info = q.run(
      `INSERT INTO inventory (item, unit, stock, threshold, per_booking, addon_id, created_at)
       VALUES (?,?,?,?,?,?,?)`,
      item,
      b.unit || null,
      Number(b.stock) || 0,
      Number(b.threshold) || 0,
      Number(b.per_booking) || 0,
      b.addon_id || null,
      nowISO()
    );
    res.json({ ok: true, id: Number(info.lastInsertRowid) });
  } catch (e) {
    console.error('[inventory] create failed:', e.message);
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// PATCH /api/inventory/:id — update any provided fields.
router.patch('/:id', requireAdmin, (req, res) => {
  try {
    const row = q.get('SELECT id FROM inventory WHERE id = ?', req.params.id);
    if (!row) return res.status(404).json({ ok: false, error: 'not_found' });
    const b = req.body || {};
    const sets = [];
    const vals = [];
    for (const f of FIELDS) {
      if (b[f] === undefined) continue;
      let v = b[f];
      if (f === 'stock' || f === 'threshold' || f === 'per_booking') v = Number(v) || 0;
      sets.push(`${f} = ?`);
      vals.push(v);
    }
    if (sets.length) {
      q.run(`UPDATE inventory SET ${sets.join(', ')} WHERE id = ?`, ...vals, row.id);
    }
    res.json({ ok: true });
  } catch (e) {
    console.error('[inventory] update failed:', e.message);
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// POST /api/inventory/:id/adjust — bump stock by `delta` (may be negative), floor at 0.
router.post('/:id/adjust', requireAdmin, (req, res) => {
  try {
    const row = q.get('SELECT id, stock FROM inventory WHERE id = ?', req.params.id);
    if (!row) return res.status(404).json({ ok: false, error: 'not_found' });
    const delta = Number((req.body || {}).delta) || 0;
    const stock = Math.max(0, row.stock + delta);
    q.run('UPDATE inventory SET stock = ? WHERE id = ?', stock, row.id);
    res.json({ ok: true, stock });
  } catch (e) {
    console.error('[inventory] adjust failed:', e.message);
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// DELETE /api/inventory/:id — remove an item.
router.delete('/:id', requireAdmin, (req, res) => {
  try {
    q.run('DELETE FROM inventory WHERE id = ?', req.params.id);
    res.json({ ok: true });
  } catch (e) {
    console.error('[inventory] delete failed:', e.message);
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

module.exports = router;
