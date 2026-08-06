/* Ashiya Limousine — Rewards layer: loyalty points + referral program for
   logged-in customers. Loads (defer) after the main inline script and after
   live.js. Reuses window.ALSCore helpers and window.ALS.openAuth. Bilingual
   EN/JA. Self-contained, never throws. */
(function () {
  'use strict';
  if (window.__alsRewards) return;
  window.__alsRewards = true;

  var C = window.ALSCore || {};
  var esc = C.esc || function (s) { return String(s == null ? '' : s); };
  var yen = C.yen || function (n) { return '¥' + Number(n || 0).toLocaleString('en-US'); };
  var isJA = function () { try { return (C.L || document.documentElement.lang) === 'ja'; } catch (_) { return false; } };
  var T = function (en, ja) { return isJA() ? ja : en; };
  var $ = function (id) { return document.getElementById(id); };

  var toast = function (msg) {
    try {
      if (typeof window.toast === 'function') { window.toast(msg); return; }
      var el = $('toastMsg'), box = $('toast');
      if (el && box) { el.textContent = msg; box.classList.add('show'); setTimeout(function () { box.classList.remove('show'); }, 3200); }
    } catch (_) {}
  };

  var nfmt = function (n) {
    var v = Number(n || 0);
    if (!isFinite(v)) v = 0;
    try { return v.toLocaleString('en-US'); } catch (_) { return String(v); }
  };

  /* ---------- scoped styles ---------- */
  try {
    var css = document.createElement('style');
    css.textContent =
      '#als-rewards .modal{max-width:460px;text-align:left}' +
      '#als-rewards h3{text-align:left}' +
      '#als-rewards .msub{text-align:left}' +
      '.alr-block{border:1px solid var(--hair);border-radius:14px;padding:16px 16px 15px;margin-bottom:14px}' +
      '.alr-lbl{font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--faint);margin-bottom:9px;font-weight:700}' +
      '.alr-pts{font-family:var(--serif);font-size:30px;color:var(--gold2);line-height:1.1}' +
      '.alr-note{color:var(--muted);font-size:12.5px;margin-top:7px;line-height:1.5}' +
      '.alr-how{color:var(--faint);font-size:12px;margin-top:8px;line-height:1.5}' +
      '.alr-code{font-family:var(--mono);text-align:center;font-size:15px;color:var(--gold2);' +
      'border:1px dashed var(--line);border-radius:11px;padding:11px;letter-spacing:.14em;margin-bottom:11px}' +
      '.alr-linkrow{display:flex;gap:8px;align-items:stretch;margin-bottom:11px}' +
      '.alr-link{flex:1;min-width:0;padding:10px 12px;border-radius:10px;border:1px solid var(--line);' +
      'background:var(--panel,rgba(255,255,255,.02));color:var(--cream);font-family:var(--mono);font-size:12px;' +
      'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '.alr-copy{white-space:nowrap;flex-shrink:0}' +
      '.alr-stat{color:var(--muted);font-size:12.5px;margin-top:2px}' +
      '.alr-stat b{color:var(--gold2);font-family:var(--mono);font-weight:400}' +
      '#rewardsLink,#rewardsLinkM{cursor:pointer}';
    document.head.appendChild(css);
  } catch (_) {}

  /* ---------- modal markup ---------- */
  var wrap = document.createElement('div');
  wrap.innerHTML =
    '<div class="modal-bg" id="als-rewards"><div class="modal">' +
    '<button class="x" id="alrX" aria-label="Close"><svg><use href="#i-x"/></svg></button>' +
    '<h3 id="alrTitle">Rewards</h3>' +
    '<p class="msub" id="alrSub"></p>' +
    '<div id="alrBody"></div>' +
    '</div></div>';
  document.body.appendChild(wrap);

  var closeR = function () { try { var m = $('als-rewards'); if (m) m.classList.remove('open'); } catch (_) {} };
  try {
    var xb = $('alrX'); if (xb) xb.onclick = closeR;
    var mb = $('als-rewards');
    if (mb) mb.addEventListener('click', function (e) { if (e.target === mb) closeR(); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { var m = $('als-rewards'); if (m && m.classList.contains('open')) closeR(); }
    });
  } catch (_) {}

  /* ---------- nav links ---------- */
  function makeLink(id) {
    var a = document.createElement('a');
    a.href = '#';
    a.id = id;
    a.setAttribute('style', 'color:var(--gold2)');
    a.textContent = T('Rewards', '特典');
    a.addEventListener('click', function (e) {
      e.preventDefault();
      try { var mm = $('mMenu'); if (mm) mm.classList.remove('open'); } catch (_) {}
      open();
    });
    return a;
  }
  try {
    var acct = $('acctLink');
    if (acct && acct.parentNode && !$('rewardsLink')) {
      acct.parentNode.insertBefore(makeLink('rewardsLink'), acct.nextSibling);
    }
    var mMenu = $('mMenu');
    if (mMenu && !$('rewardsLinkM')) {
      var acctM = $('acctLinkM');
      var lm = makeLink('rewardsLinkM');
      if (acctM && acctM.parentNode === mMenu) mMenu.insertBefore(lm, acctM.nextSibling);
      else mMenu.appendChild(lm);
    }
  } catch (_) {}

  /* ---------- open + render ---------- */
  function open() {
    fetch('/api/referrals/mine', { method: 'GET', credentials: 'include' })
      .then(function (r) {
        if (r.status === 401) {
          closeR();
          try { if (window.ALS && typeof window.ALS.openAuth === 'function') window.ALS.openAuth('login'); } catch (_) {}
          return null;
        }
        return r.json().then(function (d) { return d; }, function () { return null; });
      })
      .then(function (d) {
        if (!d || d.ok !== true) return;
        render(d);
        try { var m = $('als-rewards'); if (m) m.classList.add('open'); } catch (_) {}
      })
      .catch(function () { /* network fail: silent no-op */ });
  }

  function render(d) {
    try {
      $('alrTitle').textContent = T('Rewards', '特典');
      $('alrSub').textContent = T('Your loyalty points and referral rewards.', 'ポイントとご紹介特典の確認ができます。');

      var points = Number(d.points || 0);
      var uses = Number(d.uses || 0);
      var credits = Number(d.credits || 0);
      var code = esc(d.code || '');
      var link = '';
      try { link = location.origin + (d.share_url || ''); } catch (_) { link = String(d.share_url || ''); }

      var ptsLine = isJA()
        ? nfmt(points) + ' ポイント'
        : 'You have ' + nfmt(points) + ' points';
      var ptsNote = T(
        'Earn 1 point per ¥1,000 spent; redeemable on future bookings.',
        'ご利用¥1,000ごとに1ポイント。次回以降のご予約にご利用いただけます。'
      );

      var howReferral = T(
        'How it works: share your link; friends get a warm welcome and you earn credit.',
        'ご紹介の流れ：リンクをシェアすると、ご友人には温かいおもてなし、お客様には特典クレジットが貯まります。'
      );

      var html =
        '<div class="alr-block">' +
        '<div class="alr-lbl">' + esc(T('Loyalty points', 'ロイヤルティ ポイント')) + '</div>' +
        '<div class="alr-pts">' + esc(ptsLine) + '</div>' +
        '<div class="alr-note">' + esc(ptsNote) + '</div>' +
        '</div>' +
        '<div class="alr-block">' +
        '<div class="alr-lbl">' + esc(T('Referral', 'ご紹介')) + '</div>' +
        '<div class="alr-code">' + code + '</div>' +
        '<div class="alr-linkrow">' +
        '<div class="alr-link" id="alrLink" title="' + esc(link) + '">' + esc(link) + '</div>' +
        '<button class="btn btn-gold btn-sm alr-copy" id="alrCopy">' + esc(T('Copy', 'コピー')) + '</button>' +
        '</div>' +
        '<div class="alr-stat">' +
        esc(T('Referrals used:', 'ご紹介数：')) + ' <b>' + nfmt(uses) + '</b> · ' +
        esc(T('Credit earned:', '獲得クレジット：')) + ' <b>' + esc(yen(credits)) + '</b>' +
        '</div>' +
        '<div class="alr-how">' + esc(howReferral) + '</div>' +
        '</div>';

      $('alrBody').innerHTML = html;

      var cp = $('alrCopy');
      if (cp) cp.onclick = function () {
        var done = function () { toast(T('Link copied', 'リンクをコピーしました')); };
        try {
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(link).then(done, function () { fallbackCopy(link, done); });
          } else { fallbackCopy(link, done); }
        } catch (_) { fallbackCopy(link, done); }
      };
    } catch (_) { /* never throw */ }
  }

  function fallbackCopy(text, cb) {
    try {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      if (cb) cb();
    } catch (_) {}
  }
})();
