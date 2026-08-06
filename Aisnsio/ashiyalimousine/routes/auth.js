// routes/auth.js — customer register / login / logout / me.
// Mounted at /api/auth by server.js. Depends only on express + lib/* helpers.
const express = require('express');
const { q, nowISO } = require('../lib/db');
const { enc } = require('../lib/crypto');
const {
  hashPw,
  verifyPw,
  signToken,
  setAuthCookie,
  clearAuthCookie,
  optionalAuth,
} = require('../lib/auth');

const router = express.Router();

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// POST /register — create a customer account, set cookie, return user.
router.post('/register', (req, res) => {
  try {
    const b = req.body || {};
    const email = String(b.email || '').trim().toLowerCase();
    const password = String(b.password || '');
    const name = String(b.name || '').trim();
    const phone = b.phone == null ? '' : String(b.phone);

    if (!EMAIL_RE.test(email)) return res.status(400).json({ ok: false, error: 'invalid_email' });
    if (password.length < 8) return res.status(400).json({ ok: false, error: 'weak_password' });
    if (!name) return res.status(400).json({ ok: false, error: 'name_required' });

    const existing = q.get('SELECT id FROM users WHERE email = ?', email);
    if (existing) return res.status(409).json({ ok: false, error: 'email_taken' });

    const info = q.run(
      'INSERT INTO users (email,pass_hash,name,phone_enc,role,token_version,created_at) VALUES (?,?,?,?,?,?,?)',
      email, hashPw(password), name, enc(phone), 'customer', 0, nowISO()
    );
    const id = Number(info.lastInsertRowid);

    // Referral credit: if they registered via a referral link, credit the referrer.
    try {
      const ref = String(b.ref || '').trim().toUpperCase();
      if (ref) {
        const rr = q.get('SELECT user_id FROM referrals WHERE code = ?', ref);
        if (rr) {
          q.run('INSERT INTO referral_credits (code,referred_email,amount,created_at) VALUES (?,?,?,?)', ref, email, 3000, nowISO());
          q.run('UPDATE referrals SET uses = uses + 1 WHERE code = ?', ref);
          if (rr.user_id) q.run('UPDATE users SET points = points + 300 WHERE id = ?', rr.user_id);
        }
      }
    } catch (_) {}

    const token = signToken({ id, role: 'customer', token_version: 0 });
    setAuthCookie(res, token);
    return res.json({ ok: true, user: { id, email, name, role: 'customer' } });
  } catch (_) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// POST /login — verify credentials (any role), set cookie, return user.
router.post('/login', (req, res) => {
  try {
    const b = req.body || {};
    const email = String(b.email || '').trim().toLowerCase();
    const password = String(b.password || '');

    const u = q.get('SELECT id,email,pass_hash,name,role,token_version FROM users WHERE email = ?', email);
    if (!u || !verifyPw(password, u.pass_hash)) {
      return res.status(401).json({ ok: false, error: 'bad_credentials' });
    }

    const token = signToken({ id: u.id, role: u.role, token_version: u.token_version });
    setAuthCookie(res, token);
    return res.json({ ok: true, user: { id: u.id, email: u.email, name: u.name, role: u.role } });
  } catch (_) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// POST /logout — clear the auth cookie.
router.post('/logout', (req, res) => {
  try {
    clearAuthCookie(res);
    return res.json({ ok: true });
  } catch (_) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// GET /me — report current session (optionalAuth never blocks).
router.get('/me', optionalAuth, (req, res) => {
  try {
    if (req.user) return res.json({ ok: true, user: req.user });
    return res.json({ ok: false });
  } catch (_) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

module.exports = router;
