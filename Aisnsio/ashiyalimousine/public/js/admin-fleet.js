/* admin-fleet.js — Fleet & chauffeurs console for the Ashiya Limousine staff dashboard.
   Self-contained browser module. Loads after the main inline script via
   <script src="/js/admin-fleet.js" defer></script>. Binds to #admFleet (no-op if
   absent), opens a wide modal with 3 tabs: Drivers, Maintenance, Dispatch.
   Reuses window.ALSCore + the site's CSS variables/design tokens. No frameworks.
   Never throws; closes on 401/403. Bilingual EN/JA. */
(function () {
  'use strict';
  if (window.__alsFleetInit) return;
  window.__alsFleetInit = true;

  var STYLE_ID = 'als-fleet-style';
  var MODAL_ID = 'alsFleetModal';

  var VEHS = ['exc3', 'exc4', 'dts', 'c300', 'mas', 'ssk'];
  var MAINT_KINDS = ['inspection', 'service', 'repair', 'cleaning'];
  var DRIVER_STATUSES = ['active', 'off', 'inactive'];

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

  function vehLabel(id) {
    try {
      if (window.ALSCore && typeof window.ALSCore.vehName === 'function') {
        var nm = window.ALSCore.vehName(id);
        if (nm) return nm;
      }
    } catch (e) { /* ignore */ }
    return id;
  }

  function todayISO() {
    var d = new Date();
    var m = String(d.getMonth() + 1);
    var day = String(d.getDate());
    if (m.length < 2) m = '0' + m;
    if (day.length < 2) day = '0' + day;
    return d.getFullYear() + '-' + m + '-' + day;
  }

  function labels() {
    return isJA()
      ? {
          title: '車両・乗務員', tabDrivers: '乗務員', tabMaint: '整備', tabDispatch: '配車',
          add: '追加', del: '削除', done: '完了', save: '保存', unassigned: '未割当',
          name: '氏名', phone: '電話', license: '免許', status: '状態', notes: '備考',
          actions: '操作', empty: 'データがありません', loading: '読み込み中…',
          veh: '車両', kind: '種別', due: '期日', cost: '費用', odo: '走行距離',
          date: '日付', time: '時刻', plan: 'プラン', pax: '人数', pickup: '出発地',
          driver: '乗務員', maps: '地図', noJobs: 'この日の配車はありません',
          st_active: '稼働', st_off: '休み', st_inactive: '停止',
          k_inspection: '車検', k_service: '点検', k_repair: '修理', k_cleaning: '清掃',
          overdue: '期限超過', pDone: '完了', pOpen: '未対応', addDriver: '乗務員を追加',
          addMaint: '整備を追加', dash: '—'
        }
      : {
          title: 'Fleet & chauffeurs', tabDrivers: 'Drivers', tabMaint: 'Maintenance', tabDispatch: 'Dispatch',
          add: 'Add', del: 'Delete', done: 'Mark done', save: 'Save', unassigned: 'unassigned',
          name: 'Name', phone: 'Phone', license: 'License', status: 'Status', notes: 'Notes',
          actions: 'Actions', empty: 'No records', loading: 'Loading…',
          veh: 'Vehicle', kind: 'Kind', due: 'Due', cost: 'Cost', odo: 'Odometer',
          date: 'Date', time: 'Time', plan: 'Plan', pax: 'Pax', pickup: 'Pickup',
          driver: 'Driver', maps: 'Maps', noJobs: 'No jobs scheduled for this day',
          st_active: 'Active', st_off: 'Off', st_inactive: 'Inactive',
          k_inspection: 'Inspection', k_service: 'Service', k_repair: 'Repair', k_cleaning: 'Cleaning',
          overdue: 'Overdue', pDone: 'Done', pOpen: 'Open', addDriver: 'Add driver',
          addMaint: 'Add maintenance', dash: '—'
        };
  }

  function driverStatusLabel(s, lab) {
    if (s === 'active') return lab.st_active;
    if (s === 'off') return lab.st_off;
    if (s === 'inactive') return lab.st_inactive;
    return s || lab.dash;
  }
  function driverStatusPill(s) {
    if (s === 'active') return 'ok';
    if (s === 'off') return 'warn';
    return 'bad';
  }
  function kindLabel(k, lab) {
    var key = 'k_' + k;
    return lab[key] || k || lab.dash;
  }

  /* -------- state -------- */
  var state = { lab: null, tab: 'drivers', drivers: [], dispatchDate: todayISO() };

  /* -------- styles -------- */
  function injectStyles() {
    if (document.getElementById(STYLE_ID)) return;
    var P = '#' + MODAL_ID;
    var css =
      P + ' .modal{max-width:920px;text-align:left}' +
      P + ' h3{text-align:left}' +
      P + ' .flt-tabs{display:flex;gap:8px;flex-wrap:wrap;margin:4px 0 18px}' +
      P + ' .flt-tab{border:1px solid var(--hair);border-radius:99px;padding:8px 17px;font-size:12px;' +
        'font-weight:700;letter-spacing:.06em;color:var(--muted);transition:.18s;cursor:pointer;font-family:var(--sans)}' +
      P + ' .flt-tab:hover{border-color:var(--line)}' +
      P + ' .flt-tab.on{background:var(--gold);color:#1b1503;border-color:var(--gold)}' +
      P + ' .flt-scroll{overflow-x:auto;border:1px solid var(--hair);border-radius:12px}' +
      P + ' table.flt-tbl{width:100%;border-collapse:collapse;min-width:640px;font-size:13px}' +
      P + ' .flt-tbl th{font-family:var(--mono);font-size:9.5px;letter-spacing:.16em;text-transform:uppercase;' +
        'color:var(--faint);text-align:left;padding:11px 14px;border-bottom:1px solid var(--hair);white-space:nowrap;background:rgba(255,255,255,.02)}' +
      P + ' .flt-tbl td{padding:10px 14px;border-bottom:1px solid var(--hair);color:var(--cream);vertical-align:middle}' +
      P + ' .flt-tbl tr:last-child td{border-bottom:none}' +
      P + ' .flt-tbl tr:hover td{background:rgba(212,175,55,.045)}' +
      P + ' .flt-mono{font-family:var(--mono);font-size:12px;color:var(--muted)}' +
      P + ' .flt-name{font-family:var(--serif);font-size:16px;color:var(--cream)}' +
      P + ' .flt-due-red{color:var(--bad);font-family:var(--mono);font-size:12px}' +
      P + ' .flt-empty{padding:34px 14px;text-align:center;color:var(--muted);font-size:13px}' +
      P + ' .flt-form{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:16px;' +
        'padding:14px;border:1px solid var(--hair);border-radius:12px;background:rgba(255,255,255,.015)}' +
      P + ' .flt-in,' + P + ' .flt-sel{background:var(--panel);border:1px solid var(--line);border-radius:9px;' +
        'padding:8px 11px;color:var(--cream);font-family:var(--sans);font-size:12.5px;outline:none;min-width:110px}' +
      P + ' .flt-in:focus,' + P + ' .flt-sel:focus{border-color:var(--gold)}' +
      P + ' .flt-sel{cursor:pointer}' +
      P + ' .flt-sel-sm{padding:5px 9px;font-size:11.5px;min-width:100px;border-radius:8px;' +
        'background:var(--panel);border:1px solid var(--line);color:var(--cream);font-family:var(--sans);outline:none;cursor:pointer}' +
      P + ' .flt-sel-sm:focus{border-color:var(--gold)}' +
      P + ' .flt-actbtn{border:1px solid var(--hair);border-radius:8px;padding:6px 11px;font-size:11px;' +
        'font-weight:700;letter-spacing:.05em;color:var(--muted);transition:.16s;cursor:pointer;font-family:var(--sans)}' +
      P + ' .flt-actbtn:hover{border-color:var(--line);color:var(--cream)}' +
      P + ' .flt-actbtn.danger:hover{border-color:var(--bad);color:var(--bad);background:var(--badbg)}' +
      P + ' .flt-actbtn.good:hover{border-color:var(--ok);color:var(--ok);background:var(--okbg)}' +
      P + ' .flt-acts{display:flex;gap:6px;justify-content:flex-end;flex-wrap:wrap}' +
      P + ' th.flt-r,' + P + ' td.flt-r{text-align:right}' +
      /* dispatch */
      P + ' .flt-dhead{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:14px}' +
      P + ' .flt-time{display:flex;flex-direction:column;gap:12px}' +
      P + ' .flt-job{display:flex;gap:14px;align-items:flex-start;border:1px solid var(--hair);' +
        'border-radius:12px;padding:13px 15px;background:rgba(255,255,255,.015)}' +
      P + ' .flt-job .clk{font-family:var(--mono);font-size:15px;color:var(--gold2);min-width:52px;flex-shrink:0;padding-top:2px}' +
      P + ' .flt-job .mid{flex:1;min-width:0}' +
      P + ' .flt-job .mid b{font-family:var(--serif);font-size:15px;color:var(--cream);display:block}' +
      P + ' .flt-job .meta{font-size:11.5px;color:var(--faint);margin-top:3px;line-height:1.6}' +
      P + ' .flt-job .meta a{color:var(--gold2)}' +
      P + ' .flt-job .meta a:hover{color:var(--gold)}' +
      P + ' .flt-job .ref{font-family:var(--mono);font-size:10.5px;color:var(--gold);letter-spacing:.08em}' +
      P + ' .flt-job .side{display:flex;flex-direction:column;gap:8px;align-items:flex-end;flex-shrink:0}';
    var s = document.createElement('style');
    s.id = STYLE_ID;
    s.textContent = css;
    document.head.appendChild(s);
  }

  /* -------- api wrapper -------- */
  function api(path, opts) {
    opts = opts || {};
    opts.credentials = 'include';
    var headers = { 'Accept': 'application/json' };
    if (opts.body != null && typeof opts.body === 'string') headers['Content-Type'] = 'application/json';
    opts.headers = headers;
    return fetch(path, opts).then(function (res) {
      if (res.status === 401 || res.status === 403) { closeModal(); return null; }
      return res.json().catch(function () { return null; });
    }).catch(function () { return null; });
  }

  /* -------- modal shell -------- */
  function buildModal() {
    var existing = document.getElementById(MODAL_ID);
    if (existing) return existing;
    var wrap = document.createElement('div');
    wrap.className = 'modal-bg';
    wrap.id = MODAL_ID;
    wrap.innerHTML =
      '<div class="modal" role="dialog" aria-modal="true">' +
        '<button class="x" type="button" data-flt-close aria-label="close">' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>' +
        '</button>' +
        '<h3 data-flt-title></h3>' +
        '<div class="flt-tabs" data-flt-tabs></div>' +
        '<div data-flt-body></div>' +
      '</div>';
    document.body.appendChild(wrap);

    wrap.addEventListener('click', function (e) {
      if (e.target === wrap || (e.target.closest && e.target.closest('[data-flt-close]'))) {
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
  function onKey(e) { if (e.key === 'Escape') closeModal(); }

  function isOpen() {
    var m = document.getElementById(MODAL_ID);
    return !!(m && m.classList.contains('open'));
  }
  function bodyEl() { return document.querySelector('#' + MODAL_ID + ' [data-flt-body]'); }

  /* -------- tabs -------- */
  function renderTabs() {
    var lab = state.lab;
    var host = document.querySelector('#' + MODAL_ID + ' [data-flt-tabs]');
    if (!host) return;
    var tabs = [
      { id: 'drivers', label: lab.tabDrivers },
      { id: 'maint', label: lab.tabMaint },
      { id: 'dispatch', label: lab.tabDispatch }
    ];
    host.innerHTML = tabs.map(function (t) {
      return '<button type="button" class="flt-tab' + (state.tab === t.id ? ' on' : '') +
        '" data-tab="' + t.id + '">' + esc(t.label) + '</button>';
    }).join('');
    Array.prototype.forEach.call(host.querySelectorAll('[data-tab]'), function (b) {
      b.addEventListener('click', function () {
        state.tab = b.getAttribute('data-tab');
        renderTabs();
        renderTab();
      });
    });
  }

  function renderTab() {
    if (state.tab === 'drivers') loadDrivers();
    else if (state.tab === 'maint') loadMaintenance();
    else if (state.tab === 'dispatch') loadDispatch();
  }

  function setLoading() {
    var b = bodyEl();
    if (b) b.innerHTML = '<div class="flt-empty">' + esc(state.lab.loading) + '</div>';
  }

  /* -------- DRIVERS tab -------- */
  function loadDrivers() {
    setLoading();
    api('/api/fleet/drivers').then(function (data) {
      if (!isOpen() || state.tab !== 'drivers') return;
      var drivers = (data && Array.isArray(data.drivers)) ? data.drivers : [];
      state.drivers = drivers;
      renderDrivers(drivers);
    });
  }

  function renderDrivers(drivers) {
    var lab = state.lab;
    var b = bodyEl();
    if (!b) return;
    var h = '<div class="flt-scroll"><table class="flt-tbl"><thead><tr>' +
      '<th>' + esc(lab.name) + '</th>' +
      '<th>' + esc(lab.phone) + '</th>' +
      '<th>' + esc(lab.license) + '</th>' +
      '<th>' + esc(lab.status) + '</th>' +
      '<th>' + esc(lab.notes) + '</th>' +
      '<th class="flt-r">' + esc(lab.actions) + '</th>' +
      '</tr></thead><tbody>';
    if (!drivers.length) {
      h += '<tr><td colspan="6"><div class="flt-empty">' + esc(lab.empty) + '</div></td></tr>';
    } else {
      drivers.forEach(function (d) {
        var st = d.status || 'active';
        var opts = DRIVER_STATUSES.map(function (s) {
          return '<option value="' + s + '"' + (s === st ? ' selected' : '') + '>' + esc(driverStatusLabel(s, lab)) + '</option>';
        }).join('');
        h += '<tr>' +
          '<td><span class="flt-name">' + esc(d.name || lab.dash) + '</span></td>' +
          '<td class="flt-mono">' + (d.phone ? esc(d.phone) : esc(lab.dash)) + '</td>' +
          '<td class="flt-mono">' + (d.license ? esc(d.license) : esc(lab.dash)) + '</td>' +
          '<td><span class="pill ' + driverStatusPill(st) + '">' + esc(driverStatusLabel(st, lab)) + '</span></td>' +
          '<td>' + (d.notes ? esc(d.notes) : esc(lab.dash)) + '</td>' +
          '<td><div class="flt-acts">' +
            '<select class="flt-sel-sm" data-drv-status="' + esc(d.id) + '">' + opts + '</select>' +
            '<button type="button" class="flt-actbtn danger" data-drv-del="' + esc(d.id) + '">' + esc(lab.del) + '</button>' +
          '</div></td>' +
        '</tr>';
      });
    }
    h += '</tbody></table></div>';

    // add form
    var statusOpts = DRIVER_STATUSES.map(function (s) {
      return '<option value="' + s + '">' + esc(driverStatusLabel(s, lab)) + '</option>';
    }).join('');
    h += '<div class="flt-form" data-drv-form>' +
      '<input class="flt-in" type="text" data-f="name" placeholder="' + esc(lab.name) + '" autocomplete="off">' +
      '<input class="flt-in" type="text" data-f="phone" placeholder="' + esc(lab.phone) + '" autocomplete="off">' +
      '<input class="flt-in" type="text" data-f="license" placeholder="' + esc(lab.license) + '" autocomplete="off">' +
      '<select class="flt-sel" data-f="status">' + statusOpts + '</select>' +
      '<button type="button" class="btn btn-sm" data-drv-add>' + esc(lab.add) + '</button>' +
    '</div>';
    b.innerHTML = h;

    Array.prototype.forEach.call(b.querySelectorAll('[data-drv-status]'), function (sel) {
      sel.addEventListener('change', function () {
        var id = sel.getAttribute('data-drv-status');
        api('/api/fleet/drivers/' + encodeURIComponent(id), {
          method: 'PATCH', body: JSON.stringify({ status: sel.value })
        }).then(function () { if (isOpen() && state.tab === 'drivers') loadDrivers(); });
      });
    });
    Array.prototype.forEach.call(b.querySelectorAll('[data-drv-del]'), function (btn) {
      btn.addEventListener('click', function () {
        var id = btn.getAttribute('data-drv-del');
        api('/api/fleet/drivers/' + encodeURIComponent(id), { method: 'DELETE' })
          .then(function () { if (isOpen() && state.tab === 'drivers') loadDrivers(); });
      });
    });
    var addBtn = b.querySelector('[data-drv-add]');
    if (addBtn) addBtn.addEventListener('click', function () {
      var form = b.querySelector('[data-drv-form]');
      if (!form) return;
      var payload = {
        name: form.querySelector('[data-f="name"]').value.trim(),
        phone: form.querySelector('[data-f="phone"]').value.trim(),
        license: form.querySelector('[data-f="license"]').value.trim(),
        status: form.querySelector('[data-f="status"]').value
      };
      if (!payload.name) return;
      api('/api/fleet/drivers', { method: 'POST', body: JSON.stringify(payload) })
        .then(function () { if (isOpen() && state.tab === 'drivers') loadDrivers(); });
    });
  }

  /* -------- MAINTENANCE tab -------- */
  function loadMaintenance() {
    setLoading();
    api('/api/fleet/maintenance').then(function (data) {
      if (!isOpen() || state.tab !== 'maint') return;
      var items = (data && Array.isArray(data.items)) ? data.items : [];
      renderMaintenance(items);
    });
  }

  function maintPill(it, lab) {
    var s = String(it.status || '').toLowerCase();
    if (s === 'done' || s === 'completed') return '<span class="pill ok">' + esc(lab.pDone) + '</span>';
    if (it.overdue) return '<span class="pill bad">' + esc(lab.overdue) + '</span>';
    return '<span class="pill warn">' + esc(it.status || lab.pOpen) + '</span>';
  }

  function renderMaintenance(items) {
    var lab = state.lab;
    var b = bodyEl();
    if (!b) return;
    var h = '<div class="flt-scroll"><table class="flt-tbl"><thead><tr>' +
      '<th>' + esc(lab.veh) + '</th>' +
      '<th>' + esc(lab.kind) + '</th>' +
      '<th>' + esc(lab.due) + '</th>' +
      '<th>' + esc(lab.status) + '</th>' +
      '<th class="flt-r">' + esc(lab.cost) + '</th>' +
      '<th>' + esc(lab.notes) + '</th>' +
      '<th class="flt-r">' + esc(lab.actions) + '</th>' +
      '</tr></thead><tbody>';
    if (!items.length) {
      h += '<tr><td colspan="7"><div class="flt-empty">' + esc(lab.empty) + '</div></td></tr>';
    } else {
      items.forEach(function (it) {
        var s = String(it.status || '').toLowerCase();
        var isDone = (s === 'done' || s === 'completed');
        var dueTxt = it.due_date ? esc(it.due_date) : esc(lab.dash);
        var dueCell = it.overdue ? '<span class="flt-due-red">' + dueTxt + '</span>' : '<span class="flt-mono">' + dueTxt + '</span>';
        h += '<tr>' +
          '<td>' + esc(vehLabel(it.veh)) + '</td>' +
          '<td>' + esc(kindLabel(it.kind, lab)) + '</td>' +
          '<td>' + dueCell + '</td>' +
          '<td>' + maintPill(it, lab) + '</td>' +
          '<td class="flt-r flt-mono">' + (it.cost != null && it.cost !== '' ? yen(it.cost) : esc(lab.dash)) + '</td>' +
          '<td>' + (it.notes ? esc(it.notes) : esc(lab.dash)) + '</td>' +
          '<td><div class="flt-acts">' +
            (isDone ? '' : '<button type="button" class="flt-actbtn good" data-mnt-done="' + esc(it.id) + '">' + esc(lab.done) + '</button>') +
            '<button type="button" class="flt-actbtn danger" data-mnt-del="' + esc(it.id) + '">' + esc(lab.del) + '</button>' +
          '</div></td>' +
        '</tr>';
      });
    }
    h += '</tbody></table></div>';

    // add form
    var vehOpts = VEHS.map(function (v) {
      return '<option value="' + v + '">' + esc(vehLabel(v)) + '</option>';
    }).join('');
    var kindOpts = MAINT_KINDS.map(function (k) {
      return '<option value="' + k + '">' + esc(kindLabel(k, lab)) + '</option>';
    }).join('');
    h += '<div class="flt-form" data-mnt-form>' +
      '<select class="flt-sel" data-f="veh">' + vehOpts + '</select>' +
      '<select class="flt-sel" data-f="kind">' + kindOpts + '</select>' +
      '<input class="flt-in" type="date" data-f="due_date">' +
      '<input class="flt-in" type="text" data-f="notes" placeholder="' + esc(lab.notes) + '" autocomplete="off">' +
      '<button type="button" class="btn btn-sm" data-mnt-add>' + esc(lab.add) + '</button>' +
    '</div>';
    b.innerHTML = h;

    Array.prototype.forEach.call(b.querySelectorAll('[data-mnt-done]'), function (btn) {
      btn.addEventListener('click', function () {
        var id = btn.getAttribute('data-mnt-done');
        api('/api/fleet/maintenance/' + encodeURIComponent(id) + '/done', { method: 'POST', body: '{}' })
          .then(function () { if (isOpen() && state.tab === 'maint') loadMaintenance(); });
      });
    });
    Array.prototype.forEach.call(b.querySelectorAll('[data-mnt-del]'), function (btn) {
      btn.addEventListener('click', function () {
        var id = btn.getAttribute('data-mnt-del');
        api('/api/fleet/maintenance/' + encodeURIComponent(id), { method: 'DELETE' })
          .then(function () { if (isOpen() && state.tab === 'maint') loadMaintenance(); });
      });
    });
    var addBtn = b.querySelector('[data-mnt-add]');
    if (addBtn) addBtn.addEventListener('click', function () {
      var form = b.querySelector('[data-mnt-form]');
      if (!form) return;
      var payload = {
        veh: form.querySelector('[data-f="veh"]').value,
        kind: form.querySelector('[data-f="kind"]').value,
        due_date: form.querySelector('[data-f="due_date"]').value,
        notes: form.querySelector('[data-f="notes"]').value.trim()
      };
      if (!payload.due_date) return;
      api('/api/fleet/maintenance', { method: 'POST', body: JSON.stringify(payload) })
        .then(function () { if (isOpen() && state.tab === 'maint') loadMaintenance(); });
    });
  }

  /* -------- DISPATCH tab -------- */
  function loadDispatch() {
    setLoading();
    var date = state.dispatchDate || todayISO();
    Promise.all([
      api('/api/fleet/dispatch?date=' + encodeURIComponent(date)),
      api('/api/fleet/drivers')
    ]).then(function (res) {
      if (!isOpen() || state.tab !== 'dispatch') return;
      var jobs = (res[0] && Array.isArray(res[0].jobs)) ? res[0].jobs.slice() : [];
      var drivers = (res[1] && Array.isArray(res[1].drivers)) ? res[1].drivers : [];
      state.drivers = drivers;
      jobs.sort(function (a, b) { return String(a.time || '').localeCompare(String(b.time || '')); });
      renderDispatch(jobs, drivers);
    });
  }

  function jobStatusPill(status) {
    var s = String(status || '').toLowerCase();
    if (s === 'completed' || s === 'confirmed' || s === 'done') return 'ok';
    if (s === 'pending' || s === 'hold') return 'warn';
    if (s === 'cancelled' || s === 'canceled') return 'bad';
    return 'info';
  }

  function renderDispatch(jobs, drivers) {
    var lab = state.lab;
    var b = bodyEl();
    if (!b) return;
    var h = '<div class="flt-dhead">' +
      '<input class="flt-in" type="date" data-disp-date value="' + esc(state.dispatchDate) + '">' +
    '</div>';

    if (!jobs.length) {
      h += '<div class="flt-empty">' + esc(lab.noJobs) + '</div>';
      b.innerHTML = h;
      wireDispatchDate(b);
      return;
    }

    var driverOptsFor = function (selectedId) {
      var sel = (selectedId == null || selectedId === '') ? '' : String(selectedId);
      var out = '<option value=""' + (sel === '' ? ' selected' : '') + '>' + esc(lab.unassigned) + '</option>';
      drivers.forEach(function (d) {
        out += '<option value="' + esc(d.id) + '"' + (String(d.id) === sel ? ' selected' : '') + '>' + esc(d.name || d.id) + '</option>';
      });
      return out;
    };

    h += '<div class="flt-time">';
    jobs.forEach(function (j) {
      var metaBits = [];
      metaBits.push(esc(vehLabel(j.veh)));
      metaBits.push(esc((j.pax != null ? j.pax : '') + (isJA() ? '名' : ' pax')));
      if (j.pickup) metaBits.push(esc(j.pickup));
      var mapLink = j.maps_url ? '<a href="' + esc(j.maps_url) + '" target="_blank" rel="noopener">' + esc(lab.maps) + '</a>' : '';
      h += '<div class="flt-job">' +
        '<div class="clk">' + esc(j.time || lab.dash) + '</div>' +
        '<div class="mid">' +
          '<b>' + esc(j.plan_name_en || lab.dash) + '</b>' +
          '<div class="meta">' + metaBits.join(' · ') + (mapLink ? ' · ' + mapLink : '') + '</div>' +
          '<div class="ref">' + esc(j.ref || '') + '</div>' +
        '</div>' +
        '<div class="side">' +
          '<span class="pill ' + jobStatusPill(j.status) + '">' + esc(j.status || lab.dash) + '</span>' +
          '<select class="flt-sel-sm" data-disp-assign="' + esc(j.ref) + '">' + driverOptsFor(j.driver_id) + '</select>' +
        '</div>' +
      '</div>';
    });
    h += '</div>';
    b.innerHTML = h;

    wireDispatchDate(b);
    Array.prototype.forEach.call(b.querySelectorAll('[data-disp-assign]'), function (sel) {
      sel.addEventListener('change', function () {
        var ref = sel.getAttribute('data-disp-assign');
        var val = sel.value;
        var driverId = (val === '') ? null : (isNaN(Number(val)) ? val : Number(val));
        api('/api/fleet/assign', { method: 'POST', body: JSON.stringify({ ref: ref, driver_id: driverId }) })
          .then(function () { if (isOpen() && state.tab === 'dispatch') loadDispatch(); });
      });
    });
  }

  function wireDispatchDate(b) {
    var dp = b.querySelector('[data-disp-date]');
    if (dp) dp.addEventListener('change', function () {
      state.dispatchDate = dp.value || todayISO();
      loadDispatch();
    });
  }

  /* -------- open -------- */
  function openModal() {
    injectStyles();
    state.lab = labels();
    state.tab = 'drivers';
    if (!state.dispatchDate) state.dispatchDate = todayISO();
    var m = buildModal();
    m.querySelector('[data-flt-title]').textContent = state.lab.title;
    m.classList.add('open');
    document.addEventListener('keydown', onKey);
    renderTabs();
    renderTab();
  }

  /* -------- bind -------- */
  function bind() {
    var btn = document.getElementById('admFleet');
    if (!btn || btn.__alsFleetBound) return; // no-op if absent
    btn.__alsFleetBound = true;
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
