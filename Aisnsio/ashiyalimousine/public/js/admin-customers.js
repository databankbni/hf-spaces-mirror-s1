/* admin-customers.js — Customer Directory for the Ashiya Limousine staff dashboard.
   Self-contained browser module. Loads after the main inline script via
   <script src="/js/admin-customers.js" defer></script>. Binds to #admCustomers,
   opens a modal listing every customer with full contact info, booking count,
   total spend and last booking date. Search + CSV export. Bilingual EN/JA.
   Reuses window.ALSCore + the site's CSS variables/design tokens. No frameworks. */
(function () {
  'use strict';
  if (window.__alsCustomersInit) return;
  window.__alsCustomersInit = true;

  var STYLE_ID = 'als-customers-style';
  var MODAL_ID = 'alsCustomersModal';

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
      ? { title: '顧客ディレクトリ', sub: '', customer: '顧客', contact: '連絡先',
          bookings: '予約数', spend: '利用額', last: '最終予約', search: '検索',
          csv: 'CSV出力', account: 'アカウント', guest: 'ゲスト', empty: '顧客が見つかりません', dash: '—' }
      : { title: 'Customer directory', sub: '', customer: 'Customer', contact: 'Contact',
          bookings: 'Bookings', spend: 'Spend', last: 'Last', search: 'Search',
          csv: 'Export CSV', account: 'Account', guest: 'Guest', empty: 'No customers found', dash: '—' };
  }

  function yen(n) {
    var v = Number(n);
    if (!isFinite(v)) v = 0;
    return '¥' + Math.round(v).toLocaleString('ja-JP');
  }

  /* -------- styles -------- */
  function injectStyles() {
    if (document.getElementById(STYLE_ID)) return;
    var css =
      '#' + MODAL_ID + ' .modal{max-width:860px;text-align:left}' +
      '#' + MODAL_ID + ' h3{text-align:left}' +
      '#' + MODAL_ID + ' .cust-head{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:2px 0 16px}' +
      '#' + MODAL_ID + ' .cust-head .grow{flex:1 1 200px}' +
      '#' + MODAL_ID + ' .cust-search{width:100%;background:var(--panel);border:1px solid var(--line);' +
        'border-radius:10px;padding:10px 13px;color:var(--cream);font-family:var(--sans);font-size:13px;outline:none}' +
      '#' + MODAL_ID + ' .cust-search:focus{border-color:var(--gold)}' +
      '#' + MODAL_ID + ' .cust-scroll{overflow-x:auto;border:1px solid var(--hair);border-radius:12px}' +
      '#' + MODAL_ID + ' table.cust-tbl{width:100%;border-collapse:collapse;min-width:640px;font-size:13px}' +
      '#' + MODAL_ID + ' .cust-tbl th{font-family:var(--mono);font-size:9.5px;letter-spacing:.16em;' +
        'text-transform:uppercase;color:var(--faint);text-align:left;padding:11px 14px;border-bottom:1px solid var(--hair);white-space:nowrap;background:rgba(255,255,255,.02)}' +
      '#' + MODAL_ID + ' .cust-tbl td{padding:11px 14px;border-bottom:1px solid var(--hair);color:var(--cream);vertical-align:top}' +
      '#' + MODAL_ID + ' .cust-tbl tr:last-child td{border-bottom:none}' +
      '#' + MODAL_ID + ' .cust-tbl tr:hover td{background:rgba(212,175,55,.05)}' +
      '#' + MODAL_ID + ' .cust-name{font-family:var(--serif);font-size:16px;color:var(--cream);display:flex;align-items:center;gap:8px;flex-wrap:wrap}' +
      '#' + MODAL_ID + ' .cust-contact{color:var(--muted);font-size:12px;line-height:1.7}' +
      '#' + MODAL_ID + ' .cust-contact a{color:var(--gold2)}' +
      '#' + MODAL_ID + ' .cust-contact a:hover{color:var(--gold)}' +
      '#' + MODAL_ID + ' .cust-num{font-family:var(--mono);font-size:13px;color:var(--cream);text-align:right;white-space:nowrap}' +
      '#' + MODAL_ID + ' .cust-spend{color:var(--gold2)}' +
      '#' + MODAL_ID + ' th.num,#' + MODAL_ID + ' td.num{text-align:right}' +
      '#' + MODAL_ID + ' .cust-empty{padding:30px 14px;text-align:center;color:var(--muted);font-size:13px}' +
      '#' + MODAL_ID + ' .cust-count{font-family:var(--mono);font-size:11px;color:var(--faint);letter-spacing:.1em}';
    var s = document.createElement('style');
    s.id = STYLE_ID;
    s.textContent = css;
    document.head.appendChild(s);
  }

  /* -------- modal shell -------- */
  var state = { rows: [], filtered: [], lab: null };

  function buildModal() {
    var existing = document.getElementById(MODAL_ID);
    if (existing) return existing;
    var wrap = document.createElement('div');
    wrap.className = 'modal-bg';
    wrap.id = MODAL_ID;
    wrap.innerHTML =
      '<div class="modal" role="dialog" aria-modal="true">' +
        '<button class="x" type="button" data-cust-close aria-label="close">' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>' +
        '</button>' +
        '<h3 data-cust-title></h3>' +
        '<div class="cust-head">' +
          '<div class="grow"><input type="search" class="cust-search" data-cust-search autocomplete="off"></div>' +
          '<span class="cust-count" data-cust-count></span>' +
          '<button class="btn btn-dim btn-sm" type="button" data-cust-csv>' +
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px"><path d="M12 4v11m0 0 4.5-4.5M12 15l-4.5-4.5"/><path d="M4 19h16"/></svg>' +
            '<span data-cust-csv-label></span>' +
          '</button>' +
        '</div>' +
        '<div class="cust-scroll"><div data-cust-body></div></div>' +
      '</div>';
    document.body.appendChild(wrap);

    // close: X button + backdrop click
    wrap.addEventListener('click', function (e) {
      if (e.target === wrap || (e.target.closest && e.target.closest('[data-cust-close]'))) {
        closeModal();
      }
    });
    wrap.querySelector('[data-cust-search]').addEventListener('input', function (e) {
      applyFilter(e.target.value);
    });
    wrap.querySelector('[data-cust-csv]').addEventListener('click', exportCSV);
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

  /* -------- rendering -------- */
  function chip(source, lab) {
    if (source === 'account') return '<span class="pill info">' + esc(lab.account) + '</span>';
    return '<span class="pill dim">' + esc(lab.guest) + '</span>';
  }

  function contactCell(c, lab) {
    var lines = [];
    if (c.phone) lines.push('<a href="tel:' + esc(String(c.phone).replace(/[^+0-9]/g, '')) + '">' + esc(c.phone) + '</a>');
    else lines.push(esc(lab.dash));
    if (c.email) lines.push('<a href="mailto:' + esc(c.email) + '">' + esc(c.email) + '</a>');
    else lines.push(esc(lab.dash));
    lines.push(c.line_id ? 'LINE ' + esc(c.line_id) : esc(lab.dash));
    return '<div class="cust-contact">' + lines.join('<br>') + '</div>';
  }

  function renderBody() {
    var lab = state.lab;
    var body = document.querySelector('#' + MODAL_ID + ' [data-cust-body]');
    var count = document.querySelector('#' + MODAL_ID + ' [data-cust-count]');
    if (!body) return;
    if (count) count.textContent = state.filtered.length + ' / ' + state.rows.length;
    if (!state.filtered.length) {
      body.innerHTML = '<div class="cust-empty">' + esc(lab.empty) + '</div>';
      return;
    }
    var h = '<table class="cust-tbl"><thead><tr>' +
      '<th>' + esc(lab.customer) + '</th>' +
      '<th>' + esc(lab.contact) + '</th>' +
      '<th class="num">' + esc(lab.bookings) + '</th>' +
      '<th class="num">' + esc(lab.spend) + '</th>' +
      '<th>' + esc(lab.last) + '</th>' +
      '</tr></thead><tbody>';
    state.filtered.forEach(function (c) {
      h += '<tr>' +
        '<td><div class="cust-name">' + esc(c.name || lab.dash) + chip(c.source, lab) + '</div></td>' +
        '<td>' + contactCell(c, lab) + '</td>' +
        '<td class="num cust-num">' + esc(Number(c.bookingCount || 0)) + '</td>' +
        '<td class="num cust-num cust-spend">' + yen(c.spend) + '</td>' +
        '<td>' + (c.lastDate ? esc(c.lastDate) : esc(lab.dash)) + '</td>' +
        '</tr>';
    });
    h += '</tbody></table>';
    body.innerHTML = h;
  }

  function applyFilter(q) {
    var t = String(q || '').trim().toLowerCase();
    if (!t) {
      state.filtered = state.rows.slice();
    } else {
      state.filtered = state.rows.filter(function (c) {
        return [c.name, c.phone, c.email, c.line_id].some(function (f) {
          return f && String(f).toLowerCase().indexOf(t) !== -1;
        });
      });
    }
    renderBody();
  }

  /* -------- CSV export -------- */
  function csvField(v) {
    return '"' + String(v == null ? '' : v).replace(/"/g, '""') + '"';
  }

  function exportCSV() {
    var header = ['name', 'email', 'phone', 'line_id', 'source', 'bookings', 'spend_jpy', 'last_date'];
    var lines = [header.map(csvField).join(',')];
    state.filtered.forEach(function (c) {
      lines.push([
        csvField(c.name), csvField(c.email), csvField(c.phone), csvField(c.line_id),
        csvField(c.source), csvField(Number(c.bookingCount || 0)),
        csvField(Math.round(Number(c.spend) || 0)), csvField(c.lastDate)
      ].join(','));
    });
    var csv = '﻿' + lines.join('\r\n');
    var blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = 'ashiya-limousine-customers.csv';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 1500);
  }

  /* -------- data + open -------- */
  function openModal() {
    injectStyles();
    var lab = labels();
    state.lab = lab;
    var m = buildModal();
    m.querySelector('[data-cust-title]').textContent = lab.title;
    m.querySelector('[data-cust-search]').placeholder = lab.search;
    m.querySelector('[data-cust-search]').value = '';
    m.querySelector('[data-cust-csv-label]').textContent = lab.csv;
    var body = m.querySelector('[data-cust-body]');
    body.innerHTML = '<div class="cust-empty">…</div>';
    m.classList.add('open');
    document.addEventListener('keydown', onKey);

    fetch('/api/admin/customers', { credentials: 'include', headers: { 'Accept': 'application/json' } })
      .then(function (res) {
        if (res.status === 401 || res.status === 403) {
          closeModal();
          return null;
        }
        return res.json().catch(function () { return null; });
      })
      .then(function (data) {
        if (!document.getElementById(MODAL_ID) || !document.getElementById(MODAL_ID).classList.contains('open')) return;
        var rows = (data && data.ok && Array.isArray(data.customers)) ? data.customers.slice() : [];
        rows.sort(function (a, b) { return (Number(b.spend) || 0) - (Number(a.spend) || 0); });
        state.rows = rows;
        state.filtered = rows.slice();
        renderBody();
      })
      .catch(function () {
        if (state.lab) {
          var b = document.querySelector('#' + MODAL_ID + ' [data-cust-body]');
          if (b) b.innerHTML = '<div class="cust-empty">' + esc(state.lab.empty) + '</div>';
        }
      });
  }

  /* -------- bind -------- */
  function bind() {
    var btn = document.getElementById('admCustomers');
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
