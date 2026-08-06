// Loyalty + referral API. Mounted at /api/referrals.
// Tables: referrals(id,user_id,code UNIQUE,uses,created_at),
//         referral_credits(id,code,referred_email,booking_ref,amount,created_at),
//         users(id,email,name,points).
const express = require('express');
const { q, nowISO } = require('../lib/db');
const { requireAuth, requireAdmin } = require('../lib/auth');

const router = express.Router();

const CODE_CHARS = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; // A-Z (minus I,O) + 2-9
function randCode() {
  let s = '';
  for (let i = 0; i < 6; i++) s += CODE_CHARS[Math.floor(Math.random() * CODE_CHARS.length)];
  return 'REF-' + s;
}

// find (or create) the caller's referral code
function ensureCode(uid) {
  const existing = q.get('SELECT code, uses FROM referrals WHERE user_id = ? ORDER BY id LIMIT 1', uid);
  if (existing) return existing;
  for (let i = 0; i < 40; i++) {
    const code = randCode();
    if (q.get('SELECT 1 FROM referrals WHERE code = ?', code)) continue;
    q.run('INSERT INTO referrals (user_id, code, uses, created_at) VALUES (?,?,0,?)', uid, code, nowISO());
    return { code, uses: 0 };
  }
  throw new Error('code_generation_failed');
}

const creditsFor = (code) =>
  q.get('SELECT COALESCE(SUM(amount),0) AS n FROM referral_credits WHERE code = ?', code).n;

// GET /mine — ensure the user has a code; return code, uses, credits, points, share_url.
router.get('/mine', requireAuth, (req, res) => {
  try {
    const uid = req.user.uid;
    const row = ensureCode(uid);
    const u = q.get('SELECT points FROM users WHERE id = ?', uid);
    res.json({
      ok: true,
      code: row.code,
      uses: row.uses,
      credits: creditsFor(row.code),
      points: (u && u.points) || 0,
      share_url: '/?ref=' + row.code,
    });
  } catch (e) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// GET /code/:code — public validity check.
router.get('/code/:code', (req, res) => {
  try {
    const code = String(req.params.code || '').toUpperCase();
    const hit = q.get('SELECT 1 FROM referrals WHERE code = ?', code);
    res.json({ ok: true, valid: !!hit });
  } catch (e) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// GET /admin — all referrals with credit totals.
router.get('/admin', requireAdmin, (req, res) => {
  try {
    const rows = q.all('SELECT code, user_id, uses FROM referrals ORDER BY id DESC');
    let total = 0;
    const referrals = rows.map((r) => {
      const credits = creditsFor(r.code);
      total += credits;
      return { code: r.code, user_id: r.user_id, uses: r.uses, credits };
    });
    res.json({ ok: true, referrals, total_credits: total });
  } catch (e) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// POST /admin/credit — record a referral credit + bump uses. Body: {code,amount,referred_email,booking_ref}
router.post('/admin/credit', requireAdmin, (req, res) => {
  try {
    const body = req.body || {};
    const code = String(body.code || '').toUpperCase();
    if (!code || !q.get('SELECT 1 FROM referrals WHERE code = ?', code)) {
      return res.status(404).json({ ok: false, error: 'code_unknown' });
    }
    const amount = parseInt(body.amount, 10) || 0;
    q.run(
      'INSERT INTO referral_credits (code, referred_email, booking_ref, amount, created_at) VALUES (?,?,?,?,?)',
      code, body.referred_email || null, body.booking_ref || null, amount, nowISO()
    );
    q.run('UPDATE referrals SET uses = uses + 1 WHERE code = ?', code);
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ ok: false, error: 'server_error' });
  }
});

module.exports = router;
