// Server-authoritative pricing engine. Composes: base plan + add-ons + dynamic
// surcharges (rate_rules) − coupon − gift certificate + gratuity. Pure calc (no DB
// mutation); the booking route redeems the coupon / decrements the gift on commit.
const { q } = require('./db');
const { PLANS, ADDONS } = require('./catalog');

const todayStr = () => new Date().toISOString().slice(0, 10);

// Dynamic surcharge for a date/time from active rate_rules.
function surchargeFor(date, time) {
  let pct = 0, fixed = 0;
  const labels = [];
  let rules = [];
  try { rules = q.all('SELECT * FROM rate_rules WHERE active = 1'); } catch (_) { rules = []; }
  const dow = date ? new Date(date + 'T00:00:00Z').getUTCDay() : null; // 0 Sun .. 6 Sat
  for (const r of rules) {
    let cfg = {};
    try { cfg = JSON.parse(r.config || '{}'); } catch (_) {}
    let hit = false;
    if (Array.isArray(cfg.dows) && dow != null && cfg.dows.includes(dow)) hit = true;
    if (cfg.from && time && String(time) >= String(cfg.from)) hit = true;
    if (Array.isArray(cfg.dates) && date && cfg.dates.includes(date)) hit = true;
    if (hit) {
      if (r.kind === 'pct') pct += r.amount;
      else fixed += r.amount;
      labels.push(r.label);
    }
  }
  return { pct, fixed, labels };
}

function checkCoupon(code, subtotal) {
  if (!code) return { ok: false };
  let c;
  try { c = q.get('SELECT * FROM coupons WHERE code = ? AND active = 1', String(code).toUpperCase().trim()); } catch (_) { c = null; }
  if (!c) return { ok: false, error: 'invalid' };
  if (c.expires && c.expires < todayStr()) return { ok: false, error: 'expired' };
  if (c.max_uses > 0 && c.used >= c.max_uses) return { ok: false, error: 'used_up' };
  if (subtotal < c.min_spend) return { ok: false, error: 'min_spend', min_spend: c.min_spend };
  const discount = c.kind === 'pct' ? Math.round((subtotal * c.amount) / 100) : Math.min(c.amount, subtotal);
  return { ok: true, code: c.code, discount, kind: c.kind, amount: c.amount };
}

function checkGift(code) {
  if (!code) return { ok: false };
  let g;
  try {
    g = q.get("SELECT * FROM gift_certificates WHERE code = ? AND status = 'active' AND pay_status = 'paid'", String(code).toUpperCase().trim());
  } catch (_) { g = null; }
  if (!g) return { ok: false, error: 'invalid' };
  if (g.balance <= 0) return { ok: false, error: 'empty' };
  return { ok: true, code: g.code, balance: g.balance };
}

// opts: {plan, addons[], pax, date, time, couponCode, giftCode, tip}
function composePrice(o) {
  o = o || {};
  const plan = PLANS[o.plan];
  if (!plan || !plan.bookable) return { ok: false, error: 'plan_not_bookable' };
  const pax = Math.max(1, parseInt(o.pax, 10) || 1);
  const base = plan.price;

  let addonsTotal = 0;
  const addonList = [];
  for (const id of o.addons || []) {
    const a = ADDONS[id];
    if (!a) continue;
    const amt = a.per === 'pax' ? a.price * pax : a.price;
    addonsTotal += amt;
    addonList.push({ id, label: a.name_en, amount: amt });
  }

  const sc = surchargeFor(o.date, o.time);
  const preSurcharge = base + addonsTotal;
  const surcharge = Math.round((preSurcharge * sc.pct) / 100) + sc.fixed;
  const subtotal = preSurcharge + surcharge;

  const cp = checkCoupon(o.couponCode, subtotal);
  const discount = cp.ok ? cp.discount : 0;
  const afterDiscount = Math.max(0, subtotal - discount);

  const gf = checkGift(o.giftCode);
  const giftApplied = gf.ok ? Math.min(gf.balance, afterDiscount) : 0;

  const tip = Math.max(0, parseInt(o.tip, 10) || 0);
  const total = Math.max(0, afterDiscount - giftApplied + tip);
  const deposit = Math.round(afterDiscount * 0.3); // deposit on service value (excl gift/tip)

  const breakdown = [{ label: plan.name_en, amount: base }, ...addonList.map((a) => ({ label: a.label, amount: a.amount }))];
  if (surcharge > 0) breakdown.push({ label: sc.labels.join(' + ') || 'Surcharge', amount: surcharge });
  if (discount > 0) breakdown.push({ label: 'Coupon ' + (cp.code || ''), amount: -discount });
  if (giftApplied > 0) breakdown.push({ label: 'Gift ' + (gf.code || ''), amount: -giftApplied });
  if (tip > 0) breakdown.push({ label: 'Gratuity', amount: tip });

  return {
    ok: true, base, addonsTotal, surcharge, surchargeLabels: sc.labels, subtotal,
    discount, coupon: cp.ok ? cp.code : null, couponError: o.couponCode && !cp.ok ? cp.error : null,
    giftApplied, giftCode: gf.ok ? gf.code : null, giftError: o.giftCode && !gf.ok ? gf.error : null,
    tip, total, deposit, breakdown,
  };
}

module.exports = { composePrice, checkCoupon, checkGift, surchargeFor };
