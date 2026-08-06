// routes/bookings.js — booking create (public/customer), list-own, get-one.
// Mounted at /api/bookings by server.js. Totals are ALWAYS computed server-side
// from lib/catalog.js — a client-sent total is never trusted.
const express = require('express');
const { PLANS, ADDONS, VALID_VEH } = require('../lib/catalog');
const { q, nowISO, genRef } = require('../lib/db');
const { enc, dec } = require('../lib/crypto');
const { optionalAuth, requireAuth } = require('../lib/auth');
const { composePrice } = require('../lib/pricing');
const notify = require('../lib/notify');

const router = express.Router();

// Fire booking notifications (email/SMS) + log them; never blocks or throws the request.
function fireNotify(kind, shaped, lang) {
  const fn = kind === 'confirmed' ? notify.notifyBookingConfirmed : notify.notifyBookingReceived;
  Promise.resolve()
    .then(() => fn(shaped, lang === 'ja' ? 'ja' : 'en'))
    .then((r) => {
      const log = (channel, to, subj, res) => {
        try {
          q.run(
            'INSERT INTO notifications (booking_ref,channel,to_addr,subject,body,status,provider,created_at) VALUES (?,?,?,?,?,?,?,?)',
            shaped.ref, channel, to || '', subj || kind, '', res && res.ok ? 'sent' : 'mocked', (res && res.channel) || channel, nowISO()
          );
        } catch (_) {}
      };
      if (r && r.email) log('email', shaped.mail, kind, r.email);
      if (r && r.sms) log('sms', shaped.phone, kind, r.sms);
    })
    .catch(() => {});
}

// Shape a DB row for API output: parse addons JSON + decrypt PII.
function shapeBooking(row) {
  let addons = [];
  try {
    addons = JSON.parse(row.addons || '[]');
    if (!Array.isArray(addons)) addons = [];
  } catch (_) {
    addons = [];
  }
  return {
    ref: row.ref,
    plan: row.plan,
    plan_name_en: (PLANS[row.plan] && PLANS[row.plan].name_en) || row.plan,
    veh: row.veh,
    date: row.date,
    time: row.time,
    pax: row.pax,
    addons,
    name: row.name,
    phone: dec(row.phone_enc),
    mail: dec(row.mail_enc),
    line_id: dec(row.line_enc),
    pickup: row.pickup,
    flight: row.flight,
    notes: row.notes,
    base: row.base,
    surcharge: row.surcharge,
    discount: row.discount,
    coupon: row.coupon,
    tip: row.tip,
    gift_applied: row.gift_applied,
    total: row.total,
    deposit: row.deposit,
    status: row.status,
    pay_status: row.pay_status,
    created_at: row.created_at,
  };
}

