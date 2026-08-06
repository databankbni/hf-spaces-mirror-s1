// Auth: bcrypt + JWT, dual cookie ("als_token") + Authorization: Bearer (Bearer wins),
// token_version invalidation. Cookie is SameSite=None; Secure so login works inside HF's
// cross-site iframe.
const jwt = require('jsonwebtoken');
const bcrypt = require('bcryptjs');
const { q } = require('./db');

let SECRET = process.env.JWT_SECRET;
if (!SECRET) {
  // Keep the site up for an immediate go-live demo, but warn loudly: tokens become
  // ephemeral (everyone is logged out on each rebuild). Set JWT_SECRET for durability.
  SECRET = require('crypto').randomBytes(32).toString('hex');
  console.warn('[auth] JWT_SECRET unset — using an EPHEMERAL secret. Sessions reset on rebuild. Set JWT_SECRET.');
}

const COOKIE = 'als_token';
const COOKIE_OPTS = {
  httpOnly: true,
  secure: true,
  sameSite: 'none',
  path: '/',
  maxAge: 30 * 24 * 60 * 60 * 1000,
};

const hashPw = (pw) => bcrypt.hashSync(String(pw), 10);
const verifyPw = (pw, hash) => bcrypt.compareSync(String(pw), hash || '');

function signToken(user) {
  return jwt.sign({ uid: user.id, role: user.role, tv: user.token_version || 0 }, SECRET, {
    expiresIn: '30d',
  });
}

const setAuthCookie = (res, token) => res.cookie(COOKIE, token, COOKIE_OPTS);
const clearAuthCookie = (res) => res.clearCookie(COOKIE, { ...COOKIE_OPTS, maxAge: 0 });

function readToken(req) {
  const h = req.headers.authorization;
  if (h && h.startsWith('Bearer ')) return h.slice(7).trim();
  if (req.cookies && req.cookies[COOKIE]) return req.cookies[COOKIE];
  return null;
}

// Returns {uid,role,email,name} for a valid token, else null. Verifies token_version.
function authUser(req) {
  const t = readToken(req);
  if (!t) return null;
  let p;
  try {
    p = jwt.verify(t, SECRET);
  } catch (_) {
    return null;
  }
  const u = q.get('SELECT id,email,name,role,token_version FROM users WHERE id = ?', p.uid);
  if (!u || u.token_version !== p.tv) return null;
  return { uid: u.id, role: u.role, email: u.email, name: u.name };
}

function optionalAuth(req, _res, next) {
  req.user = authUser(req);
  next();
}
function requireAuth(req, res, next) {
  const u = authUser(req);
  if (!u) return res.status(401).json({ ok: false, error: 'auth_required' });
  req.user = u;
  next();
}
function requireAdmin(req, res, next) {
  const u = authUser(req);
  if (!u || u.role !== 'admin') return res.status(403).json({ ok: false, error: 'admin_only' });
  req.user = u;
  next();
}

module.exports = {
  hashPw,
  verifyPw,
  signToken,
  setAuthCookie,
  clearAuthCookie,
  optionalAuth,
  requireAuth,
  requireAdmin,
};
