// Promotions / coupons API. Public validation for the booking flow + admin CRUD.
// Mounted at /api/promos. No express.json() here — the app wires body parsing upstream.
const express = require('express');
const { q, nowISO } = require('../lib/db');
const { checkCoupon } = require('../lib/pricing');
const { requireAdmin } = require('../lib/auth');

const router = express.Router();

// --- public: validate a coupon against a subtotal --------------------------
router.post('/validate', (req, res) => {
  try {
    const { code, subtotal } = req.body || {};
    const r = checkCoupon(code, Number(subtotal) || 0);
    return res.json(r);
  } catch (_) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// --- admin: list all coupons, newest first ---------------------------------
router.get('/admin', requireAdmin, (_req, res) => {
  try {
    const coupons = q.all('SELECT * FROM coupons ORDER BY id DESC');
    return res.json({ ok: true, coupons });
  } catch (_) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// --- admin: create a coupon ------------------------------------------------
router.post('/admin', requireAdmin, (req, res) => {
  try {
    const b = req.body || {};
    const code = String(b.code || '').trim().toUpperCase();
    const kind = String(b.kind || '');
    const amount = Number(b.amount);
    if (!code) return res.status(400).json({ ok: false, error: 'code_required' });
    if (kind !== 'pct' && kind !== 'fixed') return res.status(400).json({ ok: false, error: 'bad_kind' });
    if (!(amount > 0)) return res.status(400).json({ ok: false, error: 'bad_amount' });

    const minSpend = Math.max(0, Number(b.min_spend) || 0);
    const maxUses = Math.max(0, Number(b.max_uses) || 0);
    const expires = b.expires ? String(b.expires).trim() : null;

    if (q.get('SELECT 1 FROM coupons WHERE code = ?', code)) {
      return res.status(409).json({ ok: false, error: 'code_taken' });
    }

    const created_at = nowISO();
    const info = q.run(
      'INSERT INTO coupons (code,kind,amount,min_spend,max_uses,used,expires,active,created_at) VALUES (?,?,?,?,?,0,?,1,?)',
      code, kind, Math.round(amount), minSpend, maxUses, expires, created_at
    );

    const coupon = {
      id: Number(info.lastInsertRowid),
      code, kind, amount: Math.round(amount),
      min_spend: minSpend, max_uses: maxUses, used: 0,
      expires, active: 1, created_at,
    };
    return res.json({ ok: true, coupon });
  } catch (_) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// --- admin: toggle active --------------------------------------------------
router.patch('/admin/:id', requireAdmin, (req, res) => {
  try {
    const active = (req.body && req.body.active) ? 1 : 0;
    const info = q.run('UPDATE coupons SET active = ? WHERE id = ?', active, req.params.id);
    if (!info.changes) return res.status(404).json({ ok: false, error: 'not_found' });
    return res.json({ ok: true });
  } catch (_) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// --- admin: delete ---------------------------------------------------------
router.delete('/admin/:id', requireAdmin, (req, res) => {
  try {
    const info = q.run('DELETE FROM coupons WHERE id = ?', req.params.id);
    if (!info.changes) return res.status(404).json({ ok: false, error: 'not_found' });
    return res.json({ ok: true });
  } catch (_) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

module.exports = router;
