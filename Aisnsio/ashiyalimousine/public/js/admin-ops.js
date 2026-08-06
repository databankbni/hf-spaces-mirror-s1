/* admin-ops.js — Operations console for the Ashiya Limousine staff dashboard.
   Self-contained browser module. Loads after the main inline script via
   <script src="/js/admin-ops.js" defer></script>. Binds to #admOps (no-op if
   absent), opens an "Operations" modal with three tabs: Inventory, Incidents
   and CRM. Mirrors admin-customers.js: IIFE + double-init guard, injected
   <style>, .modal-bg/.modal shown via `open`, close on X / backdrop / Escape,
   esc(), an api() wrapper (credentials:'include', closes on 401/403), bilingual
   via document.documentElement.lang / ALSCore.L. Reuses the site's CSS vars +
   .btn/.pill tokens. No frameworks. Never throws. */
(function () {
  'use strict';
  if (window.__alsOpsInit) return;
  window.__alsOpsInit = true;

  var STYLE_ID = 'als-ops-style';
  var MODAL_ID = 'alsOpsModal';

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

  function fmtDate(iso) {
    if (!iso) return '—';
    var s = String(iso);
    var m = s.match(/^(\d{4}-\d{2}-\d{2})/);
    return m ? m[1] : s;
  }

  function labels() {
    return isJA()
      ? {
          title: '運行管理', tabInv: '在庫', tabInc: 'インシデント', tabCrm: '顧客メモ',
          add: '追加', del: '削除', resolve: '解決', load: '読込', low: '在庫僅少',
          empty: 'データがありません', dash: '—',
          // inventory
          item: '品目', unit: '単位', stock: '在庫', threshold: '下限', perBooking: '予約毎',
          addon: '連携アドオン', addonId: 'アドオンID', save: '保存',
          // incidents
          date: '日付', ref: '予約', veh: '車両', kind: '種別', desc: '内容',
          cost: '費用', status: '状態', deposit: '保証金対応', open: '未対応', resolved: '解決済',
          kDamage: '損傷', kCleaning: '清掃', kDelay: '遅延', kComplaint: 'クレーム',
          // crm
          key: '顧客キー（メール/電話）', tag: 'タグ', note: 'メモ', author: '担当',
          tVip: 'VIP', tRepeat: 'リピート', tCorp: '法人', tWatch: '要注意',
          keyHint: '顧客ディレクトリからメールをコピーして貼り付け',
          low1: '在庫僅少: '
        }
      : {
          title: 'Operations', tabInv: 'Inventory', tabInc: 'Incidents', tabCrm: 'CRM',
          add: 'Add', del: 'Delete', resolve: 'Resolve', load: 'Load', low: 'Low',
          empty: 'No records', dash: '—',
          item: 'Item', unit: 'Unit', stock: 'Stock', threshold: 'Threshold', perBooking: 'Per booking',
          addon: 'Add-on', addonId: 'Add-on ID', save: 'Save',
          date: 'Date', ref: 'Ref', veh: 'Vehicle', kind: 'Kind', desc: 'Description',
          cost: 'Cost', status: 'Status', deposit: 'Deposit action', open: 'Open', resolved: 'Resolved',
          kDamage: 'Damage', kCleaning: 'Cleaning', kDelay: 'Delay', kComplaint: 'Complaint',
          key: 'Customer key (email / phone)', tag: 'Tag', note: 'Note', author: 'By',
          tVip: 'VIP', tRepeat: 'Repeat', tCorp: 'Corporate', tWatch: 'Watch',
          keyHint: 'Copy a customer email from the Customers directory into this field',
          low1: 'Low stock: '
        };
  }

  /* -------- styles -------- */
  function injectStyles() {
    if (document.getElementById(STYLE_ID)) return;
    var P = '#' + MODAL_ID + ' ';
    var css =
      P + '.modal{max-width:900px;text-align:left}' +
      P + 'h3{text-align:left}' +
      P + '.ops-tabs{display:flex;gap:6px;flex-wrap:wrap;margin:2px 0 16px;border-bottom:1px solid var(--hair);padding-bottom:0}' +
      P + '.ops-tab{background:none;border:none;border-bottom:2px solid transparent;color:var(--muted);' +
        'font-family:var(--mono);font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;' +
        'padding:8px 12px;cursor:pointer;margin-bottom:-1px}' +
      P + '.ops-tab:hover{color:var(--cream)}' +
      P + '.ops-tab.on{color:var(--gold);border-bottom-color:var(--gold)}' +
      P + '.ops-banner{background:var(--warnbg);color:var(--warn);border:1px solid var(--warn);' +
        'border-radius:10px;padding:9px 13px;font-family:var(--mono);font-size:11.5px;letter-spacing:.06em;margin:0 0 14px}' +
      P + '.ops-scroll{overflow-x:auto;border:1px solid var(--hair);border-radius:12px}' +
      P + 'table.ops-tbl{width:100%;border-collapse:collapse;min-width:680px;font-size:13px}' +
      P + '.ops-tbl th{font-family:var(--mono);font-size:9.5px;letter-spacing:.16em;text-transform:uppercase;' +
        'color:var(--faint);text-align:left;padding:10px 12px;border-bottom:1px solid var(--hair);white-space:nowrap;background:rgba(255,255,255,.02)}' +
      P + '.ops-tbl td{padding:10px 12px;border-bottom:1px solid var(--hair);color:var(--cream);vertical-align:middle}' +
      P + '.ops-tbl tr:last-child td{border-bottom:none}' +
      P + '.ops-tbl tr:hover td{background:rgba(212,175,55,.05)}' +
      P + 'th.num,' + P + 'td.num{text-align:right}' +
      P + '.ops-empty{padding:26px 14px;text-align:center;color:var(--muted);font-size:13px}' +
      P + '.ops-inp{background:var(--panel);border:1px solid var(--line);border-radius:9px;padding:8px 10px;' +
        'color:var(--cream);font-family:var(--sans);font-size:12.5px;outline:none;width:100%}' +
      P + '.ops-inp:focus{border-color:var(--gold)}' +
      P + 'select.ops-inp{cursor:pointer}' +
      P + '.ops-num{width:64px;text-align:right;font-family:var(--mono)}' +
      P + '.ops-adj{display:inline-flex;align-items:center;gap:6px}' +
      P + '.ops-adj button{width:24px;height:24px;border-radius:7px;border:1px solid var(--line);' +
        'background:var(--panel);color:var(--cream);cursor:pointer;font-size:15px;line-height:1;padding:0}' +
      P + '.ops-adj button:hover{border-color:var(--gold);color:var(--gold)}' +
      P + '.ops-form{display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;margin:14px 0 4px;' +
        'padding:13px;border:1px dashed var(--hair);border-radius:12px}' +
      P + '.ops-fld{display:flex;flex-direction:column;gap:4px;flex:1 1 120px}' +
      P + '.ops-fld.grow{flex:2 1 200px}' +
      P + '.ops-fld label{font-family:var(--mono);font-size:9px;letter-spacing:.12em;text-transform:uppercase;color:var(--faint)}' +
      P + '.ops-del{background:none;border:none;color:var(--faint);cursor:pointer;padding:4px;line-height:1}' +
      P + '.ops-del:hover{color:var(--bad)}' +
      P + '.ops-mono{font-family:var(--mono);font-size:12px;color:var(--muted)}' +
      P + '.ops-crmbar{display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;margin-bottom:6px}' +
      P + '.ops-crmbar .ops-fld{flex:1 1 260px}' +
      P + '.ops-hint{font-size:11px;color:var(--faint);margin:8px 2px 2px}' +
      P + '.ops-note{padding:11px 13px;border:1px solid var(--hair);border-radius:11px;margin-bottom:9px}' +
      P + '.ops-note .nh{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:5px}' +
      P + '.ops-note .nt{color:var(--cream);font-size:13px;line-height:1.6;white-space:pre-wrap}' +
      P + '.ops-note .nm{font-family:var(--mono);font-size:10px;color:var(--faint);letter-spacing:.06em;margin-left:auto}';
    var s = document.createElement('style');
    s.id = STYLE_ID;
    s.textContent = css;
    document.head.appendChild(s);
  }

  /* -------- api wrapper -------- */
  function api(path, opts) {
    opts = opts || {};
    opts.credentials = 'include';
    var h = { 'Accept': 'application/json' };
    if (opts.body != null) h['Content-Type'] = 'application/json';
    opts.headers = h;
    if (opts.body != null && typeof opts.body !== 'string') opts.body = JSON.stringify(opts.body);
    return fetch(path, opts).then(function (res) {
      if (res.status === 401 || res.status === 403) {
        closeModal();
        return Promise.reject(new Error('auth'));
      }
      return res.json().catch(function () { return null; });
    });
  }

  /* -------- state + modal shell -------- */
  var state = { tab: 'inv', inv: [], invLow: 0, inc: [], crm: [], crmKey: '', lab: null };

  function buildModal() {
    var existing = document.getElementById(MODAL_ID);
    if (existing) return existing;
    var wrap = document.createElement('div');
    wrap.className = 'modal-bg';
    wrap.id = MODAL_ID;
    wrap.innerHTML =
      '<div class="modal" role="dialog" aria-modal="true">' +
        '<button class="x" type="button" data-ops-close aria-label="close">' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>' +
        '</button>' +
        '<h3 data-ops-title></h3>' +
        '<div class="ops-tabs">' +
          '<button class="ops-tab" type="button" data-ops-tab="inv"></button>' +
          '<button class="ops-tab" type="button" data-ops-tab="inc"></button>' +
          '<button class="ops-tab" type="button" data-ops-tab="crm"></button>' +
        '</div>' +
        '<div data-ops-body></div>' +
      '</div>';
    document.body.appendChild(wrap);

    wrap.addEventListener('click', onClick);
    wrap.addEventListener('change', onChange);
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
    return m && m.classList.contains('open');
  }

  function bodyEl() { return document.querySelector('#' + MODAL_ID + ' [data-ops-body]'); }

  /* -------- tab chrome -------- */
  function syncTabs() {
    var m = document.getElementById(MODAL_ID);
    if (!m) return;
    var lab = state.lab;
    var names = { inv: lab.tabInv, inc: lab.tabInc, crm: lab.tabCrm };
    var tabs = m.querySelectorAll('[data-ops-tab]');
    for (var i = 0; i < tabs.length; i++) {
      var k = tabs[i].getAttribute('data-ops-tab');
      tabs[i].textContent = names[k];
      tabs[i].classList.toggle('on', k === state.tab);
    }
  }

  function setTab(tab) {
    state.tab = tab;
    syncTabs();
    var b = bodyEl();
    if (b) b.innerHTML = '<div class="ops-empty">…</div>';
    if (tab === 'inv') loadInv();
    else if (tab === 'inc') loadInc();
    else renderCrm();
  }

  /* ============ INVENTORY ============ */
  function loadInv() {
    api('/api/inventory').then(function (d) {
      if (!isOpen() || state.tab !== 'inv') return;
      state.inv = (d && d.ok && Array.isArray(d.items)) ? d.items : [];
      state.invLow = (d && Number(d.lowCount)) || 0;
      renderInv();
    }).catch(function () {});
  }

  function renderInv() {
    var lab = state.lab, b = bodyEl();
    if (!b) return;
    var h = '';
    if (state.invLow > 0) {
      h += '<div class="ops-banner">' + esc(lab.low1) + esc(state.invLow) + '</div>';
    }
    h += '<div class="ops-scroll"><table class="ops-tbl"><thead><tr>' +
      '<th>' + esc(lab.item) + '</th>' +
      '<th>' + esc(lab.stock) + '</th>' +
      '<th class="num">' + esc(lab.threshold) + '</th>' +
      '<th>' + esc(lab.unit) + '</th>' +
      '<th>' + esc(lab.addon) + '</th>' +
      '<th></th></tr></thead><tbody>';
    if (!state.inv.length) {
      h += '<tr><td colspan="6"><div class="ops-empty">' + esc(lab.empty) + '</div></td></tr>';
    } else {
      state.inv.forEach(function (r) {
        var id = esc(r.id);
        h += '<tr>' +
          '<td>' + esc(r.item) + '</td>' +
          '<td><div class="ops-adj">' +
            '<button type="button" data-act="inv-dec" data-id="' + id + '" aria-label="-">−</button>' +
            '<input class="ops-inp ops-num" type="number" value="' + esc(r.stock) + '" data-act="inv-stock" data-id="' + id + '">' +
            '<button type="button" data-act="inv-inc" data-id="' + id + '" aria-label="+">＋</button>' +
            (r.low ? ' <span class="pill bad">' + esc(lab.low) + '</span>' : '') +
          '</div></td>' +
          '<td class="num"><input class="ops-inp ops-num" type="number" value="' + esc(r.threshold) + '" data-act="inv-thr" data-id="' + id + '"></td>' +
          '<td>' + esc(r.unit || lab.dash) + '</td>' +
          '<td class="ops-mono">' + esc(r.addon_id || lab.dash) + '</td>' +
          '<td class="num"><button class="ops-del" type="button" data-act="inv-del" data-id="' + id + '" title="' + esc(lab.del) + '">✕</button></td>' +
          '</tr>';
      });
    }
    h += '</tbody></table></div>';
    // add form
    h += '<div class="ops-form">' +
      fld(lab.item, '<input class="ops-inp" data-nf="item" placeholder="' + esc(lab.item) + '">', 'grow') +
      fld(lab.unit, '<input class="ops-inp" data-nf="unit" placeholder="' + esc(lab.unit) + '">') +
      fld(lab.stock, '<input class="ops-inp" type="number" data-nf="stock" value="0">') +
      fld(lab.threshold, '<input class="ops-inp" type="number" data-nf="threshold" value="0">') +
      fld(lab.perBooking, '<input class="ops-inp" type="number" data-nf="per_booking" value="0">') +
      fld(lab.addonId, '<input class="ops-inp" data-nf="addon_id" placeholder="' + esc(lab.addonId) + '">') +
      '<button class="btn btn-gold btn-sm" type="button" data-act="inv-add">' + esc(lab.add) + '</button>' +
      '</div>';
    b.innerHTML = h;
  }

  function fld(label, inner, extra) {
    return '<div class="ops-fld ' + (extra || '') + '"><label>' + esc(label) + '</label>' + inner + '</div>';
  }

  /* ============ INCIDENTS ============ */
  function loadInc() {
    api('/api/incidents').then(function (d) {
      if (!isOpen() || state.tab !== 'inc') return;
      state.inc = (d && d.ok && Array.isArray(d.incidents)) ? d.incidents : [];
      renderInc();
    }).catch(function () {});
  }

  function vehOptions(sel) {
    var seen = {}, out = '<option value=""></option>';
    state.inc.forEach(function (r) {
      var v = r.veh;
      if (v && !seen[v]) { seen[v] = 1; out += '<option value="' + esc(v) + '"' + (v === sel ? ' selected' : '') + '>' + esc(v) + '</option>'; }
    });
    return out;
  }

  function kindOptions() {
    var lab = state.lab;
    return '<option value="damage">' + esc(lab.kDamage) + '</option>' +
      '<option value="cleaning">' + esc(lab.kCleaning) + '</option>' +
      '<option value="delay">' + esc(lab.kDelay) + '</option>' +
      '<option value="complaint">' + esc(lab.kComplaint) + '</option>';
  }

  function kindLabel(k) {
    var lab = state.lab;
    return { damage: lab.kDamage, cleaning: lab.kCleaning, delay: lab.kDelay, complaint: lab.kComplaint }[k] || k || lab.dash;
  }

  function renderInc() {
    var lab = state.lab, b = bodyEl();
    if (!b) return;
    var h = '<div class="ops-scroll"><table class="ops-tbl"><thead><tr>' +
      '<th>' + esc(lab.date) + '</th>' +
      '<th>' + esc(lab.ref) + '</th>' +
      '<th>' + esc(lab.veh) + '</th>' +
      '<th>' + esc(lab.kind) + '</th>' +
      '<th>' + esc(lab.desc) + '</th>' +
      '<th class="num">' + esc(lab.cost) + '</th>' +
      '<th>' + esc(lab.status) + '</th>' +
      '<th></th></tr></thead><tbody>';
    if (!state.inc.length) {
      h += '<tr><td colspan="8"><div class="ops-empty">' + esc(lab.empty) + '</div></td></tr>';
    } else {
      state.inc.forEach(function (r) {
        var id = esc(r.id);
        var resolved = r.status === 'resolved';
        h += '<tr>' +
          '<td class="ops-mono">' + esc(fmtDate(r.created_at)) + '</td>' +
          '<td class="ops-mono">' + esc(r.booking_ref || lab.dash) + '</td>' +
          '<td>' + esc(r.veh || lab.dash) + '</td>' +
          '<td>' + esc(kindLabel(r.kind)) + '</td>' +
          '<td>' + esc(r.description) + '</td>' +
          '<td class="num">' + yen(r.cost) + '</td>' +
          '<td><span class="pill ' + (resolved ? 'ok' : 'warn') + '">' + esc(resolved ? lab.resolved : lab.open) + '</span></td>' +
          '<td class="num" style="white-space:nowrap">' +
            (resolved ? '' : '<button class="btn btn-ghost btn-sm" type="button" data-act="inc-res" data-id="' + id + '">' + esc(lab.resolve) + '</button> ') +
            '<button class="ops-del" type="button" data-act="inc-del" data-id="' + id + '" title="' + esc(lab.del) + '">✕</button>' +
          '</td></tr>';
      });
    }
    h += '</tbody></table></div>';
    h += '<div class="ops-form">' +
      fld(lab.ref, '<input class="ops-inp" data-if="booking_ref" placeholder="' + esc(lab.ref) + '">') +
      fld(lab.veh, '<select class="ops-inp" data-if="veh">' + vehOptions('') + '</select>') +
      fld(lab.kind, '<select class="ops-inp" data-if="kind">' + kindOptions() + '</select>') +
      fld(lab.desc, '<input class="ops-inp" data-if="description" placeholder="' + esc(lab.desc) + '">', 'grow') +
      fld(lab.cost, '<input class="ops-inp" type="number" data-if="cost" value="0">') +
      fld(lab.deposit, '<input class="ops-inp" data-if="deposit_action" placeholder="' + esc(lab.deposit) + '">') +
      '<button class="btn btn-gold btn-sm" type="button" data-act="inc-add">' + esc(lab.add) + '</button>' +
      '</div>';
    b.innerHTML = h;
  }

  /* ============ CRM ============ */
  function renderCrm() {
    var lab = state.lab, b = bodyEl();
    if (!b) return;
    var h = '<div class="ops-crmbar">' +
      fld(lab.key, '<input class="ops-inp" data-crm="key" placeholder="' + esc(lab.key) + '" value="' + esc(state.crmKey) + '">') +
      '<button class="btn btn-gold btn-sm" type="button" data-act="crm-load">' + esc(lab.load) + '</button>' +
      '</div>';
    h += '<div class="ops-hint">' + esc(lab.keyHint) + '</div>';
    if (state.crmKey) {
      if (!state.crm.length) {
        h += '<div class="ops-empty">' + esc(lab.empty) + '</div>';
      } else {
        state.crm.forEach(function (n) {
          h += '<div class="ops-note"><div class="nh">' +
            (n.tag ? '<span class="pill info">' + esc(n.tag) + '</span>' : '') +
            (n.booking_ref ? '<span class="ops-mono">' + esc(n.booking_ref) + '</span>' : '') +
            '<span class="nm">' + esc(fmtDate(n.created_at)) + (n.author ? ' · ' + esc(n.author) : '') + '</span>' +
            '<button class="ops-del" type="button" data-act="crm-del" data-id="' + esc(n.id) + '" title="' + esc(lab.del) + '">✕</button>' +
            '</div>' +
            (n.note ? '<div class="nt">' + esc(n.note) + '</div>' : '') +
            '</div>';
        });
      }
      // add note form
      h += '<div class="ops-form">' +
        fld(lab.tag, '<select class="ops-inp" data-cf="tag">' +
          '<option value="">' + esc(lab.dash) + '</option>' +
          '<option value="VIP">' + esc(lab.tVip) + '</option>' +
          '<option value="Repeat">' + esc(lab.tRepeat) + '</option>' +
          '<option value="Corporate">' + esc(lab.tCorp) + '</option>' +
          '<option value="Watch">' + esc(lab.tWatch) + '</option>' +
          '</select>') +
        fld(lab.note, '<input class="ops-inp" data-cf="note" placeholder="' + esc(lab.note) + '">', 'grow') +
        '<button class="btn btn-gold btn-sm" type="button" data-act="crm-add">' + esc(lab.add) + '</button>' +
        '</div>';
    }
    b.innerHTML = h;
  }

  function loadCrm(key) {
    key = String(key || '').trim();
    state.crmKey = key;
    if (!key) { state.crm = []; renderCrm(); return; }
    api('/api/crm?key=' + encodeURIComponent(key)).then(function (d) {
      if (!isOpen() || state.tab !== 'crm') return;
      state.crm = (d && d.ok && Array.isArray(d.notes)) ? d.notes : [];
      renderCrm();
    }).catch(function () {});
  }

  /* -------- event delegation -------- */
  function onChange(e) {
    var t = e.target;
    if (!t || !t.getAttribute) return;
    var act = t.getAttribute('data-act');
    if (act === 'inv-stock' || act === 'inv-thr') {
      var id = t.getAttribute('data-id');
      var field = act === 'inv-stock' ? 'stock' : 'threshold';
      var body = {};
      body[field] = Number(t.value) || 0;
      api('/api/inventory/' + id, { method: 'PATCH', body: body }).then(loadInv).catch(function () {});
    }
  }

  function readFields(sel, attr) {
    var out = {};
    var els = document.querySelectorAll('#' + MODAL_ID + ' [' + attr + ']');
    for (var i = 0; i < els.length; i++) out[els[i].getAttribute(attr)] = els[i].value;
    return out;
  }

  function onClick(e) {
    var wrap = document.getElementById(MODAL_ID);
    if (e.target === wrap || (e.target.closest && e.target.closest('[data-ops-close]'))) {
      return closeModal();
    }
    var tabBtn = e.target.closest && e.target.closest('[data-ops-tab]');
    if (tabBtn) { setTab(tabBtn.getAttribute('data-ops-tab')); return; }
    var btn = e.target.closest && e.target.closest('[data-act]');
    if (!btn) return;
    var act = btn.getAttribute('data-act');
    var id = btn.getAttribute('data-id');
    if (act === 'inv-stock' || act === 'inv-thr') return; // handled on change

    try {
      if (act === 'inv-inc' || act === 'inv-dec') {
        api('/api/inventory/' + id + '/adjust', { method: 'POST', body: { delta: act === 'inv-inc' ? 1 : -1 } }).then(loadInv).catch(function () {});
      } else if (act === 'inv-del') {
        api('/api/inventory/' + id, { method: 'DELETE' }).then(loadInv).catch(function () {});
      } else if (act === 'inv-add') {
        var nf = readFields('nf', 'data-nf');
        if (!String(nf.item || '').trim()) return;
        api('/api/inventory', { method: 'POST', body: nf }).then(loadInv).catch(function () {});
      } else if (act === 'inc-res') {
        api('/api/incidents/' + id + '/resolve', { method: 'POST', body: {} }).then(loadInc).catch(function () {});
      } else if (act === 'inc-del') {
        api('/api/incidents/' + id, { method: 'DELETE' }).then(loadInc).catch(function () {});
      } else if (act === 'inc-add') {
        var inf = readFields('if', 'data-if');
        if (!String(inf.description || '').trim() || !String(inf.kind || '').trim()) return;
        api('/api/incidents', { method: 'POST', body: inf }).then(loadInc).catch(function () {});
      } else if (act === 'crm-load') {
        var kEl = document.querySelector('#' + MODAL_ID + ' [data-crm="key"]');
        loadCrm(kEl ? kEl.value : '');
      } else if (act === 'crm-add') {
        var cf = readFields('cf', 'data-cf');
        if (!state.crmKey) return;
        if (!String(cf.tag || '').trim() && !String(cf.note || '').trim()) return;
        api('/api/crm', { method: 'POST', body: { cust_key: state.crmKey, tag: cf.tag, note: cf.note } })
          .then(function () { loadCrm(state.crmKey); }).catch(function () {});
      } else if (act === 'crm-del') {
        api('/api/crm/' + id, { method: 'DELETE' }).then(function () { loadCrm(state.crmKey); }).catch(function () {});
      }
    } catch (err) { /* never throw */ }
  }

  /* -------- open -------- */
  function openModal() {
    injectStyles();
    state.lab = labels();
    var m = buildModal();
    m.querySelector('[data-ops-title]').textContent = state.lab.title;
    m.classList.add('open');
    document.addEventListener('keydown', onKey);
    setTab(state.tab || 'inv');
  }

  /* -------- bind -------- */
  function bind() {
    var btn = document.getElementById('admOps');
    if (!btn || btn.__alsOpsBound) return; // no-op if absent
    btn.__alsOpsBound = true;
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
