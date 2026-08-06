/* admin-leads.js — Leads (見込み客) manager for the Ashiya Limousine staff dashboard.
   Self-contained browser module. Loads after the main inline script via
   <script src="/js/admin-leads.js" defer></script>. Binds to #admLeads, opens a
   modal listing every captured lead (quote request) with contact, plan/date/pax,
   quote total, status pill + status changer, and per-row delete. Bilingual EN/JA.
   Reuses window.ALSCore + the site's CSS variables/design tokens. No frameworks. */
(function () {
  'use strict';
  if (window.__alsLeadsInit) return;
  window.__alsLeadsInit = true;

  var STYLE_ID = 'als-leads-style';
  var MODAL_ID = 'alsLeadsModal';
  var STATUSES = ['new', 'contacted', 'converted', 'closed'];

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
    var ja = isJA();
    return ja
      ? { title: '見込み客', when: '受信', customer: '顧客', trip: 'プラン・日程',
          quote: '見積', status: '状態', actions: '操作', delete: '削除',
          empty: '見込み客がありません', dash: '—', pax: '名', del_confirm: 'この見込み客を削除しますか？',
          st: { 'new': '新規', contacted: '連絡済', converted: '成約', closed: 'クローズ' } }
      : { title: 'Leads', when: 'Received', customer: 'Customer', trip: 'Plan / Date',
          quote: 'Quote', status: 'Status', actions: 'Actions', delete: 'Delete',
          empty: 'No leads yet', dash: '—', pax: 'pax', del_confirm: 'Delete this lead?',
          st: { 'new': 'New', contacted: 'Contacted', converted: 'Converted', closed: 'Closed' } };
  }

  function yen(n) {
    var v = Number(n);
    if (!isFinite(v)) v = 0;
    return '¥' + Math.round(v).toLocaleString('ja-JP');
  }

  function pillClass(status) {
    switch (String(status || 'new')) {
      case 'contacted': return 'info';
      case 'converted': return 'ok';
      case 'closed': return 'bad';
      default: return 'warn'; // new
    }
  }

  // Format an ISO-ish timestamp into a short local date+time; fall back to raw string.
  function fmtDate(v) {
    if (!v) return '';
    var d = new Date(v);
    if (isNaN(d.getTime())) return String(v);
    var pad = function (x) { return (x < 10 ? '0' : '') + x; };
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
      ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }

  // selection may be an object or a JSON string; return its .message if present.
  function selectionMessage(selection) {
    var s = selection;
    if (!s) return '';
    if (typeof s === 'string') {
      try { s = JSON.parse(s); } catch (e) { return ''; }
    }
    if (s && typeof s === 'object' && s.message) return String(s.message);
    return '';
  }

  /* -------- api wrapper -------- */
  // Resolves to parsed JSON (or null). Closes the modal on auth failure. Never throws.
  function api(method, url, body) {
    var opts = {
      method: method,
      credentials: 'include',
      headers: { 'Accept': 'application/json' }
    };
    if (body != null) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    return fetch(url, opts).then(function (res) {
      if (res.status === 401 || res.status === 403) {
        closeModal();
        return null;
      }
      if (!res.ok) return null;
      return res.json().catch(function () { return null; });
    }).catch(function () { return null; });
  }

  /* -------- styles -------- */
  function injectStyles() {
    if (document.getElementById(STYLE_ID)) return;
    var css =
      '#' + MODAL_ID + ' .modal{max-width:900px;text-align:left}' +
      '#' + MODAL_ID + ' h3{text-align:left}' +
      '#' + MODAL_ID + ' .lead-head{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:2px 0 16px}' +
      '#' + MODAL_ID + ' .lead-head .grow{flex:1 1 auto}' +
      '#' + MODAL_ID + ' .lead-scroll{overflow-x:auto;border:1px solid var(--hair);border-radius:12px}' +
      '#' + MODAL_ID + ' table.lead-tbl{width:100%;border-collapse:collapse;min-width:720px;font-size:13px}' +
      '#' + MODAL_ID + ' .lead-tbl th{font-family:var(--mono);font-size:9.5px;letter-spacing:.16em;' +
        'text-transform:uppercase;color:var(--faint);text-align:left;padding:11px 14px;border-bottom:1px solid var(--hair);white-space:nowrap;background:rgba(255,255,255,.02)}' +
      '#' + MODAL_ID + ' .lead-tbl td{padding:11px 14px;border-bottom:1px solid var(--hair);color:var(--cream);vertical-align:top}' +
      '#' + MODAL_ID + ' .lead-tbl tr:last-child td{border-bottom:none}' +
      '#' + MODAL_ID + ' .lead-tbl tr:hover td{background:rgba(212,175,55,.05)}' +
      '#' + MODAL_ID + ' .lead-when{font-family:var(--mono);font-size:11px;color:var(--muted);white-space:nowrap}' +
      '#' + MODAL_ID + ' .lead-name{font-family:var(--serif);font-size:15px;color:var(--cream)}' +
      '#' + MODAL_ID + ' .lead-contact{color:var(--muted);font-size:12px;line-height:1.7}' +
      '#' + MODAL_ID + ' .lead-contact a{color:var(--gold2)}' +
      '#' + MODAL_ID + ' .lead-contact a:hover{color:var(--gold)}' +
      '#' + MODAL_ID + ' .lead-trip{font-size:12.5px;color:var(--cream);line-height:1.6}' +
      '#' + MODAL_ID + ' .lead-trip .sub{color:var(--muted);font-size:11.5px}' +
      '#' + MODAL_ID + ' .lead-msg{color:var(--faint);font-size:11.5px;font-style:italic;margin-top:4px;max-width:240px;line-height:1.5}' +
      '#' + MODAL_ID + ' .lead-quote{font-family:var(--mono);font-size:13px;color:var(--gold2);text-align:right;white-space:nowrap}' +
      '#' + MODAL_ID + ' th.num,#' + MODAL_ID + ' td.num{text-align:right}' +
      '#' + MODAL_ID + ' .lead-sel{background:var(--panel);border:1px solid var(--line);border-radius:8px;' +
        'padding:6px 9px;color:var(--cream);font-family:var(--sans);font-size:12px;outline:none;cursor:pointer;margin-top:7px;width:100%}' +
      '#' + MODAL_ID + ' .lead-sel:focus{border-color:var(--gold)}' +
      '#' + MODAL_ID + ' .lead-del{background:transparent;border:1px solid var(--line);border-radius:8px;color:var(--muted);' +
        'font-family:var(--sans);font-size:11.5px;padding:6px 11px;cursor:pointer;white-space:nowrap;transition:.15s}' +
      '#' + MODAL_ID + ' .lead-del:hover{border-color:var(--bad,#d66);color:var(--bad,#d66)}' +
      '#' + MODAL_ID + ' .lead-empty{padding:34px 14px;text-align:center;color:var(--muted);font-size:13px}' +
      '#' + MODAL_ID + ' .lead-count{font-family:var(--mono);font-size:11px;color:var(--faint);letter-spacing:.1em}';
    var s = document.createElement('style');
    s.id = STYLE_ID;
    s.textContent = css;
    document.head.appendChild(s);
  }

  /* -------- modal shell -------- */
  var state = { rows: [], lab: null };

  function buildModal() {
    var existing = document.getElementById(MODAL_ID);
    if (existing) return existing;
    var wrap = document.createElement('div');
    wrap.className = 'modal-bg';
    wrap.id = MODAL_ID;
    wrap.innerHTML =
      '<div class="modal" role="dialog" aria-modal="true">' +
        '<button class="x" type="button" data-lead-close aria-label="close">' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>' +
        '</button>' +
        '<h3 data-lead-title></h3>' +
        '<div class="lead-head">' +
          '<span class="grow"></span>' +
          '<span class="lead-count" data-lead-count></span>' +
        '</div>' +
        '<div class="lead-scroll"><div data-lead-body></div></div>' +
      '</div>';
    document.body.appendChild(wrap);

    // close: X button + backdrop click
    wrap.addEventListener('click', function (e) {
      if (e.target === wrap || (e.target.closest && e.target.closest('[data-lead-close]'))) {
        closeModal();
      }
    });
    // status change (event delegation)
    wrap.addEventListener('change', function (e) {
      var sel = e.target.closest && e.target.closest('[data-lead-status]');
      if (sel) onStatusChange(sel);
    });
    // delete (event delegation)
    wrap.addEventListener('click', function (e) {
      var del = e.target.closest && e.target.closest('[data-lead-del]');
      if (del) onDelete(del);
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

  /* -------- rendering -------- */
  function contactCell(lead, lab) {
    var lines = [];
    lines.push('<div class="lead-name">' + esc(lead.name || lab.dash) + '</div>');
    if (lead.email) {
      lines.push('<a href="mailto:' + esc(lead.email) + '">' + esc(lead.email) + '</a>');
    }
    return '<div class="lead-contact">' + lines.join('') + '</div>';
  }

  function tripCell(lead, lab) {
    var top = [];
    if (lead.plan) top.push(esc(lead.plan));
    var sub = [];
    if (lead.date) sub.push(esc(lead.date) + (lead.time ? ' ' + esc(lead.time) : ''));
    if (lead.pax != null && lead.pax !== '') sub.push(esc(lead.pax) + ' ' + esc(lab.pax));
    var msg = selectionMessage(lead.selection);
    var h = '<div class="lead-trip">';
    h += top.length ? top.join(' · ') : esc(lab.dash);
    if (sub.length) h += '<div class="sub">' + sub.join(' · ') + '</div>';
    h += '</div>';
    if (msg) h += '<div class="lead-msg">' + esc(msg) + '</div>';
    return h;
  }

  function statusSelect(lead, lab) {
    var cur = String(lead.status || 'new');
    var h = '<select class="lead-sel" data-lead-status data-id="' + esc(lead.id) + '">';
    STATUSES.forEach(function (s) {
      h += '<option value="' + esc(s) + '"' + (s === cur ? ' selected' : '') + '>' +
        esc(lab.st[s] || s) + '</option>';
    });
    h += '</select>';
    return h;
  }

  function renderBody() {
    var lab = state.lab;
    var body = document.querySelector('#' + MODAL_ID + ' [data-lead-body]');
    var count = document.querySelector('#' + MODAL_ID + ' [data-lead-count]');
    if (!body) return;
    if (count) count.textContent = String(state.rows.length);
    if (!state.rows.length) {
      body.innerHTML = '<div class="lead-empty">' + esc(lab.empty) + '</div>';
      return;
    }
    var h = '<table class="lead-tbl"><thead><tr>' +
      '<th>' + esc(lab.when) + '</th>' +
      '<th>' + esc(lab.customer) + '</th>' +
      '<th>' + esc(lab.trip) + '</th>' +
      '<th class="num">' + esc(lab.quote) + '</th>' +
      '<th>' + esc(lab.status) + '</th>' +
      '<th>' + esc(lab.actions) + '</th>' +
      '</tr></thead><tbody>';
    state.rows.forEach(function (lead) {
      var cls = pillClass(lead.status);
      var stLabel = lab.st[String(lead.status || 'new')] || String(lead.status || 'new');
      h += '<tr>' +
        '<td><span class="lead-when">' + esc(fmtDate(lead.created_at)) + '</span></td>' +
        '<td>' + contactCell(lead, lab) + '</td>' +
        '<td>' + tripCell(lead, lab) + '</td>' +
        '<td class="num lead-quote">' + yen(lead.quote_total) + '</td>' +
        '<td>' +
          '<span class="pill ' + cls + '">' + esc(stLabel) + '</span>' +
          statusSelect(lead, lab) +
        '</td>' +
        '<td><button type="button" class="lead-del" data-lead-del data-id="' + esc(lead.id) + '">' +
          esc(lab.delete) + '</button></td>' +
        '</tr>';
    });
    h += '</tbody></table>';
    body.innerHTML = h;
  }

  /* -------- actions -------- */
  function onStatusChange(sel) {
    var id = sel.getAttribute('data-id');
    var status = sel.value;
    if (!id || STATUSES.indexOf(status) === -1) return;
    sel.disabled = true;
    api('POST', '/api/leads/admin/' + encodeURIComponent(id) + '/status', { status: status })
      .then(function () {
        if (isOpen()) load();
      });
  }

  function onDelete(btn) {
    var id = btn.getAttribute('data-id');
    if (!id) return;
    var lab = state.lab || labels();
    if (!window.confirm(lab.del_confirm)) return;
    btn.disabled = true;
    api('DELETE', '/api/leads/admin/' + encodeURIComponent(id))
      .then(function () {
        if (isOpen()) load();
      });
  }

  /* -------- data -------- */
  function load() {
    api('GET', '/api/leads/admin').then(function (data) {
      if (!isOpen()) return;
      var rows = (data && Array.isArray(data.leads)) ? data.leads.slice() : [];
      rows.sort(function (a, b) {
        return new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime();
      });
      state.rows = rows;
      renderBody();
    });
  }

  /* -------- open -------- */
  function openModal() {
    injectStyles();
    var lab = labels();
    state.lab = lab;
    var m = buildModal();
    m.querySelector('[data-lead-title]').textContent = lab.title;
    var body = m.querySelector('[data-lead-body]');
    body.innerHTML = '<div class="lead-empty">…</div>';
    m.classList.add('open');
    document.addEventListener('keydown', onKey);
    load();
  }

  /* -------- bind -------- */
  function bind() {
    var btn = document.getElementById('admLeads');
    if (!btn || btn.__alsLeadsBound) return; // no-op if absent
    btn.__alsLeadsBound = true;
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
