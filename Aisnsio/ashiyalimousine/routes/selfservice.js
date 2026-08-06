// routes/selfservice.js — customer self-service: reschedule, cancel, printable invoice.
// Mounted at /api/selfservice by server.js. Global express.json() already parses bodies,
// so no express.json() here. All actions are owner-or-admin gated via authorize().
const express = require('express');
const { q, nowISO } = require('../lib/db');
const { dec } = require('../lib/crypto');
const { requireAuth } = require('../lib/auth');
const { PLANS } = require('../lib/catalog');

const router = express.Router();

// Owner (or admin) may act on a booking row.
const authorize = (req, row) => row.user_id === req.user.uid || req.user.role === 'admin';

const loadBooking = (ref) =>
  q.get('SELECT * FROM bookings WHERE ref = ?', String(ref || ''));

// Escape user-supplied strings before embedding in HTML.
function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

const yen = (n) => '¥' + Number(n || 0).toLocaleString('en-US');

// ---- POST /reschedule -----------------------------------------------------
router.post('/reschedule', requireAuth, (req, res) => {
  try {
    const { ref, date, time } = req.body || {};
    const row = loadBooking(ref);
    if (!row) return res.status(404).json({ ok: false, error: 'not_found' });
    if (!authorize(req, row)) return res.status(403).json({ ok: false, error: 'forbidden' });
    if (!['pending', 'confirmed'].includes(row.status))
      return res.status(400).json({ ok: false, error: 'not_reschedulable' });
    if (!date || !time)
      return res.status(400).json({ ok: false, error: 'missing_fields' });

    // Availability lock: a non-twin vehicle can only be in one place at a time.
    if (row.veh && row.veh !== 'twin') {
      const clash = q.get(
        `SELECT 1 FROM bookings
          WHERE veh = ? AND date = ? AND time = ? AND ref <> ?
            AND status IN ('pending','confirmed') LIMIT 1`,
        row.veh, date, time, row.ref
      );
      if (clash) return res.status(409).json({ ok: false, error: 'slot_taken' });
    }

    q.run('UPDATE bookings SET date = ?, time = ? WHERE ref = ?', date, time, row.ref);
    return res.json({ ok: true });
  } catch (_) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// ---- POST /cancel ---------------------------------------------------------
router.post('/cancel', requireAuth, (req, res) => {
  try {
    const { ref } = req.body || {};
    const row = loadBooking(ref);
    if (!row) return res.status(404).json({ ok: false, error: 'not_found' });
    if (!authorize(req, row)) return res.status(403).json({ ok: false, error: 'forbidden' });
    if (row.status === 'completed')
      return res.status(400).json({ ok: false, error: 'already_completed' });

    q.run('UPDATE bookings SET status = ? WHERE ref = ?', 'cancelled', row.ref);

    // Policy: same-day / day-before cancellations are non-refundable.
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    const cutoff = tomorrow.toISOString().slice(0, 10); // today + 1 day (YYYY-MM-DD)
    const policy_note =
      String(row.date || '') <= cutoff
        ? 'Same-day/day-before cancellations are charged 100% per policy.'
        : 'Cancelled with no charge.';

    return res.json({ ok: true, policy_note });
  } catch (_) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// ---- GET /invoice/:ref ----------------------------------------------------
router.get('/invoice/:ref', requireAuth, (req, res) => {
  try {
    const row = loadBooking(req.params.ref);
    if (!row) {
      res.status(404).type('html');
      return res.send('<!doctype html><meta charset="utf-8"><title>Invoice not found</title><p style="font-family:serif">Invoice not found.</p>');
    }
    if (!authorize(req, row)) {
      res.status(403).type('html');
      return res.send('<!doctype html><meta charset="utf-8"><title>Forbidden</title><p style="font-family:serif">You are not permitted to view this invoice.</p>');
    }

    const total = Number(row.total || 0);
    const base = Number(row.base != null ? row.base : total);
    const surcharge = Number(row.surcharge || 0);
    const discount = Number(row.discount || 0);
    const tip = Number(row.tip || 0);
    const deposit = Number(row.deposit || 0);
    const tax = Math.round(total - total / 1.1);
    const issue = nowISO().slice(0, 10);
    const planName = (PLANS[row.plan] && PLANS[row.plan].name_en) || row.plan || '—';

    const rows = [];
    rows.push(`<tr><td>Plan base <span class="sub">${esc(planName)}</span></td><td class="amt">${yen(base)}</td></tr>`);
    if (surcharge > 0) rows.push(`<tr><td>Surcharge <span class="sub">weekend / night / peak</span></td><td class="amt">${yen(surcharge)}</td></tr>`);
    if (discount > 0) rows.push(`<tr><td>Discount${row.coupon ? ' <span class="sub">' + esc(row.coupon) + '</span>' : ''}</td><td class="amt">&minus;${yen(discount)}</td></tr>`);
    if (Number(row.gift_applied || 0) > 0) rows.push(`<tr><td>Gift certificate applied</td><td class="amt">&minus;${yen(row.gift_applied)}</td></tr>`);
    if (tip > 0) rows.push(`<tr><td>Gratuity</td><td class="amt">${yen(tip)}</td></tr>`);

    const html = `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ashiya Limousine Service — Invoice / 請求書 · ${esc(row.ref)}</title>
<style>
  * { box-sizing: border-box; }
  html, body { background: #ffffff; color: #111; }
  body { font-family: "Helvetica Neue", Arial, sans-serif; margin: 0; padding: 32px 20px; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .sheet { max-width: 760px; margin: 0 auto; padding: 48px 52px; border: 1px solid #e6e0d2; }
  h1, h2, h3, .brand { font-family: "Hoefler Text", Georgia, "Times New Roman", serif; }
  .brand { font-size: 24px; letter-spacing: .5px; color: #111; margin: 0; }
  .brand .accent { color: #b8912e; }
  .tagline { color: #666; font-size: 12px; letter-spacing: 2px; text-transform: uppercase; margin: 6px 0 0; }
  .top { display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 2px solid #b8912e; padding-bottom: 20px; margin-bottom: 26px; }
  .doc-title { font-size: 20px; margin: 0 0 8px; color: #111; }
  .meta { font-size: 13px; color: #333; line-height: 1.7; text-align: right; }
  .meta b { color: #111; }
  .cols { display: flex; justify-content: space-between; gap: 24px; margin-bottom: 28px; }
  .block h3 { font-size: 12px; letter-spacing: 1.5px; text-transform: uppercase; color: #b8912e; margin: 0 0 8px; }
  .block div { font-size: 14px; line-height: 1.6; color: #222; }
  table { width: 100%; border-collapse: collapse; margin: 8px 0 4px; }
  th { text-align: left; font-size: 11px; letter-spacing: 1.5px; text-transform: uppercase; color: #888; border-bottom: 1px solid #ddd; padding: 10px 4px; }
  th.amt, td.amt { text-align: right; }
  td { font-size: 14px; padding: 12px 4px; border-bottom: 1px solid #f0ece0; color: #222; }
  td .sub { color: #999; font-size: 12px; display: block; }
  .total-row td { font-size: 17px; font-weight: 700; border-top: 2px solid #b8912e; border-bottom: none; padding-top: 16px; }
  .tax { font-size: 12px; color: #777; text-align: right; margin: 4px 0 0; }
  .pay { display: flex; gap: 40px; margin-top: 26px; font-size: 14px; }
  .pay .lbl { color: #888; font-size: 11px; letter-spacing: 1px; text-transform: uppercase; display: block; margin-bottom: 4px; }
  .badge { display: inline-block; padding: 2px 10px; border: 1px solid #b8912e; border-radius: 20px; font-size: 12px; color: #7a5f16; }
  footer { margin-top: 40px; padding-top: 18px; border-top: 1px solid #e6e0d2; text-align: center; font-size: 12px; color: #777; line-height: 1.7; }
  .footer-line { font-family: "Hoefler Text", Georgia, serif; color: #444; letter-spacing: .5px; }
  .noprint { margin: 24px auto 0; display: block; }
  button.noprint { background: #b8912e; color: #fff; border: none; padding: 12px 28px; font-size: 14px; letter-spacing: 1px; border-radius: 4px; cursor: pointer; }
  @media print { .noprint { display: none; } body { padding: 0; } .sheet { border: none; padding: 20px 0; } @page { size: A4; margin: 16mm; } }
</style></head>
<body>
  <div class="sheet">
    <div class="top">
      <div>
        <p class="brand">Ashiya Limousine <span class="accent">Service</span></p>
        <p class="tagline">芦屋リムジンサービス</p>
      </div>
      <div class="meta">
        <h2 class="doc-title">Invoice / 請求書</h2>
        <div><b>No.</b> ${esc(row.ref)}</div>
        <div><b>Issued</b> ${esc(issue)}</div>
      </div>
    </div>

    <div class="cols">
      <div class="block">
        <h3>Bill to</h3>
        <div>${esc(row.name)}</div>
      </div>
      <div class="block" style="text-align:right">
        <h3>Service</h3>
        <div>${esc(planName)}<br>
          ${esc(row.date)} · ${esc(row.time)}<br>
          ${esc(row.pax)} guest(s)</div>
      </div>
    </div>

    <table>
      <thead><tr><th>Description</th><th class="amt">Amount</th></tr></thead>
      <tbody>
        ${rows.join('\n        ')}
        <tr class="total-row"><td>Total (tax incl.)</td><td class="amt">${yen(total)}</td></tr>
      </tbody>
    </table>
    <p class="tax">Consumption tax (10% incl.): ${yen(tax)}</p>

    <div class="pay">
      <div><span class="lbl">Deposit</span>${yen(deposit)}</div>
      <div><span class="lbl">Booking status</span><span class="badge">${esc(row.status)}</span></div>
      <div><span class="lbl">Payment status</span><span class="badge">${esc(row.pay_status)}</span></div>
    </div>

    <footer>
      <div class="footer-line">芦屋リムジンサービス · Ashiya, Hyogo · +81-80-5307-4774</div>
      <div>Thank you for riding with us. / ご利用ありがとうございます。</div>
    </footer>

    <button class="noprint" onclick="window.print()">Print / Save PDF</button>
  </div>
</body></html>`;

    res.status(200).type('html').send(html);
  } catch (_) {
    res.status(500).type('html');
    res.send('<!doctype html><meta charset="utf-8"><title>Invoice error</title><p style="font-family:serif">Sorry, the invoice could not be generated.</p>');
  }
});

module.exports = router;
