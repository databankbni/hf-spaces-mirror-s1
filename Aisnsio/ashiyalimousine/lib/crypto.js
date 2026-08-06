// AES-256-GCM field encryption for PII at rest (phone, email).
// Key derived from SECRET_KEY, falling back to JWT_SECRET (fleet pattern).
const crypto = require('crypto');

const KEY = crypto
  .createHash('sha256')
  .update(process.env.SECRET_KEY || process.env.JWT_SECRET || 'als-dev-key-change-me')
  .digest(); // 32 bytes

function enc(txt) {
  if (txt == null || txt === '') return '';
  const iv = crypto.randomBytes(12);
  const c = crypto.createCipheriv('aes-256-gcm', KEY, iv);
  const e = Buffer.concat([c.update(String(txt), 'utf8'), c.final()]);
  const tag = c.getAuthTag();
  return Buffer.concat([iv, tag, e]).toString('base64');
}

function dec(b64) {
  if (!b64) return '';
  try {
    const raw = Buffer.from(b64, 'base64');
    const iv = raw.subarray(0, 12);
    const tag = raw.subarray(12, 28);
    const e = raw.subarray(28);
    const d = crypto.createDecipheriv('aes-256-gcm', KEY, iv);
    d.setAuthTag(tag);
    return Buffer.concat([d.update(e), d.final()]).toString('utf8');
  } catch (_) {
    return '';
  }
}

module.exports = { enc, dec };
