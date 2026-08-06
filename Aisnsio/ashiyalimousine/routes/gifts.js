// Gift certificates — sellable online. Mounted at /api/gifts.
// Stripe is optional (gated on STRIPE_SECRET_KEY): when present we open a Checkout
// Session; otherwise we fall back to a manual "we'll send payment instructions" flow
// so the demo stays usable. Staff confirm bank-transfer purchases via /admin/:id/paid.
const express = require('express');
const { q, nowISO } = require('../lib/db');
const { requireAdmin, optionalAuth } = require('../lib/auth');

const router = express.Router();

const AMOUNTS = [10000, 20000, 30000, 50000, 100000];
const ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; // no ambiguous 0/O/1/I

function randSeg(n) {
  let s = '';
  for (let i = 0; i < n; i++) s += ALPHABET[Math.floor(Math.random() * ALPHABET.length)];
  return s;
}

function genCode() {
  for (let i = 0; i < 40; i++) {
    const code = `GIFT-${randSeg(4)}-${randSeg(4)}`;
    if (!q.get('SELECT 1 FROM gift_certificates WHERE code = ?', code)) return code;
  }
  return `GIFT-${randSeg(4)}-${Date.now().toString(36).toUpperCase().slice(-4)}`;
}

// POST /buy (optionalAuth) — issue a gift cert, optionally start Stripe checkout.
router.post('/buy', optionalAuth, (req, res) => {
  try {
    const { amount, purchaser_email, recipient_email, message } = req.body || {};
    const amt = Number(amount);
    if (!AMOUNTS.includes(amt)) return res.status(400).json({ ok: false, error: 'bad_amount' });

    const code = genCode();
    q.run(
      `INSERT INTO gift_certificates (code,initial,balance,currency,purchaser_email,recipient_email,message,status,pay_status,created_at)
       VALUES (?,?,?,?,?,?,?,?,?,?)`,
      code, amt, amt, 'jpy',
      purchaser_email || null, recipient_email || null, message || null,
      'active', 'unpaid', nowISO()
    );

    if (process.env.STRIPE_SECRET_KEY) {
      try {
        const stripe = require('stripe')(process.env.STRIPE_SECRET_KEY);
        const origin = req.headers.origin || ('https://' + req.headers.host);
        return stripe.checkout.sessions
          .create({
            mode: 'payment',
            line_items: [
              {
                quantity: 1,
                price_data: {
                  currency: 'jpy',
                  unit_amount: amt,
                  product_data: { name: `Ashiya Limousine Gift Certificate ${code}` },
                },
              },
            ],
            success_url: `${origin}/?gift_paid=${code}`,
            cancel_url: `${origin}/?gift=${code}`,
            metadata: { gift: code },
          })
          .then((session) => res.json({ ok: true, code, enabled: true, url: session.url }))
          .catch(() =>
            res.json({
              ok: true,
              code,
              enabled: false,
              manual: true,
              amount: amt,
              message: 'We will send payment instructions to complete your gift.',
            })
          );
      } catch (_) {
        return res.json({
          ok: true,
          code,
          enabled: false,
          manual: true,
          amount: amt,
          message: 'We will send payment instructions to complete your gift.',
        });
      }
    }

    return res.json({
      ok: true,
      code,
      enabled: false,
      manual: true,
      amount: amt,
      message: 'We will send payment instructions to complete your gift.',
    });
  } catch (_) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// GET /admin (requireAdmin) — all certs, newest first.
// Registered before /:code so the literal path is not swallowed by the param route.
router.get('/admin', requireAdmin, (_req, res) => {
  try {
    const gifts = q.all('SELECT * FROM gift_certificates ORDER BY id DESC');
    return res.json({ ok: true, gifts });
  } catch (_) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// GET /:code (public) — expose only balance + status for an active cert.
router.get('/:code', (req, res) => {
  try {
    const g = q.get(
      "SELECT code,balance,status FROM gift_certificates WHERE code = ? AND status = 'active'",
      req.params.code
    );
    if (!g) return res.status(404).json({ ok: false, error: 'not_found' });
    return res.json({ ok: true, code: g.code, balance: g.balance, status: g.status });
  } catch (_) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// POST /admin/:id/paid (requireAdmin) — confirm a bank-transfer purchase.
router.post('/admin/:id/paid', requireAdmin, (req, res) => {
  try {
    const row = q.get('SELECT id FROM gift_certificates WHERE id = ?', req.params.id);
    if (!row) return res.status(404).json({ ok: false, error: 'not_found' });
    q.run("UPDATE gift_certificates SET pay_status = 'paid' WHERE id = ?", row.id);
    return res.json({ ok: true });
  } catch (_) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

module.exports = router;
