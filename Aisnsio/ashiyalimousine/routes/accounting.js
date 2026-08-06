'use strict';

/**
 * routes/accounting.js — Japanese accounting export for Ashiya Limousine.
 *
 * Mounted at /api/accounting (Express Router, CommonJS). requireAdmin on all.
 * Revenue = bookings with status IN (confirmed, completed), filtered on the
 * booking `date` field. Amounts are tax-inclusive JPY (消費税10% 内税).
 *
 * Endpoints:
 *   GET /export.csv?from=&to=&format=freee|mf|generic  -> UTF-8 BOM CSV
 *   GET /summary                                        -> monthly revenue JSON
 *
 * No express.json() here — this router has no body-reading routes. Only
 * express + lib modules are used.
 */

const express = require('express');
const { q } = require('../lib/db');
const { requireAdmin } = require('../lib/auth');
const { PLANS } = require('../lib/catalog');

const router = express.Router();

// Human-friendly plan name, falling back to the raw plan id.
function planName(id) {
  return (PLANS[id] && PLANS[id].name_en) || id || '';
}

// tax portion of a tax-inclusive total at 10% (内税): total - total / 1.1
function taxIncl(total) {
  return Math.round(Number(total || 0) - Number(total || 0) / 1.1);
}

// Quote every CSV field and escape embedded quotes by doubling them.
function csvCell(v) {
  return '"' + String(v == null ? '' : v).replace(/"/g, '""') + '"';
}

function csvRow(cells) {
  return cells.map(csvCell).join(',');
}

// A YYYY-MM-DD looking string, else null (so bad query params are ignored).
function cleanDate(v) {
  return typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) ? v : null;
}

// Fetch confirmed+completed revenue rows within an optional [from,to] date range.
function revenueRows(from, to) {
  const where = ["status IN ('confirmed','completed')"];
  const params = [];
  if (from) { where.push('date >= ?'); params.push(from); }
  if (to) { where.push('date <= ?'); params.push(to); }
  return q.all(
    `SELECT ref, name, plan, date, time, total, deposit, tip, status, pay_status
       FROM bookings
      WHERE ${where.join(' AND ')}
      ORDER BY date ASC, ref ASC`,
    ...params
  );
}

// ---- CSV builders per format ----------------------------------------------
const FORMATS = {
  generic: {
    header: ['date', 'ref', 'customer', 'plan', 'total_jpy', 'tax_10pct_incl', 'deposit_jpy', 'status', 'pay_status'],
    row: (r) => [
      r.date, r.ref, r.name, planName(r.plan),
      r.total, taxIncl(r.total), r.deposit, r.status, r.pay_status,
    ],
  },
  freee: {
    // freee 会計 import-friendly columns.
    header: ['取引日', '勘定科目', '税区分', '金額', '備考'],
    row: (r) => [
      r.date, '売上高', '課税売上10%', r.total,
      `${r.ref} ${planName(r.plan)}`,
    ],
  },
  mf: {
    // MoneyForward (マネーフォワード) 仕訳 columns.
    header: ['取引No', '取引日', '借方勘定科目', '貸方勘定科目', '金額', '摘要'],
    row: (r) => [
      r.ref, r.date, '売掛金', '売上高', r.total,
      `${r.name} ${planName(r.plan)}`,
    ],
  },
};

// GET /export.csv?from=YYYY-MM-DD&to=YYYY-MM-DD&format=freee|mf|generic
router.get('/export.csv', requireAdmin, (req, res) => {
  try {
    const key = String(req.query.format || 'generic').toLowerCase();
    const fmt = FORMATS[key] || FORMATS.generic;
    const name = FORMATS[key] ? key : 'generic';
    const from = cleanDate(req.query.from);
    const to = cleanDate(req.query.to);

    const rows = revenueRows(from, to);
    const lines = [csvRow(fmt.header)];
    for (const r of rows) lines.push(csvRow(fmt.row(r)));

    const csv = '﻿' + lines.join('\r\n') + '\r\n';
    res.setHeader('Content-Type', 'text/csv; charset=utf-8');
    res.setHeader('Content-Disposition', `attachment; filename="ashiya-accounting-${name}.csv"`);
    return res.send(csv);
  } catch (_) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

// GET /summary -> { ok, months:[{month,revenue,tax,count}], totals }
router.get('/summary', requireAdmin, (req, res) => {
  try {
    const rows = q.all(
      `SELECT substr(date,1,7) AS month, total
         FROM bookings
        WHERE status IN ('confirmed','completed')`
    );
    // Aggregate per month in JS so per-booking tax rounding matches the export.
    const map = new Map();
    for (const r of rows) {
      const m = r.month || '';
      const cur = map.get(m) || { month: m, revenue: 0, tax: 0, count: 0 };
      cur.revenue += Number(r.total || 0);
      cur.tax += taxIncl(r.total);
      cur.count += 1;
      map.set(m, cur);
    }
    // Last 6 months that actually appear in the data, chronological order.
    const months = Array.from(map.values())
      .sort((a, b) => (a.month < b.month ? -1 : a.month > b.month ? 1 : 0))
      .slice(-6);

    const totals = months.reduce(
      (t, m) => ({ revenue: t.revenue + m.revenue, tax: t.tax + m.tax, count: t.count + m.count }),
      { revenue: 0, tax: 0, count: 0 }
    );

    return res.json({ ok: true, months, totals });
  } catch (_) {
    return res.status(500).json({ ok: false, error: 'server_error' });
  }
});

module.exports = router;
