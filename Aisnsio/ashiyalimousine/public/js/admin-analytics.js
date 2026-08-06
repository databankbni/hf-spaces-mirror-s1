/* admin-analytics.js — Analytics dashboard for the Ashiya Limousine staff dashboard.
   Self-contained browser module. Loads after the main inline script via
   <script src="/js/admin-analytics.js" defer></script>. Binds to #admAnalytics,
   opens a wide modal with KPI tiles, a conversion funnel, a 7-day revenue mini
   chart, a top-plans table and a status breakdown. No chart libraries — every
   visual is built from divs/SVG. Bilingual EN/JA. Reuses window.ALSCore + the
   site's CSS variables/design tokens. No frameworks. Never throws. */
(function () {
  'use strict';
  if (window.__alsAnalyticsInit) return;
  window.__alsAnalyticsInit = true;

  var STYLE_ID = 'als-analytics-style';
  var MODAL_ID = 'alsAnalyticsModal';

  /* -------- helpers -------- */
  function esc(v) {
    return String(v == null ? '' : v)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function isJA() {
    var l = (window.ALSCore && window.ALSCore.L) || document.documentElement.lang || 'en';
    return String(l).toLowerCase().indexOf('ja') === 0;
  }

  function labels() {
    return isJA()
      ? { title: '分析', sub: '事業ダッシュボード',
          revMonth: '今月の売上', revTotal: '累計売上', bookings: '予約',
          customers: '顧客', subscribers: '購読者', avgRating: '平均評価',
          funnel: 'ファネル', visits: '訪問', bookStart: '予約開始', bookSubmit: '予約送信',
          conversion: '転換率', last7: '直近7日', revenue: '売上',
          topPlans: '人気プラン', plan: 'プラン', count: '予約数',
          status: 'ステータス内訳', empty: 'データがありません', dash: '—',
          st_pending: '保留', st_confirmed: '確定', st_completed: '完了',
          st_declined: '却下', st_cancelled: 'キャンセル' }
      : { title: 'Analytics', sub: 'Business dashboard',
          revMonth: 'Month revenue', revTotal: 'Total revenue', bookings: 'Bookings',
          customers: 'Customers', subscribers: 'Subscribers', avgRating: 'Avg rating',
          funnel: 'Funnel', visits: 'Visits', bookStart: 'Booking started', bookSubmit: 'Booking submitted',
          conversion: 'Conversion', last7: 'Last 7 days', revenue: 'Revenue',
          topPlans: 'Top plans', plan: 'Plan', count: 'Bookings',
          status: 'Status breakdown', empty: 'No data yet', dash: '—',
          st_pending: 'Pending', st_confirmed: 'Confirmed', st_completed: 'Completed',
          st_declined: 'Declined', st_cancelled: 'Cancelled' };
  }

  function num(n) {
    var v = Number(n);
    if (!isFinite(v)) v = 0;
    return Math.round(v).toLocaleString('ja-JP');
  }

  function yen(n) {
    return '¥' + num(n);
  }

  /* -------- styles -------- */
  function injectStyles() {
    if (document.getElementById(STYLE_ID)) return;
    var css =
      '#' + MODAL_ID + ' .modal{max-width:900px;text-align:left}' +
      '#' + MODAL_ID + ' h3{text-align:left}' +
      '#' + MODAL_ID + ' .an-sub{text-align:left;font-size:13px;color:var(--muted);margin:-2px 0 20px}' +
      '#' + MODAL_ID + ' .an-sec{margin:22px 0 0}' +
      '#' + MODAL_ID + ' .an-sec:first-of-type{margin-top:0}' +
      '#' + MODAL_ID + ' .an-h{font-family:var(--mono);font-size:9.5px;letter-spacing:.18em;text-transform:uppercase;color:var(--faint);margin:0 0 11px}' +
      /* KPI tiles */
      '#' + MODAL_ID + ' .an-kpis{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}' +
      '#' + MODAL_ID + ' .an-tile{border:1px solid var(--hair);border-radius:12px;padding:13px 14px;background:rgba(255,255,255,.02)}' +
      '#' + MODAL_ID + ' .an-tile .lbl{font-family:var(--mono);font-size:8.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--faint);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}' +
      '#' + MODAL_ID + ' .an-tile .val{font-family:var(--serif);font-size:22px;line-height:1.15;color:var(--cream);margin-top:6px;word-break:break-word}' +
      '#' + MODAL_ID + ' .an-tile .val.gold{color:var(--gold2)}' +
      /* funnel */
      '#' + MODAL_ID + ' .an-fwrap{display:flex;gap:16px;align-items:center;flex-wrap:wrap}' +
      '#' + MODAL_ID + ' .an-funnel{flex:1 1 340px;min-width:0;display:flex;flex-direction:column;gap:9px}' +
      '#' + MODAL_ID + ' .an-frow{display:grid;grid-template-columns:120px 1fr auto;gap:10px;align-items:center}' +
      '#' + MODAL_ID + ' .an-flabel{font-size:12px;color:var(--muted)}' +
      '#' + MODAL_ID + ' .an-ftrack{height:24px;border-radius:7px;background:rgba(255,255,255,.03);border:1px solid var(--hair);overflow:hidden}' +
      '#' + MODAL_ID + ' .an-fbar{height:100%;border-radius:6px;min-width:2px;background:linear-gradient(90deg,var(--gold) 0%,var(--gold2) 100%);transition:width .5s cubic-bezier(.2,.9,.3,1)}' +
      '#' + MODAL_ID + ' .an-fnum{font-family:var(--mono);font-size:13px;color:var(--cream);text-align:right;white-space:nowrap}' +
      '#' + MODAL_ID + ' .an-conv{flex:0 0 auto;text-align:center;border:1px solid var(--line);border-radius:14px;padding:16px 22px;background:var(--golddim)}' +
      '#' + MODAL_ID + ' .an-conv .clbl{font-family:var(--mono);font-size:9px;letter-spacing:.16em;text-transform:uppercase;color:var(--gold);white-space:nowrap}' +
      '#' + MODAL_ID + ' .an-conv .cval{font-family:var(--serif);font-size:38px;line-height:1;color:var(--gold2);margin-top:6px}' +
      /* 7-day chart */
      '#' + MODAL_ID + ' .an-chart{display:flex;gap:6px;align-items:flex-end;height:130px;padding:0 2px}' +
      '#' + MODAL_ID + ' .an-col{flex:1 1 0;display:flex;flex-direction:column;align-items:center;gap:6px;min-width:0}' +
      '#' + MODAL_ID + ' .an-coltrack{width:100%;flex:1;display:flex;align-items:flex-end}' +
      '#' + MODAL_ID + ' .an-colbar{width:100%;border-radius:5px 5px 0 0;min-height:2px;background:linear-gradient(180deg,var(--gold2) 0%,var(--gold) 100%);transition:height .5s cubic-bezier(.2,.9,.3,1)}' +
      '#' + MODAL_ID + ' .an-colbar.zero{background:rgba(255,255,255,.06)}' +
      '#' + MODAL_ID + ' .an-colday{font-family:var(--mono);font-size:10px;color:var(--faint)}' +
      /* table */
      '#' + MODAL_ID + ' .an-scroll{overflow-x:auto;border:1px solid var(--hair);border-radius:12px}' +
      '#' + MODAL_ID + ' table.an-tbl{width:100%;border-collapse:collapse;min-width:420px;font-size:13px}' +
      '#' + MODAL_ID + ' .an-tbl th{font-family:var(--mono);font-size:9.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--faint);text-align:left;padding:10px 14px;border-bottom:1px solid var(--hair);white-space:nowrap;background:rgba(255,255,255,.02)}' +
      '#' + MODAL_ID + ' .an-tbl td{padding:10px 14px;border-bottom:1px solid var(--hair);color:var(--cream)}' +
      '#' + MODAL_ID + ' .an-tbl tr:last-child td{border-bottom:none}' +
      '#' + MODAL_ID + ' .an-tbl tr:hover td{background:rgba(212,175,55,.05)}' +
      '#' + MODAL_ID + ' .an-tbl .plan{font-family:var(--serif);font-size:15px}' +
      '#' + MODAL_ID + ' .an-tbl th.num,#' + MODAL_ID + ' .an-tbl td.num{text-align:right;font-family:var(--mono)}' +
      '#' + MODAL_ID + ' .an-tbl td.rev{color:var(--gold2)}' +
      /* status pills */
      '#' + MODAL_ID + ' .an-stats{display:flex;gap:10px;flex-wrap:wrap}' +
      '#' + MODAL_ID + ' .an-stat{display:flex;align-items:center;gap:8px;border:1px solid var(--hair);border-radius:10px;padding:8px 13px}' +
      '#' + MODAL_ID + ' .an-stat .n{font-family:var(--mono);font-size:15px;color:var(--cream)}' +
      '#' + MODAL_ID + ' .an-empty{padding:26px 14px;text-align:center;color:var(--muted);font-size:13px}' +
      '@media(max-width:640px){#' + MODAL_ID + ' .an-kpis{grid-template-columns:repeat(2,1fr)}' +
        '#' + MODAL_ID + ' .an-frow{grid-template-columns:96px 1fr auto}}';
    var s = document.createElement('style');
    s.id = STYLE_ID;
    s.textContent = css;
    document.head.appendChild(s);
  }

  /* -------- state + modal shell -------- */
  var state = { lab: null };

  function buildModal() {
    var existing = document.getElementById(MODAL_ID);
    if (existing) return existing;
    var wrap = document.createElement('div');
    wrap.className = 'modal-bg';
    wrap.id = MODAL_ID;
    wrap.innerHTML =
      '<div class="modal" role="dialog" aria-modal="true">' +
        '<button class="x" type="button" data-an-close aria-label="close">' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>' +
        '</button>' +
        '<h3 data-an-title></h3>' +
        '<div class="an-sub" data-an-sub></div>' +
        '<div data-an-body></div>' +
      '</div>';
    document.body.appendChild(wrap);

    // close: X button + backdrop click
    wrap.addEventListener('click', function (e) {
      if (e.target === wrap || (e.target.closest && e.target.closest('[data-an-close]'))) {
        closeModal();
      }
    });
    return wrap;
  }

  function closeModal() {
    var m = document.getElementById(MODAL_ID);
    if (m) m.classList.remove('open');
    document.removeEventListener('keydown', onKey);
  }

  function onKey(e) {
    if (e.key === 'Escape') closeModal();
  }

  function isOpen() {
    var m = document.getElementById(MODAL_ID);
    return !!(m && m.classList.contains('open'));
  }

  /* -------- section renderers -------- */
  function renderKpis(totals, revenue, lab) {
    totals = totals || {};
    revenue = revenue || {};
    var tiles = [
      { lbl: lab.revMonth, val: yen(revenue.month), gold: true },
      { lbl: lab.revTotal, val: yen(revenue.total), gold: true },
      { lbl: lab.bookings, val: num(totals.bookings) },
      { lbl: lab.customers, val: num(totals.customers) },
      { lbl: lab.subscribers, val: num(totals.subscribers) },
      { lbl: lab.avgRating, val: (Number(totals.avgRating) || 0).toFixed(1) + ' ★' }
    ];
    var h = '<div class="an-kpis">';
    tiles.forEach(function (t) {
      h += '<div class="an-tile"><div class="lbl">' + esc(t.lbl) + '</div>' +
        '<div class="val' + (t.gold ? ' gold' : '') + '">' + esc(t.val) + '</div></div>';
    });
    return h + '</div>';
  }

  function renderFunnel(funnel, lab) {
    funnel = funnel || {};
    var steps = [
      { label: lab.visits, val: Number(funnel.visit) || 0 },
      { label: lab.bookStart, val: Number(funnel.book_start) || 0 },
      { label: lab.bookSubmit, val: Number(funnel.book_submit) || 0 }
    ];
    var max = steps.reduce(function (m, s) { return Math.max(m, s.val); }, 0) || 1;
    var conv = Number(funnel.conversionPct) || 0;
    var rows = '';
    steps.forEach(function (s) {
      var pct = Math.round((s.val / max) * 100);
      rows += '<div class="an-frow">' +
        '<span class="an-flabel">' + esc(s.label) + '</span>' +
        '<span class="an-ftrack"><span class="an-fbar" style="width:' + pct + '%"></span></span>' +
        '<span class="an-fnum">' + esc(num(s.val)) + '</span>' +
        '</div>';
    });
    return '<div class="an-sec"><div class="an-h">' + esc(lab.funnel) + '</div>' +
      '<div class="an-fwrap">' +
        '<div class="an-funnel">' + rows + '</div>' +
        '<div class="an-conv"><div class="clbl">' + esc(lab.conversion) + '</div>' +
          '<div class="cval">' + esc(conv) + '%</div></div>' +
      '</div></div>';
  }

  function renderRevChart(revenue, lab) {
    revenue = revenue || {};
    var days = Array.isArray(revenue.last7) ? revenue.last7 : [];
    if (!days.length) {
      return '<div class="an-sec"><div class="an-h">' + esc(lab.last7) + ' · ' + esc(lab.revenue) + '</div>' +
        '<div class="an-empty">' + esc(lab.empty) + '</div></div>';
    }
    var max = days.reduce(function (m, d) { return Math.max(m, Number(d.val) || 0); }, 0) || 1;
    var cols = '';
    days.forEach(function (d) {
      var val = Number(d.val) || 0;
      var pct = Math.round((val / max) * 100);
      var dayNum = String(d.d || '').slice(8, 10) || String(d.d || '');
      cols += '<div class="an-col">' +
        '<div class="an-coltrack"><div class="an-colbar' + (val > 0 ? '' : ' zero') + '" style="height:' + pct + '%" title="' + esc(d.d) + ' · ' + esc(yen(val)) + '"></div></div>' +
        '<div class="an-colday">' + esc(dayNum) + '</div>' +
        '</div>';
    });
    return '<div class="an-sec"><div class="an-h">' + esc(lab.last7) + ' · ' + esc(lab.revenue) + '</div>' +
      '<div class="an-chart">' + cols + '</div></div>';
  }

  function renderTopPlans(byPlan, lab) {
    byPlan = Array.isArray(byPlan) ? byPlan : [];
    var inner;
    if (!byPlan.length) {
      inner = '<div class="an-empty">' + esc(lab.empty) + '</div>';
    } else {
      var rows = '';
      byPlan.forEach(function (p) {
        rows += '<tr>' +
          '<td class="plan">' + esc(p.name || p.plan || lab.dash) + '</td>' +
          '<td class="num">' + esc(num(p.count)) + '</td>' +
          '<td class="num rev">' + esc(yen(p.revenue)) + '</td>' +
          '</tr>';
      });
      inner = '<div class="an-scroll"><table class="an-tbl"><thead><tr>' +
        '<th>' + esc(lab.plan) + '</th>' +
        '<th class="num">' + esc(lab.count) + '</th>' +
        '<th class="num">' + esc(lab.revenue) + '</th>' +
        '</tr></thead><tbody>' + rows + '</tbody></table></div>';
    }
    return '<div class="an-sec"><div class="an-h">' + esc(lab.topPlans) + '</div>' + inner + '</div>';
  }

  function renderStatus(byStatus, lab) {
    byStatus = byStatus || {};
    var pillCls = (window.ALSCore && window.ALSCore.pillCls) ||
      { pending: 'warn', confirmed: 'ok', completed: 'info', declined: 'bad', cancelled: 'bad' };
    var order = ['pending', 'confirmed', 'completed', 'declined', 'cancelled'];
    var keys = order.filter(function (k) { return byStatus[k] != null; });
    // append any extra statuses the API may return
    Object.keys(byStatus).forEach(function (k) {
      if (keys.indexOf(k) === -1) keys.push(k);
    });
    var inner;
    if (!keys.length) {
      inner = '<div class="an-empty">' + esc(lab.empty) + '</div>';
    } else {
      var pills = '';
      keys.forEach(function (k) {
        var name = lab['st_' + k] || k;
        pills += '<span class="an-stat"><span class="pill ' + (pillCls[k] || 'dim') + '">' +
          esc(name) + '</span><span class="n">' + esc(num(byStatus[k])) + '</span></span>';
      });
      inner = '<div class="an-stats">' + pills + '</div>';
    }
    return '<div class="an-sec"><div class="an-h">' + esc(lab.status) + '</div>' + inner + '</div>';
  }

  function renderDashboard(data) {
    var lab = state.lab;
    var body = document.querySelector('#' + MODAL_ID + ' [data-an-body]');
    if (!body) return;
    var html =
      renderKpis(data.totals, data.revenue, lab) +
      renderFunnel(data.funnel, lab) +
      renderRevChart(data.revenue, lab) +
      renderTopPlans(data.byPlan, lab) +
      renderStatus(data.byStatus, lab);
    body.innerHTML = html;
  }

  /* -------- data + open -------- */
  function openModal() {
    injectStyles();
    var lab = labels();
    state.lab = lab;
    var m = buildModal();
    m.querySelector('[data-an-title]').textContent = lab.title;
    m.querySelector('[data-an-sub]').textContent = lab.sub;
    var body = m.querySelector('[data-an-body]');
    body.innerHTML = '<div class="an-empty">…</div>';
    m.classList.add('open');
    document.addEventListener('keydown', onKey);

    fetch('/api/analytics/dashboard', { credentials: 'include', headers: { 'Accept': 'application/json' } })
      .then(function (res) {
        if (res.status === 401 || res.status === 403) {
          closeModal();
          return null;
        }
        return res.json().catch(function () { return null; });
      })
      .then(function (data) {
        if (!isOpen()) return;
        if (!data || data.ok === false) {
          if (body) body.innerHTML = '<div class="an-empty">' + esc(lab.empty) + '</div>';
          return;
        }
        try { renderDashboard(data); }
        catch (err) { if (body) body.innerHTML = '<div class="an-empty">' + esc(lab.empty) + '</div>'; }
      })
      .catch(function () {
        if (isOpen() && body) body.innerHTML = '<div class="an-empty">' + esc(lab.empty) + '</div>';
      });
  }

  /* -------- bind -------- */
  function bind() {
    var btn = document.getElementById('admAnalytics');
    if (!btn || btn.__alsBound) return; // no-op if absent
    btn.__alsBound = true;
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      try { openModal(); } catch (err) { /* never throw */ }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bind);
  } else {
    bind();
  }
})();