// POST / — create a booking. Guests allowed; logged-in customer is linked.
router.post('/', optionalAuth, (req, res) => {
  try {
    const b = req.body || {};
    const plan = PLANS[b.plan];

    // Plan must exist and be bookable.
    if (!plan || !plan.bookable) {
      return res.status(400).json({ ok: false, error: 'plan_not_bookable' });
    }

    // Required fields.
    if (!b.name || !b.phone || !b.date || !b.time) {
      return res.status(400).json({ ok: false, error: 'missing_fields' });
    }

    // Pax within 1..plan.max.
    const pax = parseInt(b.pax, 10);
    if (!Number.isInteger(pax) || pax < 1 || pax > plan.max) {
      return res.status(400).json({ ok: false, error: 'bad_pax' });
    }

    // Addons: keep only known ids (silently drop unknown).
    const rawAddons = Array.isArray(b.addons) ? b.addons : [];
    const addons = rawAddons.filter((id) => ADDONS[id]);

    // Coerce vehicle: twin plans forced to 'twin'; otherwise keep a valid veh or ''.
    let veh;
    if (plan.veh === 'twin') veh = 'twin';
    else veh = VALID_VEH.includes(b.veh) ? b.veh : '';

    // Availability lock: a specific car can't hold two pending/confirmed jobs at the
    // same date+time (twin convoy is exempt — it spans multiple cars).
    if (veh && veh !== 'twin') {
      const clash = q.get(
        "SELECT ref FROM bookings WHERE veh = ? AND date = ? AND time = ? AND status IN ('pending','confirmed')",
        veh, String(b.date), String(b.time)
      );
      if (clash) return res.status(409).json({ ok: false, error: 'slot_taken' });
    }

    // Server-authoritative pricing — surcharges, coupon, gift, gratuity all recomputed.
    const price = composePrice({
      plan: b.plan, addons, pax, date: b.date, time: b.time,
      couponCode: b.coupon, giftCode: b.gift_code, tip: b.tip,
    });
    if (!price.ok) return res.status(400).json({ ok: false, error: price.error });
    const total = price.total;
    const deposit = price.deposit;

    const ref = genRef(b.date);
    const ts = Date.now();
    const user_id = req.user ? req.user.uid : null;
    const created_at = nowISO();
    const notes = typeof b.notes === 'string' ? b.notes : '';

    const info = q.run(
      `INSERT INTO bookings
         (ref,user_id,name,phone_enc,mail_enc,line_enc,plan,veh,date,time,pax,addons,pickup,flight,notes,base,surcharge,discount,coupon,tip,gift_code,gift_applied,total,deposit,status,pay_status,created_at,ts)
       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`,
      ref, user_id, String(b.name), enc(b.phone), enc(b.mail), enc(b.line_id),
      b.plan, veh, String(b.date), String(b.time), pax, JSON.stringify(addons),
      b.pickup ? String(b.pickup) : '', b.flight ? String(b.flight) : '', notes,
      price.base, price.surcharge, price.discount, price.coupon, price.tip, price.giftCode, price.giftApplied,
      total, deposit, 'pending', 'unpaid', created_at, ts
    );

    // Redeem coupon + decrement gift balance + award loyalty points (best-effort).
    if (price.coupon && price.discount > 0) {
      try {
        q.run('UPDATE coupons SET used = used + 1 WHERE code = ?', price.coupon);
        q.run('INSERT INTO coupon_redemptions (code,booking_ref,user_id,amount,created_at) VALUES (?,?,?,?,?)', price.coupon, ref, user_id, price.discount, created_at);
      } catch (_) {}
    }
    if (price.giftCode && price.giftApplied > 0) {
      try {
        q.run("UPDATE gift_certificates SET balance = balance - ?, status = CASE WHEN balance - ? <= 0 THEN 'redeemed' ELSE status END WHERE code = ?", price.giftApplied, price.giftApplied, price.giftCode);
      } catch (_) {}
    }
    if (user_id) {
      try { q.run('UPDATE users SET points = points + ? WHERE id = ?', Math.floor(price.subtotal / 1000), user_id); } catch (_) {}
    }

    // If this customer has a saved LINE ID on their account, backfill it when missing.
    if (user_id && b.line_id) {
      try { q.run('UPDATE users SET line_enc = ? WHERE id = ? AND (line_enc IS NULL OR line_enc = "")', enc(b.line_id), user_id); } catch (_) {}
    }

    // Send "booking received" email/SMS with the service rules (provider-optional).
    fireNotify('received', {
      ref, name: String(b.name), mail: b.mail || '', phone: b.phone || '', line_id: b.line_id || '',
      plan: b.plan, plan_name_en: plan.name_en, veh, date: b.date, time: b.time, pax,
      total, deposit, pickup: b.pickup || '', flight: b.flight || '',
    }, b.lang);

    return res.json({
      ok: true,
      booking: {
        ref, total, deposit,
        base: price.base, surcharge: price.surcharge, discount: price.discount,
        coupon: price.coupon, tip: price.tip, gift_applied: price.giftApplied,
        breakdown: price.breakdown,
        plan: b.plan, veh, date: b.date, time: b.time, pax,
        status: 'pending', pay_status: 'unpaid',
      },
    });
  } catch (_) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// GET /mine — the caller's own bookings, newest first.
router.get('/mine', requireAuth, (req, res) => {
  try {
    const rows = q.all(
      'SELECT * FROM bookings WHERE user_id = ? ORDER BY ts DESC',
      req.user.uid
    );
    return res.json({ ok: true, bookings: rows.map(shapeBooking) });
  } catch (_) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// GET /:ref — one booking (owner or admin). Powers the payment page.
router.get('/:ref', requireAuth, (req, res) => {
  try {
    const row = q.get('SELECT * FROM bookings WHERE ref = ?', req.params.ref);
    if (!row) return res.status(404).json({ ok: false, error: 'not_found' });
    if (row.user_id !== req.user.uid && req.user.role !== 'admin') {
      return res.status(403).json({ ok: false, error: 'forbidden' });
    }
    return res.json({ ok: true, booking: shapeBooking(row) });
  } catch (_) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

module.exports = router;
