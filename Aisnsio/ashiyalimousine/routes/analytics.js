'use strict';

/**
 * routes/analytics.js — lightweight event tracking + admin analytics dashboard
 * for Ashiya Limousine.
 *
 * Mounted at /api/analytics (Express Router, CommonJS).
 * Tables: events(id, kind, ref, path, created_at), bookings(... plan, total,
 *   status, date, created_at), users, newsletter, reviews.
 *
 * Endpoints:
 *   POST /track      (public)       {kind, path, ref} -> {ok:true}   (fast, best-effort)
 *   GET  /dashboard  (requireAdmin) -> {ok:true, funnel, revenue, byPlan, byStatus, totals}
 *
 * No express.json() here — body parsing is done by the app. Only express + lib modules.
 */

const express = require('express');
const { q, nowISO } = require('../lib/db');
const { requireAdmin } = require('../lib/auth');
const { PLANS } = require('../lib/catalog');

const router = express.Router();

// Only these event kinds are recorded; anything else is silently ignored (still 200).
const TRACK_KINDS = new Set(['visit', 'book_start', 'book_submit', 'pay_click']);

// Trim a value to a string capped at `max` chars (abuse guard), null-safe.
function cap(v, max) {
  if (v == null) return null;
  const s = String(v);
  return s.length > max ? s.slice(0, max) : s;
}

// POST /track (public) — lightweight, fire-and-forget event logging.
router.post('/track', (req, res) => {
  try {
    const body = req.body || {};
    const kind = String(body.kind == null ? '' : body.kind);
    if (TRACK_KINDS.has(kind)) {
      q.run(
        'INSERT INTO events (kind, ref, path, created_at) VALUES (?, ?, ?, ?)',
        kind, cap(body.ref, 200), cap(body.path, 200), nowISO()
      );
    }
    // Unknown kinds are ignored but still acknowledged.
    return res.json({ ok: true });
  } catch (e) {
    // Never let tracking break the client — acknowledge anyway.
    return res.json({ ok: true });
  }
});

const PAID_STATUSES = "('confirmed','completed')";

// GET /dashboard (requireAdmin) — funnel, revenue, plan/status breakdowns, totals.
router.get('/dashboard', requireAdmin, (req, res) => {
  try {
    // ---- funnel: event counts by kind ----
    const evRows = q.all('SELECT kind, COUNT(*) AS n FROM events GROUP BY kind');
    const evMap = {};
    for (const r of evRows) evMap[r.kind] = r.n;
    const visit = evMap.visit || 0;
    const bookStart = evMap.book_start || 0;
    const bookSubmit = evMap.book_submit || 0;
    const funnel = {
      visit,
      book_start: bookStart,
      book_submit: bookSubmit,
      conversionPct: Math.round((bookSubmit / Math.max(visit, 1)) * 100),
    };

    // ---- byStatus: booking counts grouped by status ----
    const byStatus = {};
    for (const r of q.all('SELECT status, COUNT(*) AS n FROM bookings GROUP BY status')) {
      byStatus[r.status] = r.n;
    }

    // ---- revenue ----
    const ym = nowISO().slice(0, 7); // current YYYY-MM
    const monthRow = q.get(
      `SELECT COALESCE(SUM(total), 0) AS s FROM bookings
       WHERE status IN ${PAID_STATUSES} AND substr(date, 1, 7) = ?`,
      ym
    );
    const totalRow = q.get(
      `SELECT COALESCE(SUM(total), 0) AS s FROM bookings WHERE status IN ${PAID_STATUSES}`
    );

    // last 7 days (inclusive of today) keyed by booking date.
    const dayRows = q.all(
      `SELECT date AS d, COALESCE(SUM(total), 0) AS val FROM bookings
       WHERE status IN ${PAID_STATUSES} GROUP BY date`
    );
    const dayMap = {};
    for (const r of dayRows) dayMap[r.d] = r.val;
    const last7 = [];
    const base = new Date(nowISO().slice(0, 10) + 'T00:00:00Z');
    for (let i = 6; i >= 0; i--) {
      const dt = new Date(base.getTime() - i * 86400000);
      const d = dt.toISOString().slice(0, 10);
      last7.push({ d, val: dayMap[d] || 0 });
    }
    const revenue = { month: monthRow.s || 0, total: totalRow.s || 0, last7 };

    // ---- byPlan: per-plan count + confirmed/completed revenue, top 8 by revenue ----
    const planRows = q.all(
      `SELECT plan,
              COUNT(*) AS count,
              COALESCE(SUM(CASE WHEN status IN ${PAID_STATUSES} THEN total ELSE 0 END), 0) AS revenue
       FROM bookings GROUP BY plan`
    );
    const byPlan = planRows
      .map((r) => ({
        plan: r.plan,
        name: (PLANS[r.plan] && PLANS[r.plan].name_en) || r.plan,
        count: r.count,
        revenue: r.revenue,
      }))
      .sort((a, b) => b.revenue - a.revenue)
      .slice(0, 8);

    // ---- totals ----
    const bookings = q.get('SELECT COUNT(*) AS n FROM bookings').n;
    const customers = q.get("SELECT COUNT(*) AS n FROM users WHERE role = 'customer'").n;
    const subscribers = q.get('SELECT COUNT(*) AS n FROM newsletter').n;
    const reviewAgg = q.get(
      'SELECT COUNT(*) AS n, AVG(rating) AS avg FROM reviews WHERE approved = 1'
    );
    const totals = {
      bookings,
      customers,
      subscribers,
      reviews: reviewAgg.n,
      avgRating: reviewAgg.avg == null ? 0 : Math.round(reviewAgg.avg * 10) / 10,
    };

    return res.json({ ok: true, funnel, revenue, byPlan, byStatus, totals });
  } catch (e) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

module.exports = router;
