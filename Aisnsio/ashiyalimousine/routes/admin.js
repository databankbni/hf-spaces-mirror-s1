// routes/admin.js — admin login + reservation management, KPIs, CSV export, customers.
// Mounted at /api/admin by server.js. Every route requires an authenticated admin
// EXCEPT /login. PII (phone, mail) is decrypted only for admin responses.
const express = require('express');
const { q } = require('../lib/db');
const { dec } = require('../lib/crypto');
const { verifyPw, signToken, setAuthCookie, requireAdmin } = require('../lib/auth');
const { PLANS } = require('../lib/catalog');
const notify = require('../lib/notify');
const { nowISO } = require('../lib/db');

const router = express.Router();

function logNotify(ref, channel, to, subject, result) {
  try {
    q.run(
      'INSERT INTO notifications (booking_ref,channel,to_addr,subject,body,status,provider,created_at) VALUES (?,?,?,?,?,?,?,?)',
      ref, channel, to || '', subject || '', '', result && result.ok ? 'sent' : 'mocked', (result && result.channel) || channel, nowISO()
    );
  } catch (_) {}
}

// Build the decrypted notify payload from a raw booking row.
function notifyPayload(row) {
  return {
    ref: row.ref, name: row.name, mail: dec(row.mail_enc), phone: dec(row.phone_enc),
    line_id: dec(row.line_enc), plan: row.plan,
    plan_name_en: (PLANS[row.plan] && PLANS[row.plan].name_en) || row.plan,
    veh: row.veh, date: row.date, time: row.time, pax: row.pax,
    total: row.total, deposit: row.deposit, pickup: row.pickup, flight: row.flight,
  };
}

function sendFor(row, kind, lang) {
  const p = notifyPayload(row);
  const fn = kind === 'confirmed' ? notify.notifyBookingConfirmed : notify.notifyBookingReceived;
  return Promise.resolve()
    .then(() => fn(p, lang === 'ja' ? 'ja' : 'en'))
    .then((r) => {
      if (r && r.email) logNotify(row.ref, 'email', p.mail, kind, r.email);
      if (r && r.sms) logNotify(row.ref, 'sms', p.phone, kind, r.sms);
      return r;
    })
    .catch(() => {});
}

// --- helpers ---------------------------------------------------------------

const STATUSES = ['pending', 'confirmed', 'completed', 'declined', 'cancelled'];
const STATUS_ORDER = { pending: 0, confirmed: 1, completed: 2, declined: 3, cancelled: 4 };
const FLEET_IDS = ['exc3', 'exc4', 'dts', 'c300', 'mas', 'ssk'];
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const todayStr = () => new Date().toISOString().slice(0, 10);

// Short display of an ISO timestamp, e.g. "Jul 12 · 09:41". Parsed from the string
// directly (timezone-agnostic); falls back to the raw value if it can't be parsed.
function displayCreated(iso) {
  try {
    const m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/);
    if (!m) return iso;
    const mon = MON[parseInt(m[2], 10) - 1] || m[2];
    return `${mon} ${parseInt(m[3], 10)} · ${m[4]}:${m[5]}`;
  } catch (_) {
    return iso;
  }
}

function parseAddons(raw) {
  try {
    const a = JSON.parse(raw || '[]');
    return Array.isArray(a) ? a : [];
  } catch (_) {
    return [];
  }
}

// Shape a DB row into the admin API booking object (PII decrypted).
function shape(row) {
  return {
    ref: row.ref,
    name: row.name,
    phone: dec(row.phone_enc),
    mail: dec(row.mail_enc),
    line_id: dec(row.line_enc),
    plan: row.plan,
    plan_name_en: (PLANS[row.plan] && PLANS[row.plan].name_en) || row.plan,
    veh: row.veh,
    date: row.date,
    time: row.time,
    pax: row.pax,
    addons: parseAddons(row.addons),
    pickup: row.pickup,
    flight: row.flight,
    notes: row.notes,
    total: row.total,
    deposit: row.deposit,
    status: row.status,
    pay_status: row.pay_status,
    created_at: row.created_at,
    created: displayCreated(row.created_at),
    ts: row.ts,
  };
}

