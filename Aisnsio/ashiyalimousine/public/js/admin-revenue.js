/* admin-revenue.js — Revenue & offers console for the Ashiya Limousine staff dashboard.
   Self-contained browser module. Loads after the main inline script via
   <script src="/js/admin-revenue.js" defer></script>. Binds to #admRevenue, opens a
   modal with 4 tabs: Coupons (promo codes CRUD), Gift cards, Waitlist, Rate rules.
   Reuses window.ALSCore + the site's CSS variables/design tokens. Bilingual EN/JA.
   No frameworks. Any fetch returning 401/403 closes the modal (session expired). */
(function () {
  'use strict';
  if (window.__alsRevenueInit) return;
  window.__alsRevenueInit = true;

  var STYLE_ID = 'als-revenue-style';
  var MODAL_ID = 'alsRevenueModal';

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

  function yen(n) {
    var v = Number(n);
    if (!isFinite(v)) v = 0;
    return '¥' + Math.round(v).toLocaleString('ja-JP');
  }

  var INF = '∞'; // ∞

  function labels() {
    return isJA()
      ? {
          title: '売上・特典コンソール', dash: '—', loading: '読み込み中…',
          tabCoupons: 'クーポン', tabGifts: 'ギフト券', tabWait: 'ウェイトリスト', tabRules: 'レート規則',
          // coupons
          code: 'コード', type: '種別', minSpend: '最低利用額', uses: '利用回数', expires: '有効期限',
          active: '有効', actions: '操作', createCoupon: 'クーポンを作成', noExpiry: '無期限',
          on: 'ON', off: 'OFF', del: '削除', create: '作成', amount: '金額',
          kindPct: '割合(%)', kindFixed: '定額(¥)', codeTaken: 'このコードは使用済みです',
          emptyCoupons: 'クーポンがありません', confirmDel: 'このクーポンを削除しますか？',
          phCode: 'コード', phAmount: '値', phMin: '最低額', phMax: '上限(0=∞)',
          // gifts
          initial: '初期額', balance: '残高', status: 'ステータス', pay: '支払', parties: '購入者→受取人',
          markPaid: '支払済にする', paid: '支払済', unpaid: '未払い', emptyGifts: 'ギフト券がありません',
          // waitlist
          name: '氏名', contact: '連絡先', details: 'プラン/日時/人数', pax: '名', emptyWait: 'ウェイトリストは空です',
          stWaiting: '待機中', stOffered: 'オファー済', stConverted: '成約', stClosed: 'クローズ',
          // rules
          label: '名称', summary: '条件', emptyRules: 'レート規則がありません'
        }
      : {
          title: 'Revenue & offers', dash: '—', loading: 'Loading…',
          tabCoupons: 'Coupons', tabGifts: 'Gift cards', tabWait: 'Waitlist', tabRules: 'Rate rules',
          code: 'Code', type: 'Type', minSpend: 'Min spend', uses: 'Uses', expires: 'Expires',
          active: 'Active', actions: 'Actions', createCoupon: 'Create coupon', noExpiry: 'No expiry',
          on: 'On', off: 'Off', del: 'Delete', create: 'Create', amount: 'Amount',
          kindPct: 'Percent (%)', kindFixed: 'Fixed (¥)', codeTaken: 'Code taken',
          emptyCoupons: 'No coupons yet', confirmDel: 'Delete this coupon?',
          phCode: 'CODE', phAmount: 'Value', phMin: 'Min', phMax: 'Max (0=∞)',
          initial: 'Initial', balance: 'Balance', status: 'Status', pay: 'Payment', parties: 'Purchaser → Recipient',
          markPaid: 'Mark paid', paid: 'Paid', unpaid: 'Unpaid', emptyGifts: 'No gift cards yet',
          name: 'Name', contact: 'Contact', details: 'Plan / date / time / pax', pax: 'pax', emptyWait: 'Waitlist is empty',
          stWaiting: 'Waiting', stOffered: 'Offered', stConverted: 'Converted', stClosed: 'Closed',
          label: 'Label', summary: 'Conditions', emptyRules: 'No rate rules'
        };
  }

  /* -------- styles -------- */
  function injectStyles() {
    if (document.getElementById(STYLE_ID)) return;
    var css =
      '#' + MODAL_ID + ' .modal{max-width:880px;text-align:left}' +
      '#' + MODAL_ID + ' h3{text-align:left}' +
      '#' + MODAL_ID + ' .rev-tabs{display:flex;gap:6px;flex-wrap:wrap;margin:2px 0 16px;border-bottom:1px solid var(--hair)}' +
      '#' + MODAL_ID + ' .rev-tab{appearance:none;background:none;border:none;border-bottom:2px solid transparent;' +
        'color:var(--muted);font-family:var(--mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;' +
        'padding:9px 12px;cursor:pointer;margin-bottom:-1px}' +
      '#' + MODAL_ID + ' .rev-tab:hover{color:var(--cream)}' +
      '#' + MODAL_ID + ' .rev-tab.on{color:var(--gold2);border-bottom-color:var(--gold)}' +
      '#' + MODAL_ID + ' .rev-scroll{overflow-x:auto;border:1px solid var(--hair);border-radius:12px}' +
      '#' + MODAL_ID + ' table.rev-tbl{width:100%;border-collapse:collapse;min-width:640px;font-size:13px}' +
      '#' + MODAL_ID + ' .rev-tbl th{font-family:var(--mono);font-size:9.5px;letter-spacing:.16em;text-transform:uppercase;' +
        'color:var(--faint);text-align:left;padding:10px 13px;border-bottom:1px solid var(--hair);white-space:nowrap;background:rgba(255,255,255,.02)}' +
      '#' + MODAL_ID + ' .rev-tbl td{padding:10px 13px;border-bottom:1px solid var(--hair);color:var(--cream);vertical-align:middle}' +
      '#' + MODAL_ID + ' .rev-tbl tr:last-child td{border-bottom:none}' +
      '#' + MODAL_ID + ' .rev-tbl tr:hover td{background:rgba(212,175,55,.05)}' +
      '#' + MODAL_ID + ' .rev-code{font-family:var(--mono);font-size:13px;color:var(--gold2);letter-spacing:.06em}' +
      '#' + MODAL_ID + ' .rev-num{font-family:var(--mono);white-space:nowrap}' +
      '#' + MODAL_ID + ' .rev-sub{color:var(--muted);font-size:11px;line-height:1.6}' +
      '#' + MODAL_ID + ' .rev-sub a{color:var(--gold2)}' +
      '#' + MODAL_ID + ' .rev-empty{padding:28px 14px;text-align:center;color:var(--muted);font-size:13px}' +
      '#' + MODAL_ID + ' .rev-actions{display:flex;gap:6px;flex-wrap:wrap;align-items:center}' +
      '#' + MODAL_ID + ' .rev-msg{color:var(--bad);font-size:12px;margin:8px 0 0;min-height:16px;font-family:var(--sans)}' +
      '#' + MODAL_ID + ' .rev-form{display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;margin:14px 0 4px;' +
        'padding:14px;border:1px solid var(--hair);border-radius:12px;background:rgba(255,255,255,.02)}' +
      '#' + MODAL_ID + ' .rev-fld{display:flex;flex-direction:column;gap:4px}' +
      '#' + MODAL_ID + ' .rev-fld label{font-family:var(--mono);font-size:8.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--faint)}' +
      '#' + MODAL_ID + ' .rev-in,#' + MODAL_ID + ' .rev-sel{background:var(--panel);border:1px solid var(--line);border-radius:9px;' +
        'padding:8px 10px;color:var(--cream);font-family:var(--sans);font-size:13px;outline:none}' +
      '#' + MODAL_ID + ' .rev-in:focus,#' + MODAL_ID + ' .rev-sel:focus{border-color:var(--gold)}' +
      '#' + MODAL_ID + ' .rev-in.w-code{width:120px}#' + MODAL_ID + ' .rev-in.w-num{width:92px}' +
      '#' + MODAL_ID + ' .rev-st-sel{background:var(--panel);border:1px solid var(--line);border-radius:8px;' +
        'padding:5px 8px;color:var(--cream);font-family:var(--sans);font-size:12px;outline:none}' +
      '#' + MODAL_ID + ' .rev-st-sel:focus{border-color:var(--gold)}';
    var s = document.createElement('style');
    s.id = STYLE_ID;
    s.textContent = css;
    document.head.appendChild(s);
  }

  /* -------- state + shell -------- */
  var state = { tab: 'coupons', lab: null, busy: false };

  function buildModal() {
    var existing = document.getElementById(MODAL_ID);
    if (existing) return existing;
    var wrap = document.createElement('div');
    wrap.className = 'modal-bg';
    wrap.id = MODAL_ID;
    wrap.innerHTML =
      '<div class="modal" role="dialog" aria-modal="true">' +
        '<button class="x" type="button" data-rev-close aria-label="close">' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>' +
        '</button>' +
        '<h3 data-rev-title></h3>' +
        '<div class="rev-tabs" data-rev-tabs></div>' +
        '<div data-rev-body></div>' +
      '</div>';
    document.body.appendChild(wrap);

    wrap.addEventListener('click', function (e) {
      if (e.target === wrap || (e.target.closest && e.target.closest('[data-rev-close]'))) {
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

  function body() {
    return document.querySelector('#' + MODAL_ID + ' [data-rev-body]');
  }

  /* -------- fetch wrapper: closes modal on 401/403 -------- */
  function api(url, opts) {
    opts = opts || {};
    opts.credentials = 'include';
    opts.headers = opts.headers || {};
    if (!opts.headers.Accept) opts.headers.Accept = 'application/json';
    return fetch(url, opts).then(function (res) {
      if (res.status === 401 || res.status === 403) {
        closeModal();
        var e = new Error('unauthorized');
        e.__auth = true;
        throw e;
      }
      return res;
    });
  }

  function jsonOf(res) {
    return res.json().catch(function () { return null; });
  }

  /* -------- tabs -------- */
  var TABS = ['coupons', 'gifts', 'waitlist', 'rules'];

  function renderTabs() {
    var lab = state.lab;
    var names = { coupons: lab.tabCoupons, gifts: lab.tabGifts, waitlist: lab.tabWait, rules: lab.tabRules };
    var host = document.querySelector('#' + MODAL_ID + ' [data-rev-tabs]');
    if (!host) return;
    host.innerHTML = TABS.map(function (t) {
      return '<button type="button" class="rev-tab' + (state.tab === t ? ' on' : '') + '" data-rev-tab="' + t + '">' + esc(names[t]) + '</button>';
    }).join('');
    Array.prototype.forEach.call(host.querySelectorAll('[data-rev-tab]'), function (b) {
      b.addEventListener('click', function () {
        state.tab = b.getAttribute('data-rev-tab');
        renderTabs();
        loadTab();
      });
    });
  }

  function setLoading() {
    var b = body();
    if (b) b.innerHTML = '<div class="rev-scroll"><div class="rev-empty">' + esc(state.lab.loading) + '</div></div>';
  }

  function loadTab() {
    setLoading();
    if (state.tab === 'coupons') return loadCoupons();
    if (state.tab === 'gifts') return loadGifts();
    if (state.tab === 'waitlist') return loadWaitlist();
    if (state.tab === 'rules') return loadRules();
  }

  function guarded(fn) {
    return function (err) {
      if (err && err.__auth) return; // modal already closed
      if (!isOpen()) return;
      fn();
    };
  }

  /* ===================== TAB 1: COUPONS ===================== */
  function loadCoupons() {
    api('/api/promos/admin')
      .then(jsonOf)
      .then(function (data) {
        if (!isOpen() || state.tab !== 'coupons') return;
        var rows = (data && Array.isArray(data.coupons)) ? data.coupons : [];
        renderCoupons(rows);
      })
      .catch(guarded(function () { renderCoupons([]); }));
  }

  function couponTypeText(c) {
    return c.kind === 'pct' ? (Number(c.amount) || 0) + '%' : yen(c.amount);
  }

  function renderCoupons(rows) {
    var lab = state.lab, b = body();
    if (!b) return;
    var h = renderCouponForm();
    h += '<div class="rev-msg" data-rev-cmsg></div>';
    if (!rows.length) {
      h += '<div class="rev-scroll"><div class="rev-empty">' + esc(lab.emptyCoupons) + '</div></div>';
      b.innerHTML = h;
      bindCouponForm();
      return;
    }
    h += '<div class="rev-scroll"><table class="rev-tbl"><thead><tr>' +
      '<th>' + esc(lab.code) + '</th>' +
      '<th>' + esc(lab.type) + '</th>' +
      '<th>' + esc(lab.minSpend) + '</th>' +
      '<th>' + esc(lab.uses) + '</th>' +
      '<th>' + esc(lab.expires) + '</th>' +
      '<th>' + esc(lab.active) + '</th>' +
      '<th>' + esc(lab.actions) + '</th>' +
      '</tr></thead><tbody>';
    rows.forEach(function (c) {
      var uses = (Number(c.used) || 0) + ' / ' + (Number(c.max_uses) > 0 ? Number(c.max_uses) : INF);
      var isActive = Number(c.active) === 1 || c.active === true;
      h += '<tr>' +
        '<td class="rev-code">' + esc(c.code) + '</td>' +
        '<td class="rev-num">' + esc(couponTypeText(c)) + '</td>' +
        '<td class="rev-num">' + (Number(c.min_spend) > 0 ? yen(c.min_spend) : esc(lab.dash)) + '</td>' +
        '<td class="rev-num">' + esc(uses) + '</td>' +
        '<td class="rev-num">' + (c.expires ? esc(c.expires) : esc(lab.noExpiry)) + '</td>' +
        '<td><span class="pill ' + (isActive ? 'ok' : 'dim') + '">' + esc(isActive ? lab.on : lab.off) + '</span></td>' +
        '<td><div class="rev-actions">' +
          '<button class="btn btn-dim btn-sm" type="button" data-rev-toggle="' + esc(c.id) + '" data-rev-next="' + (isActive ? 0 : 1) + '">' + esc(isActive ? lab.off : lab.on) + '</button>' +
          '<button class="btn btn-ghost btn-sm" type="button" data-rev-del="' + esc(c.id) + '">' + esc(lab.del) + '</button>' +
        '</div></td>' +
        '</tr>';
    });
    h += '</tbody></table></div>';
    b.innerHTML = h;
    bindCouponForm();

    Array.prototype.forEach.call(b.querySelectorAll('[data-rev-toggle]'), function (btn) {
      btn.addEventListener('click', function () {
        if (state.busy) return;
        state.busy = true;
        var id = btn.getAttribute('data-rev-toggle');
        var next = Number(btn.getAttribute('data-rev-next'));
        api('/api/promos/admin/' + encodeURIComponent(id), {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ active: next })
        }).then(function () { state.busy = false; loadCoupons(); })
          .catch(guarded(function () { state.busy = false; }));
      });
    });
    Array.prototype.forEach.call(b.querySelectorAll('[data-rev-del]'), function (btn) {
      btn.addEventListener('click', function () {
        if (state.busy) return;
        if (!window.confirm(lab.confirmDel)) return;
        state.busy = true;
        var id = btn.getAttribute('data-rev-del');
        api('/api/promos/admin/' + encodeURIComponent(id), { method: 'DELETE' })
          .then(function () { state.busy = false; loadCoupons(); })
          .catch(guarded(function () { state.busy = false; }));
      });
    });
  }

  function renderCouponForm() {
    var lab = state.lab;
    return '<div class="rev-form" data-rev-form>' +
      '<div class="rev-fld"><label>' + esc(lab.code) + '</label>' +
        '<input class="rev-in w-code" type="text" data-cf-code placeholder="' + esc(lab.phCode) + '" autocomplete="off"></div>' +
      '<div class="rev-fld"><label>' + esc(lab.type) + '</label>' +
        '<select class="rev-sel" data-cf-kind>' +
          '<option value="pct">' + esc(lab.kindPct) + '</option>' +
          '<option value="fixed">' + esc(lab.kindFixed) + '</option>' +
        '</select></div>' +
      '<div class="rev-fld"><label>' + esc(lab.amount) + '</label>' +
        '<input class="rev-in w-num" type="number" min="0" step="1" data-cf-amount placeholder="' + esc(lab.phAmount) + '"></div>' +
      '<div class="rev-fld"><label>' + esc(lab.minSpend) + '</label>' +
        '<input class="rev-in w-num" type="number" min="0" step="1" data-cf-min placeholder="' + esc(lab.phMin) + '"></div>' +
      '<div class="rev-fld"><label>' + esc(lab.uses) + '</label>' +
        '<input class="rev-in w-num" type="number" min="0" step="1" data-cf-max placeholder="' + esc(lab.phMax) + '"></div>' +
      '<div class="rev-fld"><label>' + esc(lab.expires) + '</label>' +
        '<input class="rev-in" type="date" data-cf-exp></div>' +
      '<button class="btn btn-gold btn-sm" type="button" data-cf-submit>' + esc(lab.create) + '</button>' +
      '</div>';
  }

  function bindCouponForm() {
    var lab = state.lab, b = body();
    if (!b) return;
    var sub = b.querySelector('[data-cf-submit]');
    if (!sub) return;
    sub.addEventListener('click', function () {
      if (state.busy) return;
      var msg = b.querySelector('[data-rev-cmsg]');
      if (msg) { msg.textContent = ''; msg.style.color = 'var(--bad)'; }
      var code = (b.querySelector('[data-cf-code]').value || '').trim();
      var kind = b.querySelector('[data-cf-kind]').value;
      var amount = Number(b.querySelector('[data-cf-amount]').value || 0);
      var min_spend = Number(b.querySelector('[data-cf-min]').value || 0);
      var max_uses = Number(b.querySelector('[data-cf-max]').value || 0);
      var expires = b.querySelector('[data-cf-exp]').value || '';
      if (!code || !(amount > 0)) {
        if (msg) msg.textContent = lab.dash;
        return;
      }
      state.busy = true;
      var payload = { code: code, kind: kind, amount: amount, min_spend: min_spend, max_uses: max_uses };
      if (expires) payload.expires = expires;
      api('/api/promos/admin', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      }).then(function (res) {
        state.busy = false;
        if (res.status === 409) {
          if (msg) msg.textContent = lab.codeTaken;
          return;
        }
        loadCoupons();
      }).catch(guarded(function () { state.busy = false; }));
    });
  }

  /* ===================== TAB 2: GIFT CARDS ===================== */
  function loadGifts() {
    api('/api/gifts/admin')
      .then(jsonOf)
      .then(function (data) {
        if (!isOpen() || state.tab !== 'gifts') return;
        var rows = (data && Array.isArray(data.gifts)) ? data.gifts : [];
        renderGifts(rows);
      })
      .catch(guarded(function () { renderGifts([]); }));
  }

  function statusPill(status, lab) {
    var s = String(status || '').toLowerCase();
    var cls = 'info';
    if (s === 'active' || s === 'redeemed' || s === 'converted') cls = 'ok';
    else if (s === 'used' || s === 'closed' || s === 'expired') cls = 'dim';
    else if (s === 'pending' || s === 'partial' || s === 'offered' || s === 'waiting') cls = 'warn';
    return '<span class="pill ' + cls + '">' + esc(status || lab.dash) + '</span>';
  }

  function payPill(pay, lab) {
    var s = String(pay || '').toLowerCase();
    if (s === 'paid') return '<span class="pill ok">' + esc(lab.paid) + '</span>';
    if (s === 'unpaid') return '<span class="pill bad">' + esc(lab.unpaid) + '</span>';
    return '<span class="pill dim">' + esc(pay || lab.dash) + '</span>';
  }

  function renderGifts(rows) {
    var lab = state.lab, b = body();
    if (!b) return;
    if (!rows.length) {
      b.innerHTML = '<div class="rev-scroll"><div class="rev-empty">' + esc(lab.emptyGifts) + '</div></div>';
      return;
    }
    var h = '<div class="rev-scroll"><table class="rev-tbl"><thead><tr>' +
      '<th>' + esc(lab.code) + '</th>' +
      '<th>' + esc(lab.initial) + '</th>' +
      '<th>' + esc(lab.balance) + '</th>' +
      '<th>' + esc(lab.status) + '</th>' +
      '<th>' + esc(lab.pay) + '</th>' +
      '<th>' + esc(lab.parties) + '</th>' +
      '<th>' + esc(lab.actions) + '</th>' +
      '</tr></thead><tbody>';
    rows.forEach(function (g) {
      var unpaid = String(g.pay_status || '').toLowerCase() === 'unpaid';
      var parties = esc(g.purchaser_email || lab.dash) + ' <span class="rev-sub">→</span> ' + esc(g.recipient_email || lab.dash);
      h += '<tr>' +
        '<td class="rev-code">' + esc(g.code) + '</td>' +
        '<td class="rev-num">' + yen(g.initial) + '</td>' +
        '<td class="rev-num">' + yen(g.balance) + '</td>' +
        '<td>' + statusPill(g.status, lab) + '</td>' +
        '<td>' + payPill(g.pay_status, lab) + '</td>' +
        '<td><div class="rev-sub">' + parties + '</div></td>' +
        '<td>' + (unpaid ? '<button class="btn btn-gold btn-sm" type="button" data-rev-paid="' + esc(g.id) + '">' + esc(lab.markPaid) + '</button>' : '') + '</td>' +
        '</tr>';
    });
    h += '</tbody></table></div>';
    b.innerHTML = h;

    Array.prototype.forEach.call(b.querySelectorAll('[data-rev-paid]'), function (btn) {
      btn.addEventListener('click', function () {
        if (state.busy) return;
        state.busy = true;
        var id = btn.getAttribute('data-rev-paid');
        api('/api/gifts/admin/' + encodeURIComponent(id) + '/paid', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: '{}'
        }).then(function () { state.busy = false; loadGifts(); })
          .catch(guarded(function () { state.busy = false; }));
      });
    });
  }

  /* ===================== TAB 3: WAITLIST ===================== */
  var WAIT_STATUSES = ['waiting', 'offered', 'converted', 'closed'];

  function loadWaitlist() {
    api('/api/waitlist/admin')
      .then(jsonOf)
      .then(function (data) {
        if (!isOpen() || state.tab !== 'waitlist') return;
        var rows = (data && Array.isArray(data.entries)) ? data.entries : [];
        renderWaitlist(rows);
      })
      .catch(guarded(function () { renderWaitlist([]); }));
  }

  function waitStatusName(s, lab) {
    return { waiting: lab.stWaiting, offered: lab.stOffered, converted: lab.stConverted, closed: lab.stClosed }[s] || s;
  }

  function renderWaitlist(rows) {
    var lab = state.lab, b = body();
    if (!b) return;
    if (!rows.length) {
      b.innerHTML = '<div class="rev-scroll"><div class="rev-empty">' + esc(lab.emptyWait) + '</div></div>';
      return;
    }
    var h = '<div class="rev-scroll"><table class="rev-tbl"><thead><tr>' +
      '<th>' + esc(lab.name) + '</th>' +
      '<th>' + esc(lab.contact) + '</th>' +
      '<th>' + esc(lab.details) + '</th>' +
      '<th>' + esc(lab.status) + '</th>' +
      '<th>' + esc(lab.actions) + '</th>' +
      '</tr></thead><tbody>';
    rows.forEach(function (w) {
      var contact = [];
      if (w.phone) contact.push('<a href="tel:' + esc(String(w.phone).replace(/[^+0-9]/g, '')) + '">' + esc(w.phone) + '</a>');
      if (w.mail) contact.push('<a href="mailto:' + esc(w.mail) + '">' + esc(w.mail) + '</a>');
      if (!contact.length) contact.push(esc(lab.dash));
      var details = [w.plan, w.date, w.time, (w.pax != null ? (Number(w.pax) + ' ' + lab.pax) : '')]
        .filter(function (x) { return x != null && String(x) !== ''; })
        .map(function (x) { return esc(x); }).join(' &middot; ') || esc(lab.dash);
      var cur = String(w.status || 'waiting').toLowerCase();
      var opts = WAIT_STATUSES.map(function (s) {
        return '<option value="' + s + '"' + (s === cur ? ' selected' : '') + '>' + esc(waitStatusName(s, lab)) + '</option>';
      }).join('');
      h += '<tr>' +
        '<td>' + esc(w.name || lab.dash) + '</td>' +
        '<td><div class="rev-sub">' + contact.join('<br>') + '</div></td>' +
        '<td><div class="rev-sub">' + details + '</div></td>' +
        '<td>' + statusPill(waitStatusName(cur, lab), lab) + '</td>' +
        '<td><select class="rev-st-sel" data-rev-wstatus="' + esc(w.id) + '">' + opts + '</select></td>' +
        '</tr>';
    });
    h += '</tbody></table></div>';
    b.innerHTML = h;

    Array.prototype.forEach.call(b.querySelectorAll('[data-rev-wstatus]'), function (sel) {
      sel.addEventListener('change', function () {
        if (state.busy) return;
        state.busy = true;
        var id = sel.getAttribute('data-rev-wstatus');
        api('/api/waitlist/admin/' + encodeURIComponent(id) + '/status', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: sel.value })
        }).then(function () { state.busy = false; loadWaitlist(); })
          .catch(guarded(function () { state.busy = false; }));
      });
    });
  }

  /* ===================== TAB 4: RATE RULES ===================== */
  var DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

  function loadRules() {
    api('/api/pricing/rules')
      .then(jsonOf)
      .then(function (data) {
        if (!isOpen() || state.tab !== 'rules') return;
        var rows = (data && Array.isArray(data.rules)) ? data.rules : [];
        renderRules(rows);
      })
      .catch(guarded(function () { renderRules([]); }));
  }

  function ruleTypeText(r) {
    return r.kind === 'pct' ? ('+' + (Number(r.amount) || 0) + '%') : ('+' + yen(r.amount));
  }

  function ruleSummary(cfg, lab) {
    if (!cfg || typeof cfg !== 'object') return lab.dash;
    var parts = [];
    if (Array.isArray(cfg.dows) && cfg.dows.length) {
      parts.push(cfg.dows.map(function (d) { return DOW[Number(d)] || d; }).join('/'));
    }
    if (cfg.from) parts.push('from ' + cfg.from);
    if (cfg.to) parts.push('to ' + cfg.to);
    if (Array.isArray(cfg.dates) && cfg.dates.length) {
      parts.push(cfg.dates.length + (isJA() ? '日' : ' date' + (cfg.dates.length === 1 ? '' : 's')));
    }
    return parts.length ? parts.join(' · ') : lab.dash;
  }

  function renderRules(rows) {
    var lab = state.lab, b = body();
    if (!b) return;
    if (!rows.length) {
      b.innerHTML = '<div class="rev-scroll"><div class="rev-empty">' + esc(lab.emptyRules) + '</div></div>';
      return;
    }
    var h = '<div class="rev-scroll"><table class="rev-tbl"><thead><tr>' +
      '<th>' + esc(lab.label) + '</th>' +
      '<th>' + esc(lab.type) + '</th>' +
      '<th>' + esc(lab.summary) + '</th>' +
      '</tr></thead><tbody>';
    rows.forEach(function (r) {
      h += '<tr>' +
        '<td>' + esc(r.label || r.code || lab.dash) + '</td>' +
        '<td class="rev-num rev-code">' + esc(ruleTypeText(r)) + '</td>' +
        '<td><div class="rev-sub">' + esc(ruleSummary(r.config, lab)) + '</div></td>' +
        '</tr>';
    });
    h += '</tbody></table></div>';
    b.innerHTML = h;
  }

  /* -------- open -------- */
  function openModal() {
    injectStyles();
    var lab = labels();
    state.lab = lab;
    state.tab = 'coupons';
    state.busy = false;
    var m = buildModal();
    m.querySelector('[data-rev-title]').textContent = lab.title;
    m.classList.add('open');
    document.addEventListener('keydown', onKey);
    renderTabs();
    loadTab();
  }

  /* -------- bind -------- */
  function bind() {
    var btn = document.getElementById('admRevenue');
    if (!btn || btn.__alsRevBound) return; // no-op if the button is absent
    btn.__alsRevBound = true;
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
