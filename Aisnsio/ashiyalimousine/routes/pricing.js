// Pricing API — live booking-form price preview + public rate rules & bundles.
// Mounted at /api/pricing. Server-authoritative: all money is computed here from
// lib/pricing (composePrice) and lib/catalog, never trusted from the client.
const express = require('express');
const { composePrice } = require('../lib/pricing');
const { PLANS, ADDONS, BUNDLES } = require('../lib/catalog');
const { q } = require('../lib/db');
const { optionalAuth } = require('../lib/auth');

const router = express.Router();

// Live price preview for the booking form.
router.post('/quote', optionalAuth, (req, res) => {
  try {
    const b = req.body || {};
    const quote = composePrice({
      plan: b.plan,
      addons: b.addons,
      pax: b.pax,
      date: b.date,
      time: b.time,
      couponCode: b.couponCode,
      giftCode: b.giftCode,
      tip: b.tip,
    });
    if (!quote || !quote.ok) {
      return res.status(400).json({ ok: false, error: (quote && quote.error) || 'invalid_quote' });
    }
    res.json({ ok: true, quote });
  } catch (e) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// Active dynamic rate rules (surcharges). Public.
router.get('/rules', (_req, res) => {
  try {
    const rows = q.all('SELECT * FROM rate_rules WHERE active = 1');
    const rules = rows.map((r) => {
      let config = {};
      try { config = JSON.parse(r.config || '{}'); } catch (_) { config = {}; }
      return { ...r, config };
    });
    res.json({ ok: true, rules });
  } catch (e) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// Tiered experience bundles with headline pricing. Public.
router.get('/bundles', (_req, res) => {
  try {
    const bundles = Object.keys(BUNDLES).map((key) => {
      const b = BUNDLES[key];
      const plan = PLANS[b.plan] || {};
      const addons = (b.addons || [])
        .filter((id) => ADDONS[id])
        .map((id) => ({ id, name_en: ADDONS[id].name_en, price: ADDONS[id].price }));
      // per:'pax' add-ons are headlined at pax=1.
      const addonsTotal = (b.addons || []).reduce((sum, id) => {
        const a = ADDONS[id];
        return a ? sum + a.price : sum; // pax=1 -> a.price whether flat or per-pax
      }, 0);
      const price = (plan.price || 0) + addonsTotal;
      return {
        key,
        name_en: b.name_en,
        badge: b.badge || '',
        plan: b.plan,
        plan_name_en: plan.name_en || '',
        addons,
        price,
      };
    });
    res.json({ ok: true, bundles });
  } catch (e) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

module.exports = router;
