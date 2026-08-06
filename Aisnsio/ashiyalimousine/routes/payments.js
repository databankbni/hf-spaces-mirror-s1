// routes/payments.js — Stripe-OPTIONAL payments, mounted at /api/payments.
// Payments activate ONLY when STRIPE_SECRET_KEY is set; otherwise the API returns a
// graceful "manual/invoice" response and never crashes. Stripe is loaded lazily so a
// missing dependency or key can't break boot. Currency is JPY (zero-decimal — amounts are
// whole yen, never multiplied by 100).
const express = require('express');
const { q, nowISO } = require('../lib/db');
const { requireAuth } = require('../lib/auth');

const router = express.Router();

let stripe = null;
function getStripe() {
  if (stripe) return stripe;
  const k = process.env.STRIPE_SECRET_KEY;
  if (!k) return null;
  try {
    stripe = require('stripe')(k);
  } catch (_) {
    stripe = null;
  }
  return stripe;
}

// Owner-or-admin authorization against a booking.
function canAccess(req, booking) {
  return booking.user_id === req.user.uid || req.user.role === 'admin';
}

// GET /config — front-end asks whether card payments are live.
router.get('/config', (req, res) => {
  try {
    res.json({ ok: true, enabled: !!process.env.STRIPE_SECRET_KEY, currency: 'jpy' });
  } catch (e) {
    res.status(500).json({ ok: false, error: 'config_failed' });
  }
});

// POST /checkout — create a Stripe Checkout Session (or a manual/invoice fallback).
router.post('/checkout', requireAuth, (req, res) => {
  try {
    const ref = req.body && req.body.ref;
    let kind = (req.body && req.body.kind) || 'deposit';
    if (kind !== 'full') kind = 'deposit';
    if (!ref) return res.status(400).json({ ok: false, error: 'ref_required' });

    const booking = q.get('SELECT * FROM bookings WHERE ref = ?', ref);
    if (!booking) return res.status(404).json({ ok: false, error: 'booking_not_found' });
    if (!canAccess(req, booking)) return res.status(403).json({ ok: false, error: 'forbidden' });

    const amount = kind === 'full' ? booking.total : booking.deposit;
    const origin = req.headers.origin || ('https://' + req.headers.host);
    const s = getStripe();

    if (s) {
      return s.checkout.sessions
        .create({
          mode: 'payment',
          line_items: [
            {
              quantity: 1,
              price_data: {
                currency: 'jpy',
                unit_amount: amount,
                product_data: {
                  name: `Ashiya Limousine ${kind === 'full' ? 'Full payment' : 'Deposit'} — ${ref}`,
                },
              },
            },
          ],
          success_url: `${origin}/?paid=${ref}`,
          cancel_url: `${origin}/?pay=${ref}`,
          client_reference_id: ref,
          metadata: { ref, kind },
        })
        .then((session) => {
          q.run(
            `INSERT INTO payments (booking_ref,amount,currency,provider,kind,stripe_session,status,created_at)
             VALUES (?,?,?,?,?,?,?,?)`,
            ref, amount, 'jpy', 'stripe', kind, session.id, 'pending', nowISO()
          );
          res.json({ ok: true, enabled: true, url: session.url });
        })
        .catch((e) => {
          console.warn('[payments] stripe checkout failed:', e && e.message);
          res.status(502).json({ ok: false, error: 'stripe_checkout_failed' });
        });
    }

    // Stripe not enabled → manual / invoice mode.
    q.run(
      `INSERT INTO payments (booking_ref,amount,currency,provider,kind,status,created_at)
       VALUES (?,?,?,?,?,?,?)`,
      ref, amount, 'jpy', 'manual', kind, 'pending', nowISO()
    );
    return res.json({
      ok: true,
      enabled: false,
      manual: true,
      amount,
      message:
        'Card payments are not enabled yet — our team will send an invoice / bank-transfer details.',
    });
  } catch (e) {
    console.warn('[payments] checkout error:', e && e.message);
    res.status(500).json({ ok: false, error: 'checkout_failed' });
  }
});

// POST /webhook — Stripe server-to-server callback. server.js mounts express.raw for this
// path, so req.body is a Buffer. Always respond 200 quickly; never 500 the process.
router.post('/webhook', (req, res) => {
  try {
    const secret = process.env.STRIPE_WEBHOOK_SECRET;
    const s = getStripe();
    let event = null;

    if (secret && s) {
      try {
        event = s.webhooks.constructEvent(req.body, req.headers['stripe-signature'], secret);
      } catch (err) {
        console.warn('[payments] webhook signature verify failed:', err && err.message);
        return res.status(400).json({ received: false, error: 'invalid_signature' });
      }
    } else {
      // Best-effort parse when no signing secret is configured.
      try {
        const raw = Buffer.isBuffer(req.body) ? req.body.toString() : String(req.body || '');
        event = JSON.parse(raw);
      } catch (_) {
        event = null;
      }
    }

    if (event && event.type === 'checkout.session.completed') {
      try {
        const session = (event.data && event.data.object) || {};
        const meta = session.metadata || {};
        const ref = meta.ref || session.client_reference_id;
        const kind = meta.kind === 'full' ? 'full' : 'deposit';

        if (session.id) {
          if (session.payment_intent) {
            q.run(
              `UPDATE payments SET status = 'paid', stripe_intent = ? WHERE stripe_session = ?`,
              session.payment_intent, session.id
            );
          } else {
            q.run(`UPDATE payments SET status = 'paid' WHERE stripe_session = ?`, session.id);
          }
        }
        if (ref) {
          const pay_status = kind === 'full' ? 'paid' : 'deposit_paid';
          q.run('UPDATE bookings SET pay_status = ? WHERE ref = ?', pay_status, ref);
        }
      } catch (e) {
        console.warn('[payments] webhook handling error:', e && e.message);
      }
    }

    return res.status(200).json({ received: true });
  } catch (e) {
    // Never let a bad webhook 500 the process.
    console.warn('[payments] webhook fatal (swallowed):', e && e.message);
    return res.status(200).json({ received: true });
  }
});

// GET /status/:ref — owner or admin: pay status + payment rows for this booking.
router.get('/status/:ref', requireAuth, (req, res) => {
  try {
    const ref = req.params.ref;
    const booking = q.get('SELECT * FROM bookings WHERE ref = ?', ref);
    if (!booking) return res.status(404).json({ ok: false, error: 'booking_not_found' });
    if (!canAccess(req, booking)) return res.status(403).json({ ok: false, error: 'forbidden' });

    const payments = q.all(
      `SELECT amount,kind,provider,status,created_at FROM payments
       WHERE booking_ref = ? ORDER BY id DESC`,
      ref
    );
    res.json({ ok: true, pay_status: booking.pay_status, payments });
  } catch (e) {
    console.warn('[payments] status error:', e && e.message);
    res.status(500).json({ ok: false, error: 'status_failed' });
  }
});

module.exports = router;