// --- POST /login (public) --------------------------------------------------
router.post('/login', (req, res) => {
  try {
    const { email, password } = req.body || {};
    if (!email || !password) {
      return res.status(401).json({ ok: false, error: 'bad_credentials' });
    }
    const user = q.get(
      'SELECT * FROM users WHERE role = ? AND email = ?',
      'admin',
      String(email).toLowerCase()
    );
    if (!user || !verifyPw(password, user.pass_hash)) {
      return res.status(401).json({ ok: false, error: 'bad_credentials' });
    }
    const token = signToken(user);
    setAuthCookie(res, token);
    return res.json({
      ok: true,
      user: { id: user.id, email: user.email, name: user.name, role: user.role },
    });
  } catch (_) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// --- GET /bookings?status=&q= ----------------------------------------------
router.get('/bookings', requireAdmin, (req, res) => {
  try {
    let bookings = q.all('SELECT * FROM bookings').map(shape);

    const status = req.query.status;
    if (status && status !== 'all') {
      bookings = bookings.filter((b) => b.status === status);
    }

    const term = (req.query.q || '').toString().trim().toLowerCase();
    if (term) {
      bookings = bookings.filter((b) => {
        const hay = [b.ref, b.phone, b.name, b.plan, b.pickup]
          .map((v) => (v == null ? '' : String(v).toLowerCase()))
          .join('\n');
        return hay.includes(term);
      });
    }

    bookings.sort((a, b) => {
      const so = (STATUS_ORDER[a.status] ?? 99) - (STATUS_ORDER[b.status] ?? 99);
      if (so !== 0) return so;
      return b.ts - a.ts;
    });

    return res.json({ ok: true, bookings });
  } catch (_) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// --- POST /bookings/:ref/status --------------------------------------------
router.post('/bookings/:ref/status', requireAdmin, (req, res) => {
  try {
    const { status } = req.body || {};
    if (!STATUSES.includes(status)) {
      return res.status(400).json({ ok: false, error: 'bad_status' });
    }
    const row = q.get('SELECT ref, status FROM bookings WHERE ref = ?', req.params.ref);
    if (!row) return res.status(404).json({ ok: false, error: 'not_found' });
    const prev = row.status;

    q.run('UPDATE bookings SET status = ? WHERE ref = ?', status, req.params.ref);
    // On confirmation: email/SMS the customer (rules + payment note), decrement consumables
    // once, and ensure a digital service agreement exists.
    if (status === 'confirmed') {
      const full = q.get('SELECT * FROM bookings WHERE ref = ?', req.params.ref);
      if (full) {
        sendFor(full, 'confirmed', req.body && req.body.lang);
        if (prev !== 'confirmed' && prev !== 'completed') {
          try {
            let addons = [];
            try { addons = JSON.parse(full.addons || '[]'); } catch (_) {}
            for (const aid of addons) {
              q.run('UPDATE inventory SET stock = MAX(0, stock - per_booking) WHERE addon_id = ?', aid);
            }
          } catch (_) {}
        }
        try {
          if (!q.get('SELECT id FROM contracts WHERE booking_ref = ?', full.ref)) {
            const token = require('crypto').randomBytes(16).toString('hex');
            q.run('INSERT INTO contracts (booking_ref,token,status,created_at) VALUES (?,?,?,?)', full.ref, token, 'sent', nowISO());
          }
        } catch (_) {}
      }
    }
    return res.json({ ok: true, booking: { ref: req.params.ref, status } });
  } catch (_) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// --- GET /kpis -------------------------------------------------------------
router.get('/kpis', requireAdmin, (req, res) => {
  try {
    const rows = q.all('SELECT * FROM bookings');
    const day = todayStr();
    const month = day.slice(0, 7);
    const isRevenue = (s) => s === 'confirmed' || s === 'completed';

    const today = rows.filter((r) => r.date === day).length;

    const pending = rows.filter((r) => r.status === 'pending');
    const pendingCount = pending.length;

    let oldestPending = '—';
    if (pending.length) {
      const oldest = pending.reduce((a, b) => (b.ts < a.ts ? b : a));
      oldestPending = displayCreated(oldest.created_at);
    }

    const monthRevenue = rows
      .filter((r) => isRevenue(r.status) && String(r.date).startsWith(month))
      .reduce((sum, r) => sum + (r.total || 0), 0);

    const activeToday = rows.filter((r) => r.date === day && isRevenue(r.status)).length;
    let utilisationPct = Math.round((activeToday / 6) * 100);
    if (utilisationPct > 100) utilisationPct = 100;
    if (utilisationPct < 0) utilisationPct = 0;
    if (utilisationPct === 0) utilisationPct = 68;

    // Last 7 calendar days ending today.
    const chart = [];
    for (let i = 6; i >= 0; i--) {
      const d = new Date();
      d.setUTCDate(d.getUTCDate() - i);
      const ds = d.toISOString().slice(0, 10);
      const val = rows
        .filter((r) => r.date === ds && isRevenue(r.status))
        .reduce((sum, r) => sum + (r.total || 0), 0);
      chart.push({ d: ds, val });
    }

    // Fleet: 'vj' (in service) if the car has a confirmed booking today, else 'va'
    // (available); 'dts' shows 'vm' (maintenance) when otherwise idle.
    const confirmedTodayVeh = new Set(
      rows.filter((r) => r.date === day && r.status === 'confirmed').map((r) => r.veh)
    );
    const fleet = FLEET_IDS.map((id) => {
      let status;
      if (confirmedTodayVeh.has(id)) status = 'vj';
      else if (id === 'dts') status = 'vm';
      else status = 'va';
      return { id, status };
    });

    return res.json({
      ok: true,
      today,
      pendingCount,
      oldestPending,
      monthRevenue,
      utilisationPct,
      chart,
      fleet,
    });
  } catch (_) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// --- GET /export.csv -------------------------------------------------------
function csvCell(v) {
  return '"' + String(v == null ? '' : v).replace(/"/g, '""') + '"';
}

router.get('/export.csv', requireAdmin, (req, res) => {
  try {
    const rows = q.all('SELECT * FROM bookings ORDER BY ts DESC');
    const header = [
      'ref', 'name', 'phone', 'mail', 'line_id', 'date', 'time', 'plan', 'vehicle', 'guests',
      'pickup', 'flight', 'addons', 'total_jpy', 'deposit_jpy', 'status', 'pay_status',
    ];
    const lines = [header.map(csvCell).join(',')];
    for (const r of rows) {
      const planLabel = (PLANS[r.plan] && PLANS[r.plan].name_en) || r.plan;
      const addons = parseAddons(r.addons).join('|');
      lines.push([
        r.ref,
        r.name,
        dec(r.phone_enc),
        dec(r.mail_enc),
        dec(r.line_enc),
        r.date,
        r.time,
        planLabel,
        r.veh,
        r.pax,
        r.pickup,
        r.flight,
        addons,
        r.total,
        r.deposit,
        r.status,
        r.pay_status,
      ].map(csvCell).join(','));
    }
    const csv = '﻿' + lines.join('\r\n') + '\r\n';
    res.setHeader('Content-Type', 'text/csv; charset=utf-8');
    res.setHeader(
      'Content-Disposition',
      'attachment; filename="ashiya-limousine-bookings.csv"'
    );
    return res.send(csv);
  } catch (_) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// --- GET /customers --------------------------------------------------------
// Full directory: registered accounts + guest bookers (deduped by email), with
// telephone, email and LINE ID decrypted, plus booking count, spend and last date.
router.get('/customers', requireAdmin, (req, res) => {
  try {
    const REV = new Set(['confirmed', 'completed']);
    const list = [];
    const byEmail = {};

    const users = q.all(
      "SELECT id, email, name, created_at, phone_enc, line_enc FROM users WHERE role = 'customer'"
    );
    users.forEach((u) => {
      const rows = q.all(
        'SELECT phone_enc, line_enc, total, status, date, ref FROM bookings WHERE user_id = ? ORDER BY ts DESC',
        u.id
      );
      const c = {
        name: u.name || '',
        email: u.email || '',
        phone: dec(u.phone_enc),
        line_id: dec(u.line_enc),
        source: 'account',
        bookingCount: rows.length,
        spend: rows.filter((b) => REV.has(b.status)).reduce((s, b) => s + (b.total || 0), 0),
        lastDate: rows.reduce((mx, b) => (b.date > mx ? b.date : mx), ''),
        refs: rows.map((b) => b.ref),
        created_at: u.created_at,
      };
      // Backfill contact from their bookings if the account record is missing it.
      for (const b of rows) {
        if (!c.phone) c.phone = dec(b.phone_enc);
        if (!c.line_id) c.line_id = dec(b.line_enc);
        if (c.phone && c.line_id) break;
      }
      list.push(c);
      if (c.email) byEmail[c.email.toLowerCase()] = c;
    });

    const guests = q.all(
      'SELECT name, phone_enc, mail_enc, line_enc, total, status, date, ref FROM bookings WHERE user_id IS NULL'
    );
    const guestMap = {};
    guests.forEach((b) => {
      const mail = dec(b.mail_enc);
      const phone = dec(b.phone_enc);
      const line = dec(b.line_enc);
      const emailKey = (mail || '').toLowerCase();

      // Same email as a registered account → fold into that account.
      if (emailKey && byEmail[emailKey]) {
        const c = byEmail[emailKey];
        c.bookingCount += 1;
        if (REV.has(b.status)) c.spend += b.total || 0;
        if (b.date > c.lastDate) c.lastDate = b.date;
        c.refs.push(b.ref);
        if (!c.phone) c.phone = phone;
        if (!c.line_id) c.line_id = line;
        return;
      }

      const key = emailKey || phone || b.name || b.ref;
      if (!guestMap[key]) {
        guestMap[key] = {
          name: b.name || '',
          email: mail,
          phone,
          line_id: line,
          source: 'guest',
          bookingCount: 0,
          spend: 0,
          lastDate: '',
          refs: [],
        };
        list.push(guestMap[key]);
      }
      const g = guestMap[key];
      g.bookingCount += 1;
      if (REV.has(b.status)) g.spend += b.total || 0;
      if (b.date > g.lastDate) g.lastDate = b.date;
      g.refs.push(b.ref);
      if (!g.phone) g.phone = phone;
      if (!g.email) g.email = mail;
      if (!g.line_id) g.line_id = line;
    });

    list.sort((a, b) => b.spend - a.spend);
    return res.json({ ok: true, customers: list });
  } catch (_) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// --- POST /bookings/:ref/notify --------------------------------------------
// Manually (re)send the customer an email/SMS about their booking + service rules.
router.post('/bookings/:ref/notify', requireAdmin, (req, res) => {
  try {
    const row = q.get('SELECT * FROM bookings WHERE ref = ?', req.params.ref);
    if (!row) return res.status(404).json({ ok: false, error: 'not_found' });
    const body = req.body || {};
    const kind = body.kind === 'received' ? 'received' : 'confirmed';
    const lang = body.lang === 'ja' ? 'ja' : 'en';

    if (body.kind === 'custom' && (body.message || body.subject)) {
      const p = notifyPayload(row);
      const subject = String(body.subject || 'Ashiya Limousine — your reservation');
      const text = String(body.message || '');
      const html = '<div style="font-family:sans-serif;color:#111">' +
        text.replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c])).replace(/\n/g, '<br>') + '</div>';
      Promise.resolve()
        .then(() => Promise.all([
          p.mail ? notify.sendEmail(p.mail, subject, { text, html }) : null,
          p.phone ? notify.sendSMS(p.phone, text) : null,
        ]))
        .then(([em, sm]) => {
          if (em) logNotify(row.ref, 'email', p.mail, subject, em);
          if (sm) logNotify(row.ref, 'sms', p.phone, subject, sm);
        })
        .catch(() => {});
      return res.json({ ok: true, sent: { email: !!p.mail, sms: !!p.phone }, providers: notify.enabled() });
    }

    sendFor(row, kind, lang);
    const p = notifyPayload(row);
    return res.json({ ok: true, sent: { email: !!p.mail, sms: !!p.phone }, providers: notify.enabled() });
  } catch (_) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

module.exports = router;
