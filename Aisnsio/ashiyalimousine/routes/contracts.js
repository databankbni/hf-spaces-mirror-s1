// Digital service agreement / e-signature. Admin generates a contract for a booking,
// the guest opens a public /?sign=<token> link, reviews the terms + confirmed booking
// details, and signs. Public endpoints never expose phone/email.
const express = require('express');
const crypto = require('crypto');
const { q, nowISO } = require('../lib/db');
const { requireAdmin } = require('../lib/auth');
const { PLANS } = require('../lib/catalog');

const router = express.Router();

// Service-agreement clauses (English). The front-end localizes the headings.
const TERMS = [
  'Once confirmed, cancellations on the day or the day before are charged 100% of the plan fee.',
  'A 30% deposit confirms the reservation; the balance is due by the day of service.',
  'Drinks, light food and champagne may be brought aboard; fast food is not permitted; broken glassware is charged at cost.',
  'The guest is responsible for damage to the vehicle beyond normal use; cleaning or repair costs may be charged.',
  'A dedicated chauffeur and private photo time are included; routes and timings are subject to traffic and safety.',
  'By signing, the guest agrees to these terms and the confirmed booking details above.',
];

// POST / (admin) — create or reuse a contract for a booking ref.
router.post('/', requireAdmin, (req, res) => {
  try {
    const ref = (req.body && req.body.ref) || '';
    const booking = q.get('SELECT ref FROM bookings WHERE ref = ?', ref);
    if (!booking) return res.status(404).json({ ok: false, error: 'not_found' });

    let c = q.get('SELECT token FROM contracts WHERE booking_ref = ? ORDER BY id DESC LIMIT 1', ref);
    if (!c) {
      const token = crypto.randomBytes(16).toString('hex');
      q.run(
        'INSERT INTO contracts (booking_ref,token,status,created_at) VALUES (?,?,?,?)',
        ref, token, 'sent', nowISO()
      );
      c = { token };
    }
    return res.json({ ok: true, token: c.token, url: '/?sign=' + c.token });
  } catch (e) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// GET / (admin) — list all contracts.
router.get('/', requireAdmin, (req, res) => {
  try {
    const contracts = q.all('SELECT * FROM contracts ORDER BY id DESC');
    return res.json({ ok: true, contracts });
  } catch (e) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// GET /:token (public) — the guest-facing contract + booking summary + terms.
router.get('/:token', (req, res) => {
  try {
    const c = q.get('SELECT * FROM contracts WHERE token = ?', req.params.token);
    if (!c) return res.status(404).json({ ok: false, error: 'not_found' });
    const b = q.get('SELECT * FROM bookings WHERE ref = ?', c.booking_ref) || {};
    return res.json({
      ok: true,
      contract: {
        token: c.token,
        status: c.status,
        signer_name: c.signer_name,
        signed_at: c.signed_at,
        ref: c.booking_ref,
        name: b.name,
        plan_name_en: (PLANS[b.plan] && PLANS[b.plan].name_en) || b.plan,
        veh: b.veh,
        date: b.date,
        time: b.time,
        pax: b.pax,
        total: b.total,
        deposit: b.deposit,
      },
      terms: TERMS,
    });
  } catch (e) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// POST /:token/sign (public) — the guest agrees + signs.
router.post('/:token/sign', (req, res) => {
  try {
    const body = req.body || {};
    const signer_name = (body.signer_name || '').trim();
    if (body.agreed !== true || !signer_name) {
      return res.status(400).json({ ok: false, error: 'must_agree' });
    }
    const c = q.get('SELECT * FROM contracts WHERE token = ?', req.params.token);
    if (!c) return res.status(404).json({ ok: false, error: 'not_found' });
    if (c.status === 'signed') return res.json({ ok: true, already: true });

    const ip = req.headers['x-forwarded-for'] || (req.socket && req.socket.remoteAddress) || '';
    q.run(
      'UPDATE contracts SET status = ?, signed_at = ?, signer_name = ?, agreed = 1, ip = ? WHERE token = ?',
      'signed', nowISO(), signer_name, ip, c.token
    );
    return res.json({ ok: true });
  } catch (e) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

module.exports = router;
