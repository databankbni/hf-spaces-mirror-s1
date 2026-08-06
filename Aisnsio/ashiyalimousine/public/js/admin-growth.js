/* admin-growth.js — Growth console for the Ashiya Limousine staff dashboard.
   Self-contained browser module. Loads after the main inline script via
   <script src="/js/admin-growth.js" defer></script>. Binds to #admGrowth (no-op
   if absent), opens a "Growth" modal with four tabs: Reviews, Corporate,
   Newsletter and Posts. Mirrors admin-ops.js / admin-customers.js: IIFE +
   double-init guard, injected <style>, .modal-bg/.modal shown via `open`, close
   on X / backdrop / Escape, esc(), an api() wrapper (credentials:'include',
   closes on 401/403), bilingual via document.documentElement.lang / ALSCore.L.
   Reuses the site's CSS vars + .btn/.pill tokens. No frameworks. Never throws. */
(function () {
  'use strict';
  if (window.__alsGrowthInit) return;
  window.__alsGrowthInit = true;

  var STYLE_ID = 'als-growth-style';
  var MODAL_ID = 'alsGrowthModal';

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

  function stars(n) {
    var r = Math.max(0, Math.min(5, Math.round(Number(n) || 0)));
    var out = '';
    for (var i = 0; i < 5; i++) out += i < r ? '★' : '☆';
    return out;
  }

  function toast(msg) {
    try { if (typeof window.toast === 'function') window.toast(msg); } catch (e) { /* noop */ }
  }

  function labels() {
    return isJA()
      ? {
          title: 'グロース',
          tabRev: 'レビュー', tabCorp: '法人', tabNews: 'メルマガ', tabPosts: '記事',
          empty: 'データがありません', dash: '—', del: '削除', add: '追加',
          approve: '承認', unapprove: '承認取消', approved: '承認済', pending: '保留',
          broadcast: '一斉送信', publish: '公開', unpublish: '非公開', published: '公開中', draft: '下書き',
          // reviews
          rating: '評価', author: '投稿者', rTitle: 'タイトル', occasion: '用途', status: '状態',
          // corporate
          company: '会社名', contact: '担当者', est: '月間見込', note: 'メモ',
          stNew: '新規', stApproved: '承認', stDeclined: '却下',
          // newsletter
          email: 'メール', lang: '言語', date: '日付', count: '購読者',
          subject: '件名', message: '本文', langAll: 'すべて', langEn: '英語', langJa: '日本語',
          sent: '送信キュー: ',
          // posts
          kind: '種別', kBlog: 'ブログ', kHelp: 'ヘルプ', excerpt: '抜粋', body: '本文',
          pubChk: '公開する', created: '作成'
        }
      : {
          title: 'Growth',
          tabRev: 'Reviews', tabCorp: 'Corporate', tabNews: 'Newsletter', tabPosts: 'Posts',
          empty: 'No records', dash: '—', del: 'Delete', add: 'Add',
          approve: 'Approve', unapprove: 'Unapprove', approved: 'Approved', pending: 'Pending',
          broadcast: 'Broadcast', publish: 'Publish', unpublish: 'Unpublish', published: 'Published', draft: 'Draft',
          rating: 'Rating', author: 'Author', rTitle: 'Title', occasion: 'Occasion', status: 'Status',
          company: 'Company', contact: 'Contact', est: 'Monthly est.', note: 'Note',
          stNew: 'New', stApproved: 'Approved', stDeclined: 'Declined',
          email: 'Email', lang: 'Lang', date: 'Date', count: 'Subscribers',
          subject: 'Subject', message: 'Message', langAll: 'All', langEn: 'English', langJa: 'Japanese',
          sent: 'Queued: ',
          kind: 'Kind', kBlog: 'Blog', kHelp: 'Help', excerpt: 'Excerpt', body: 'Body',
          pubChk: 'Publish now', created: 'Created'
        };
  }

  /* -------- styles -------- */
  function injectStyles() {
    if (document.getElementById(STYLE_ID)) return;
    var P = '#' + MODAL_ID + ' ';
    var css =
      P + '.modal{max-width:900px;text-align:left}' +
      P + 'h3{text-align:left}' +
      P + '.gr-tabs{display:flex;gap:6px;flex-wrap:wrap;margin:2px 0 16px;border-bottom:1px solid var(--hair);padding-bottom:0}' +
      P + '.gr-tab{background:none;border:none;border-bottom:2px solid transparent;color:var(--muted);' +
        'font-family:var(--mono);font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;' +
        'padding:8px 12px;cursor:pointer;margin-bottom:-1px}' +
      P + '.gr-tab:hover{color:var(--cream)}' +
      P + '.gr-tab.on{color:var(--gold);border-bottom-color:var(--gold)}' +
      P + '.gr-scroll{overflow-x:auto;border:1px solid var(--hair);border-radius:12px}' +
      P + 'table.gr-tbl{width:100%;border-collapse:collapse;min-width:640px;font-size:13px}' +
      P + '.gr-tbl th{font-family:var(--mono);font-size:9.5px;letter-spacing:.16em;text-transform:uppercase;' +
        'color:var(--faint);text-align:left;padding:10px 12px;border-bottom:1px solid var(--hair);white-space:nowrap;background:rgba(255,255,255,.02)}' +
      P + '.gr-tbl td{padding:10px 12px;border-bottom:1px solid var(--hair);color:var(--cream);vertical-align:middle}' +
      P + '.gr-tbl tr:last-child td{border-bottom:none}' +
      P + '.gr-tbl tr:hover td{background:rgba(212,175,55,.05)}' +
      P + 'th.num,' + P + 'td.num{text-align:right}' +
      P + '.gr-empty{padding:26px 14px;text-align:center;color:var(--muted);font-size:13px}' +
      P + '.gr-stars{color:var(--gold);font-size:14px;letter-spacing:1px;white-space:nowrap}' +
      P + '.gr-sub{color:var(--muted);font-size:12px;line-height:1.6}' +
      P + '.gr-sub a{color:var(--gold2)}' +
      P + '.gr-sub a:hover{color:var(--gold)}' +
      P + '.gr-mono{font-family:var(--mono);font-size:12px;color:var(--muted)}' +
      P + '.gr-count{font-family:var(--mono);font-size:11px;color:var(--faint);letter-spacing:.1em;margin:0 0 12px}' +
      P + '.gr-inp{background:var(--panel);border:1px solid var(--line);border-radius:9px;padding:8px 10px;' +
        'color:var(--cream);font-family:var(--sans);font-size:12.5px;outline:none;width:100%}' +
      P + '.gr-inp:focus{border-color:var(--gold)}' +
      P + 'select.gr-inp{cursor:pointer}' +
      P + 'textarea.gr-inp{resize:vertical;min-height:70px;font-family:var(--sans);line-height:1.5}' +
      P + '.gr-sel{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:5px 8px;' +
        'color:var(--cream);font-family:var(--mono);font-size:11px;outline:none;cursor:pointer}' +
      P + '.gr-sel:focus{border-color:var(--gold)}' +
      P + '.gr-form{display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;margin:14px 0 4px;' +
        'padding:13px;border:1px dashed var(--hair);border-radius:12px}' +
      P + '.gr-fld{display:flex;flex-direction:column;gap:4px;flex:1 1 140px}' +
      P + '.gr-fld.grow{flex:2 1 240px}' +
      P + '.gr-fld.full{flex:1 1 100%}' +
      P + '.gr-fld label{font-family:var(--mono);font-size:9px;letter-spacing:.12em;text-transform:uppercase;color:var(--faint)}' +
      P + '.gr-chk{display:flex;align-items:center;gap:7px;flex:1 1 140px;color:var(--cream);font-size:12.5px;cursor:pointer}' +
      P + '.gr-chk input{width:16px;height:16px;accent-color:var(--gold);cursor:pointer}' +
      P + '.gr-del{background:none;border:none;color:var(--faint);cursor:pointer;padding:4px;line-height:1;font-size:14px}' +
      P + '.gr-del:hover{color:var(--bad)}' +
      P + '.gr-act{white-space:nowrap}' +
      P + '.gr-act .btn{margin-right:6px}';
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
  var state = { tab: 'rev', reviews: [], accounts: [], subs: [], subCount: 0, posts: [], lab: null };

  function buildModal() {
    var existing = document.getElementById(MODAL_ID);
    if (existing) return existing;
    var wrap = document.createElement('div');
    wrap.className = 'modal-bg';
    wrap.id = MODAL_ID;
    wrap.innerHTML =
      '<div class="modal" role="dialog" aria-modal="true">' +
        '<button class="x" type="button" data-gr-close aria-label="close">' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>' +
        '</button>' +
        '<h3 data-gr-title></h3>' +
        '<div class="gr-tabs">' +
          '<button class="gr-tab" type="button" data-gr-tab="rev"></button>' +
          '<button class="gr-tab" type="button" data-gr-tab="corp"></button>' +
          '<button class="gr-tab" type="button" data-gr-tab="news"></button>' +
          '<button class="gr-tab" type="button" data-gr-tab="posts"></button>' +
        '</div>' +
        '<div data-gr-body></div>' +
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

  function bodyEl() { return document.querySelector('#' + MODAL_ID + ' [data-gr-body]'); }

  function fld(label, inner, extra) {
    return '<div class="gr-fld ' + (extra || '') + '"><label>' + esc(label) + '</label>' + inner + '</div>';
  }

  function readFields(attr) {
    var out = {};
    var els = document.querySelectorAll('#' + MODAL_ID + ' [' + attr + ']');
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      out[el.getAttribute(attr)] = el.type === 'checkbox' ? el.checked : el.value;
    }
    return out;
  }

  /* -------- tab chrome -------- */
  function syncTabs() {
    var m = document.getElementById(MODAL_ID);
    if (!m) return;
    var lab = state.lab;
    var names = { rev: lab.tabRev, corp: lab.tabCorp, news: lab.tabNews, posts: lab.tabPosts };
    var tabs = m.querySelectorAll('[data-gr-tab]');
    for (var i = 0; i < tabs.length; i++) {
      var k = tabs[i].getAttribute('data-gr-tab');
      tabs[i].textContent = names[k];
      tabs[i].classList.toggle('on', k === state.tab);
    }
  }

  function setTab(tab) {
    state.tab = tab;
    syncTabs();
    var b = bodyEl();
    if (b) b.innerHTML = '<div class="gr-empty">…</div>';
    if (tab === 'rev') loadReviews();
    else if (tab === 'corp') loadCorp();
    else if (tab === 'news') loadNews();
    else loadPosts();
  }

  /* ============ REVIEWS ============ */
  function loadReviews() {
    api('/api/reviews/admin').then(function (d) {
      if (!isOpen() || state.tab !== 'rev') return;
      state.reviews = (d && d.ok && Array.isArray(d.reviews)) ? d.reviews : [];
      renderReviews();
    }).catch(function () {});
  }

  function renderReviews() {
    var lab = state.lab, b = bodyEl();
    if (!b) return;
    var h = '<div class="gr-scroll"><table class="gr-tbl"><thead><tr>' +
      '<th>' + esc(lab.rating) + '</th>' +
      '<th>' + esc(lab.author) + '</th>' +
      '<th>' + esc(lab.rTitle) + '</th>' +
      '<th>' + esc(lab.status) + '</th>' +
      '<th></th></tr></thead><tbody>';
    if (!state.reviews.length) {
      h += '<tr><td colspan="5"><div class="gr-empty">' + esc(lab.empty) + '</div></td></tr>';
    } else {
      state.reviews.forEach(function (r) {
        var id = esc(r.id);
        var ok = !!Number(r.approved);
        h += '<tr>' +
          '<td><span class="gr-stars" title="' + esc(r.rating) + '">' + esc(stars(r.rating)) + '</span></td>' +
          '<td>' + esc(r.author_name || lab.dash) + '<div class="gr-mono">' + esc(fmtDate(r.created_at)) + '</div></td>' +
          '<td>' + esc(r.title || lab.dash) +
            (r.occasion ? '<div class="gr-sub">' + esc(r.occasion) + '</div>' : '') + '</td>' +
          '<td><span class="pill ' + (ok ? 'ok' : 'warn') + '">' + esc(ok ? lab.approved : lab.pending) + '</span></td>' +
          '<td class="num gr-act">' +
            '<button class="btn btn-ghost btn-sm" type="button" data-act="rev-toggle" data-id="' + id + '" data-to="' + (ok ? '0' : '1') + '">' +
              esc(ok ? lab.unapprove : lab.approve) + '</button>' +
            '<button class="gr-del" type="button" data-act="rev-del" data-id="' + id + '" title="' + esc(lab.del) + '">✕</button>' +
          '</td></tr>';
      });
    }
    h += '</tbody></table></div>';
    b.innerHTML = h;
  }

  /* ============ CORPORATE ============ */
  function loadCorp() {
    api('/api/corporate/admin').then(function (d) {
      if (!isOpen() || state.tab !== 'corp') return;
      state.accounts = (d && d.ok && Array.isArray(d.accounts)) ? d.accounts : [];
      renderCorp();
    }).catch(function () {});
  }

  function statusPill(st) {
    var lab = state.lab;
    var cls = st === 'approved' ? 'ok' : (st === 'declined' ? 'bad' : 'warn');
    var txt = st === 'approved' ? lab.stApproved : (st === 'declined' ? lab.stDeclined : lab.stNew);
    return '<span class="pill ' + cls + '">' + esc(txt) + '</span>';
  }

  function statusSelect(id, cur) {
    var lab = state.lab;
    var opts = [['new', lab.stNew], ['approved', lab.stApproved], ['declined', lab.stDeclined]];
    var out = '<select class="gr-sel" data-act="corp-status" data-id="' + esc(id) + '">';
    opts.forEach(function (o) {
      out += '<option value="' + o[0] + '"' + (o[0] === cur ? ' selected' : '') + '>' + esc(o[1]) + '</option>';
    });
    return out + '</select>';
  }

  function renderCorp() {
    var lab = state.lab, b = bodyEl();
    if (!b) return;
    var h = '<div class="gr-scroll"><table class="gr-tbl"><thead><tr>' +
      '<th>' + esc(lab.company) + '</th>' +
      '<th>' + esc(lab.contact) + '</th>' +
      '<th class="num">' + esc(lab.est) + '</th>' +
      '<th>' + esc(lab.status) + '</th>' +
      '<th></th></tr></thead><tbody>';
    if (!state.accounts.length) {
      h += '<tr><td colspan="5"><div class="gr-empty">' + esc(lab.empty) + '</div></td></tr>';
    } else {
      state.accounts.forEach(function (a) {
        var id = esc(a.id);
        var cur = String(a.status || 'new');
        var contact = [];
        if (a.contact_name) contact.push(esc(a.contact_name));
        if (a.email) contact.push('<a href="mailto:' + esc(a.email) + '">' + esc(a.email) + '</a>');
        if (a.phone) contact.push('<a href="tel:' + esc(String(a.phone).replace(/[^+0-9]/g, '')) + '">' + esc(a.phone) + '</a>');
        h += '<tr>' +
          '<td>' + esc(a.company || lab.dash) +
            (a.note ? '<div class="gr-sub">' + esc(a.note) + '</div>' : '') +
            '<div class="gr-mono">' + esc(fmtDate(a.created_at)) + '</div></td>' +
          '<td><div class="gr-sub">' + (contact.length ? contact.join('<br>') : esc(lab.dash)) + '</div></td>' +
          '<td class="num">' + (a.monthly_est ? yen(a.monthly_est) : esc(lab.dash)) + '</td>' +
          '<td>' + statusPill(cur) + '<div style="margin-top:6px">' + statusSelect(id, cur) + '</div></td>' +
          '<td class="num gr-act"><button class="gr-del" type="button" data-act="corp-del" data-id="' + id + '" title="' + esc(lab.del) + '">✕</button></td>' +
          '</tr>';
      });
    }
    h += '</tbody></table></div>';
    b.innerHTML = h;
  }

  /* ============ NEWSLETTER ============ */
  function loadNews() {
    api('/api/newsletter/admin').then(function (d) {
      if (!isOpen() || state.tab !== 'news') return;
      state.subs = (d && d.ok && Array.isArray(d.subscribers)) ? d.subscribers : [];
      state.subCount = (d && Number(d.count)) || state.subs.length;
      renderNews();
    }).catch(function () {});
  }

  function renderNews() {
    var lab = state.lab, b = bodyEl();
    if (!b) return;
    var h = '<div class="gr-count">' + esc(lab.count) + ': ' + esc(state.subCount) + '</div>';
    h += '<div class="gr-scroll"><table class="gr-tbl"><thead><tr>' +
      '<th>' + esc(lab.email) + '</th>' +
      '<th>' + esc(lab.lang) + '</th>' +
      '<th>' + esc(lab.date) + '</th>' +
      '<th></th></tr></thead><tbody>';
    if (!state.subs.length) {
      h += '<tr><td colspan="4"><div class="gr-empty">' + esc(lab.empty) + '</div></td></tr>';
    } else {
      state.subs.forEach(function (s) {
        var id = esc(s.id);
        h += '<tr>' +
          '<td>' + esc(s.email || lab.dash) + '</td>' +
          '<td class="gr-mono">' + esc((s.lang || '').toUpperCase() || lab.dash) + '</td>' +
          '<td class="gr-mono">' + esc(fmtDate(s.created_at)) + '</td>' +
          '<td class="num gr-act"><button class="gr-del" type="button" data-act="news-del" data-id="' + id + '" title="' + esc(lab.del) + '">✕</button></td>' +
          '</tr>';
      });
    }
    h += '</tbody></table></div>';
    // broadcast form
    h += '<div class="gr-form">' +
      fld(lab.subject, '<input class="gr-inp" data-bf="subject" placeholder="' + esc(lab.subject) + '">', 'grow') +
      fld(lab.lang, '<select class="gr-inp" data-bf="lang">' +
        '<option value="">' + esc(lab.langAll) + '</option>' +
        '<option value="en">' + esc(lab.langEn) + '</option>' +
        '<option value="ja">' + esc(lab.langJa) + '</option>' +
        '</select>') +
      fld(lab.message, '<textarea class="gr-inp" data-bf="message" placeholder="' + esc(lab.message) + '"></textarea>', 'full') +
      '<button class="btn btn-gold btn-sm" type="button" data-act="news-broadcast">' + esc(lab.broadcast) + '</button>' +
      '</div>';
    b.innerHTML = h;
  }

  /* ============ POSTS ============ */
  function loadPosts() {
    api('/api/content/admin/all').then(function (d) {
      if (!isOpen() || state.tab !== 'posts') return;
      state.posts = (d && d.ok && Array.isArray(d.posts)) ? d.posts : [];
      renderPosts();
    }).catch(function () {});
  }

  function kindLabel(k) {
    var lab = state.lab;
    return k === 'help' ? lab.kHelp : lab.kBlog;
  }

  function renderPosts() {
    var lab = state.lab, b = bodyEl();
    if (!b) return;
    var h = '<div class="gr-scroll"><table class="gr-tbl"><thead><tr>' +
      '<th>' + esc(lab.rTitle) + '</th>' +
      '<th>' + esc(lab.kind) + '</th>' +
      '<th>' + esc(lab.status) + '</th>' +
      '<th></th></tr></thead><tbody>';
    if (!state.posts.length) {
      h += '<tr><td colspan="4"><div class="gr-empty">' + esc(lab.empty) + '</div></td></tr>';
    } else {
      state.posts.forEach(function (p) {
        var id = esc(p.id);
        var pub = !!Number(p.published);
        h += '<tr>' +
          '<td>' + esc(p.title || lab.dash) +
            (p.excerpt ? '<div class="gr-sub">' + esc(p.excerpt) + '</div>' : '') +
            '<div class="gr-mono">' + esc(p.slug || '') + ' · ' + esc(fmtDate(p.created_at)) + '</div></td>' +
          '<td class="gr-mono">' + esc(kindLabel(p.kind)) + '</td>' +
          '<td><span class="pill ' + (pub ? 'ok' : 'dim') + '">' + esc(pub ? lab.published : lab.draft) + '</span></td>' +
          '<td class="num gr-act">' +
            '<button class="btn btn-ghost btn-sm" type="button" data-act="post-toggle" data-id="' + id + '" data-to="' + (pub ? '0' : '1') + '">' +
              esc(pub ? lab.unpublish : lab.publish) + '</button>' +
            '<button class="gr-del" type="button" data-act="post-del" data-id="' + id + '" title="' + esc(lab.del) + '">✕</button>' +
          '</td></tr>';
      });
    }
    h += '</tbody></table></div>';
    // create form
    h += '<div class="gr-form">' +
      fld(lab.kind, '<select class="gr-inp" data-pf="kind">' +
        '<option value="blog">' + esc(lab.kBlog) + '</option>' +
        '<option value="help">' + esc(lab.kHelp) + '</option>' +
        '</select>') +
      fld(lab.rTitle, '<input class="gr-inp" data-pf="title" placeholder="' + esc(lab.rTitle) + '">', 'grow') +
      fld(lab.excerpt, '<input class="gr-inp" data-pf="excerpt" placeholder="' + esc(lab.excerpt) + '">', 'full') +
      fld(lab.body, '<textarea class="gr-inp" data-pf="body" placeholder="' + esc(lab.body) + '"></textarea>', 'full') +
      '<label class="gr-chk"><input type="checkbox" data-pf="published" checked>' + esc(lab.pubChk) + '</label>' +
      '<button class="btn btn-gold btn-sm" type="button" data-act="post-add">' + esc(lab.add) + '</button>' +
      '</div>';
    b.innerHTML = h;
  }

  /* -------- event delegation -------- */
  function onChange(e) {
    var t = e.target;
    if (!t || !t.getAttribute) return;
    if (t.getAttribute('data-act') === 'corp-status') {
      var id = t.getAttribute('data-id');
      api('/api/corporate/admin/' + id + '/status', { method: 'POST', body: { status: t.value } })
        .then(loadCorp).catch(function () {});
    }
  }

  function onClick(e) {
    var wrap = document.getElementById(MODAL_ID);
    if (e.target === wrap || (e.target.closest && e.target.closest('[data-gr-close]'))) {
      return closeModal();
    }
    var tabBtn = e.target.closest && e.target.closest('[data-gr-tab]');
    if (tabBtn) { setTab(tabBtn.getAttribute('data-gr-tab')); return; }
    var btn = e.target.closest && e.target.closest('[data-act]');
    if (!btn) return;
    var act = btn.getAttribute('data-act');
    if (act === 'corp-status') return; // handled on change
    var id = btn.getAttribute('data-id');

    try {
      if (act === 'rev-toggle') {
        api('/api/reviews/admin/' + id + '/approve', { method: 'POST', body: { approved: Number(btn.getAttribute('data-to')) } })
          .then(loadReviews).catch(function () {});
      } else if (act === 'rev-del') {
        api('/api/reviews/admin/' + id, { method: 'DELETE' }).then(loadReviews).catch(function () {});
      } else if (act === 'corp-del') {
        api('/api/corporate/admin/' + id, { method: 'DELETE' }).then(loadCorp).catch(function () {});
      } else if (act === 'news-del') {
        api('/api/newsletter/admin/' + id, { method: 'DELETE' }).then(loadNews).catch(function () {});
      } else if (act === 'news-broadcast') {
        var bf = readFields('data-bf');
        if (!String(bf.subject || '').trim() || !String(bf.message || '').trim()) return;
        api('/api/newsletter/admin/broadcast', { method: 'POST', body: { subject: bf.subject, message: bf.message, lang: bf.lang } })
          .then(function (d) {
            var n = (d && Number(d.queued)) || 0;
            toast(state.lab.sent + n);
          }).catch(function () {});
      } else if (act === 'post-toggle') {
        api('/api/content/admin/' + id, { method: 'PATCH', body: { published: Number(btn.getAttribute('data-to')) } })
          .then(loadPosts).catch(function () {});
      } else if (act === 'post-del') {
        api('/api/content/admin/' + id, { method: 'DELETE' }).then(loadPosts).catch(function () {});
      } else if (act === 'post-add') {
        var pf = readFields('data-pf');
        if (!String(pf.title || '').trim()) return;
        api('/api/content/admin', {
          method: 'POST',
          body: {
            kind: pf.kind === 'help' ? 'help' : 'blog',
            title: pf.title,
            excerpt: pf.excerpt,
            body: pf.body,
            published: pf.published ? 1 : 0
          }
        }).then(loadPosts).catch(function () {});
      }
    } catch (err) { /* never throw */ }
  }

  /* -------- open -------- */
  function openModal() {
    injectStyles();
    state.lab = labels();
    var m = buildModal();
    m.querySelector('[data-gr-title]').textContent = state.lab.title;
    m.classList.add('open');
    document.addEventListener('keydown', onKey);
    setTab(state.tab || 'rev');
  }

  /* -------- bind -------- */
  function bind() {
    var btn = document.getElementById('admGrowth');
    if (!btn || btn.__alsGrowthBound) return; // no-op if absent
    btn.__alsGrowthBound = true;
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
