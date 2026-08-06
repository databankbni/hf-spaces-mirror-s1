/* Ashiya Limousine — booking extras layer: PROMO CODE + GIFT CARD + GRATUITY.
   Injects a controls panel above #submitBk, keeps a live server-authoritative
   price preview (POST /api/pricing/quote), and feeds the accepted values into
   window.ALSExtras so the main booking submit sends them. Loads deferred, after
   the main inline script and live.js. Self-contained; vanilla JS; no deps. */
(function () {
  'use strict';

  if (window.__alsExtrasInit) return;      // guard double-init
  window.__alsExtrasInit = true;

  var C = window.ALSCore || {};
  var X = window.ALSExtras = window.ALSExtras || { coupon: '', gift: '', tip: 0 };

  var yen = C.yen || function (n) { return '¥' + Number(n || 0).toLocaleString('en-US'); };
  var esc = C.esc || function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  };
  var isJA = function () { return (C.L || document.documentElement.lang) === 'ja'; };
  var T = function (en, ja) { return isJA() ? ja : en; };
  // Prefer a real i18n value from ALSCore.tt; fall back to an EN/JA literal.
  var lab = function (key, en, ja) {
    if (C.tt) { var v = C.tt(key); if (v && v !== key) return v; }
    return T(en, ja);
  };
  var negYen = function (n) { return '−' + yen(Math.abs(Number(n || 0))); };

  function ready(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }

  ready(function () {
    var submit = document.getElementById('submitBk');
    if (!submit || !submit.parentNode) return;                       // no-op if absent

    /* ---------- scoped styles (site CSS vars) ---------- */
    var css = document.createElement('style');
    css.textContent =
      '#als-extras{margin:14px 0;padding:16px 15px;border:1px solid var(--hair);border-radius:14px;background:linear-gradient(172deg,var(--panel),transparent 78%);display:flex;flex-direction:column;gap:14px}' +
      '#als-extras .xg-lbl{font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--gold);font-weight:700;margin-bottom:7px}' +
      '#als-extras .xg-row{display:flex;gap:8px;align-items:stretch}' +
      '#als-extras .xg-row input{flex:1;min-width:0;padding:10px 12px;border-radius:10px;border:1px solid var(--line);background:var(--panel);color:var(--cream);font-family:var(--mono);font-size:13px;letter-spacing:.05em;text-transform:uppercase}' +
      '#als-extras .xg-row input:focus{outline:none;border-color:var(--gold)}' +
      '#als-extras .xg-apply{flex:0 0 auto;padding:0 15px;border-radius:10px;border:1px solid var(--line);background:transparent;color:var(--gold2);font-size:11.5px;letter-spacing:.05em;font-weight:700;cursor:pointer;transition:.15s;white-space:nowrap}' +
      '#als-extras .xg-apply:hover{background:var(--golddim);border-color:var(--gold)}' +
      '#als-extras .xg-apply.on{background:var(--golddim);border-color:var(--gold);color:var(--gold2)}' +
      '#als-extras .xg-err{color:var(--bad);font-size:12px;min-height:0;margin-top:6px;display:none}' +
      '#als-extras .xg-err.show{display:block}' +
      '#als-extras .xg-ok{color:var(--ok,#6ecf8f);font-size:12px;margin-top:6px;display:none}' +
      '#als-extras .xg-ok.show{display:block}' +
      '#als-extras .xg-chips{display:flex;flex-wrap:wrap;gap:7px}' +
      '#als-extras .xg-chip{padding:8px 13px;border-radius:99px;border:1px solid var(--line);background:transparent;color:var(--muted);font-family:var(--mono);font-size:12px;cursor:pointer;transition:.15s}' +
      '#als-extras .xg-chip:hover{border-color:var(--gold);color:var(--gold2)}' +
      '#als-extras .xg-chip.on{background:linear-gradient(130deg,var(--gold),var(--gold2));color:#1b1503;font-weight:700;border-color:transparent}' +
      '#als-quote{border-top:1px solid var(--hair);padding-top:12px;display:flex;flex-direction:column;gap:6px}' +
      '#als-quote .ql{display:flex;justify-content:space-between;gap:14px;font-size:13px;color:var(--muted)}' +
      '#als-quote .ql .qk{color:var(--muted)}' +
      '#als-quote .ql .qv{font-family:var(--mono);color:var(--cream)}' +
      '#als-quote .ql.disc .qv{color:var(--ok,#6ecf8f)}' +
      '#als-quote .qtotal{display:flex;justify-content:space-between;align-items:baseline;gap:14px;margin-top:5px;padding-top:9px;border-top:1px solid var(--hair)}' +
      '#als-quote .qtotal .qk{font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--gold);font-weight:700}' +
      '#als-quote .qtotal .qv{font-family:var(--mono);font-size:22px;color:var(--gold2)}' +
      '#als-quote .qdep{font-size:11.5px;color:var(--faint);text-align:right;font-family:var(--mono)}' +
      '#als-quote .qhint{color:var(--muted);font-size:12.5px;text-align:center;padding:6px 0}';
    document.head.appendChild(css);

    /* ---------- markup ---------- */
    var panel = document.createElement('div');
    panel.id = 'als-extras';
    panel.innerHTML =
      '<div class="xg-block">' +
        '<div class="xg-lbl">' + esc(lab('coupon_l', 'Promo code', 'プロモコード')) + '</div>' +
        '<div class="xg-row">' +
          '<input id="xg-coupon" autocomplete="off" spellcheck="false" placeholder="' + esc(T('Enter code', 'コードを入力')) + '">' +
          '<button type="button" class="xg-apply" id="xg-coupon-go">' + esc(lab('apply_l', 'Apply', '適用')) + '</button>' +
        '</div>' +
        '<div class="xg-err" id="xg-coupon-err"></div>' +
        '<div class="xg-ok" id="xg-coupon-ok"></div>' +
      '</div>' +
      '<div class="xg-block">' +
        '<div class="xg-lbl">' + esc(lab('gift_l', 'Gift card', 'ギフトカード')) + '</div>' +
        '<div class="xg-row">' +
          '<input id="xg-gift" autocomplete="off" spellcheck="false" placeholder="' + esc(T('Enter code', 'コードを入力')) + '">' +
          '<button type="button" class="xg-apply" id="xg-gift-go">' + esc(lab('apply_l', 'Apply', '適用')) + '</button>' +
        '</div>' +
        '<div class="xg-err" id="xg-gift-err"></div>' +
        '<div class="xg-ok" id="xg-gift-ok"></div>' +
      '</div>' +
      '<div class="xg-block">' +
        '<div class="xg-lbl">' + esc(lab('tip_l', 'Gratuity', 'グラチュイティ（心付け）')) + '</div>' +
        '<div class="xg-chips" id="xg-tips"></div>' +
      '</div>' +
      '<div id="als-quote"></div>';
    submit.parentNode.insertBefore(panel, submit);

    var $ = function (id) { return document.getElementById(id); };
    var couponIn = $('xg-coupon'), giftIn = $('xg-gift'), quoteBox = $('als-quote');

    /* ---------- state ---------- */
    var TIP_CHIPS = [
      { mode: 'none', label: T('None', 'なし'), val: 0 },
      { mode: '3000', label: '¥3,000', val: 3000 },
      { mode: '5000', label: '¥5,000', val: 5000 },
      { mode: '10000', label: '¥10,000', val: 10000 },
      { mode: 'pct', label: '10%', val: null }
    ];
    var state = { coupon: '', gift: '', tipMode: 'none', tip: 0 };
    var lastQuote = null;

    // Render gratuity chips.
    var chipWrap = $('xg-tips');
    TIP_CHIPS.forEach(function (c) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'xg-chip';
      b.setAttribute('data-mode', c.mode);
      b.textContent = c.label;
      b.onclick = function () { state.tipMode = c.mode; syncChips(); refresh(); };
      chipWrap.appendChild(b);
    });
    function syncChips() {
      chipWrap.querySelectorAll('.xg-chip').forEach(function (b) {
        b.classList.toggle('on', b.getAttribute('data-mode') === state.tipMode);
      });
    }
    syncChips();

    function computeTip() {
      if (state.tipMode === 'pct') {
        var sub = (lastQuote && lastQuote.subtotal) || (C.priceNow ? C.priceNow() : 0) || 0;
        return Math.round(sub * 0.1);
      }
      var c = TIP_CHIPS.filter(function (x) { return x.mode === state.tipMode; })[0];
      return c ? (c.val || 0) : 0;
    }

    /* ---------- error text ---------- */
    function couponMsg(err, amt) {
      switch (err) {
        case 'expired': return T('This code has expired.', 'このコードは有効期限切れです。');
        case 'used_up': return T('This code is no longer available.', 'このコードは利用上限に達しています。');
        case 'min_spend': return (Number(amt) > 0)
          ? T('Minimum spend ', '最低ご利用金額 ') + yen(amt)
          : T('Your order does not meet this code’s minimum spend.', 'このコードの最低ご利用金額に達していません。');
        case 'invalid':
        default: return T('Invalid code.', '無効なコードです。');
      }
    }
    function giftMsg(err) {
      switch (err) {
        case 'empty': return T('No balance remaining on this card.', 'このカードに残高がありません。');
        case 'invalid':
        default: return T('Invalid gift card.', '無効なギフトカードです。');
      }
    }
    function setMsg(errId, okId, errText, okText) {
      var e = $(errId), o = $(okId);
      if (errText) { e.textContent = errText; e.classList.add('show'); } else { e.textContent = ''; e.classList.remove('show'); }
      if (okText) { o.textContent = okText; o.classList.add('show'); } else { o.textContent = ''; o.classList.remove('show'); }
    }

    /* ---------- render breakdown ---------- */
    function renderHint(text) {
      quoteBox.innerHTML = '<div class="qhint">' + esc(text) + '</div>';
    }
    function renderQuote(qt) {
      var rows = '';
      (qt.breakdown || []).forEach(function (ln) {
        var neg = Number(ln.amount) < 0;
        rows += '<div class="ql' + (neg ? ' disc' : '') + '">' +
          '<span class="qk">' + esc(ln.label) + '</span>' +
          '<span class="qv">' + (neg ? negYen(ln.amount) : yen(ln.amount)) + '</span></div>';
      });
      rows += '<div class="qtotal"><span class="qk">' + esc(T('Total', '合計')) + '</span>' +
        '<span class="qv">' + yen(qt.total) + '</span></div>';
      rows += '<div class="qdep">' + esc(T('Deposit ', '内金 ')) + yen(qt.deposit) + '</div>';
      quoteBox.innerHTML = rows;
    }

    /* ---------- fetch quote ---------- */
    function doQuote() {
      var sel = C.currentSelection ? C.currentSelection() : null;
      if (!sel || !sel.plan || !sel.date) {
        renderHint(T('Choose a plan and a date to see your price.', 'プランと日付を選ぶと料金が表示されます。'));
        return;
      }
      state.tip = computeTip();
      // Mirror what the user entered so the submit sends exactly that.
      X.coupon = state.coupon;
      X.gift = state.gift;
      X.tip = state.tip;

      var body = {
        plan: sel.plan, addons: sel.addons || [], pax: sel.pax,
        date: sel.date, time: sel.time,
        couponCode: state.coupon, giftCode: state.gift, tip: state.tip
      };
      fetch('/api/pricing/quote', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(body)
      }).then(function (r) {
        return r.json().then(function (d) { return { ok: r.ok, data: d }; });
      }).then(function (res) {
        var d = res.data || {};
        if (!d.ok || !d.quote) {
          renderHint(T('Price preview unavailable.', '料金プレビューを取得できませんでした。'));
          return;
        }
        var qt = lastQuote = d.quote;
        // recompute pct tip against fresh subtotal, re-quote if it changed
        if (state.tipMode === 'pct') {
          var freshTip = Math.round((qt.subtotal || 0) * 0.1);
          if (freshTip !== state.tip) { refresh(); return; }
        }
        // coupon feedback
        if (state.coupon && qt.couponError) {
          setMsg('xg-coupon-err', 'xg-coupon-ok', couponMsg(qt.couponError, qt.min_spend), '');
        } else if (qt.coupon) {
          setMsg('xg-coupon-err', 'xg-coupon-ok', '', T('Applied: ', '適用: ') + qt.coupon);
        } else {
          setMsg('xg-coupon-err', 'xg-coupon-ok', '', '');
        }
        $('xg-coupon-go').classList.toggle('on', !!qt.coupon);
        // gift feedback
        if (state.gift && qt.giftError) {
          setMsg('xg-gift-err', 'xg-gift-ok', giftMsg(qt.giftError), '');
        } else if (qt.giftCode) {
          setMsg('xg-gift-err', 'xg-gift-ok', '', T('Applied: ', '適用: ') + yen(qt.giftApplied || 0));
        } else {
          setMsg('xg-gift-err', 'xg-gift-ok', '', '');
        }
        $('xg-gift-go').classList.toggle('on', !!qt.giftCode);

        renderQuote(qt);
      }).catch(function () {
        renderHint(T('Price preview unavailable.', '料金プレビューを取得できませんでした。'));
      });
    }

    /* ---------- debounce ---------- */
    var timer = null;
    function refresh() {
      if (timer) clearTimeout(timer);
      timer = setTimeout(doQuote, 220);
    }
    X.refresh = refresh;

    /* ---------- wiring ---------- */
    function applyCoupon() { state.coupon = couponIn.value.trim().toUpperCase(); refresh(); }
    function applyGift() { state.gift = giftIn.value.trim().toUpperCase(); refresh(); }
    $('xg-coupon-go').onclick = applyCoupon;
    $('xg-gift-go').onclick = applyGift;
    couponIn.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); applyCoupon(); } });
    giftIn.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); applyGift(); } });
    // keep typed value mirrored live (so submit sends what's typed even before Apply)
    couponIn.addEventListener('input', function () { state.coupon = couponIn.value.trim().toUpperCase(); X.coupon = state.coupon; });
    giftIn.addEventListener('input', function () { state.gift = giftIn.value.trim().toUpperCase(); X.gift = state.gift; });

    /* ---------- lightweight selection poll ---------- */
    var lastSig = '';
    setInterval(function () {
      if (!C.currentSelection) return;
      var sig;
      try { sig = JSON.stringify(C.currentSelection()); } catch (e) { return; }
      if (sig !== lastSig) { lastSig = sig; refresh(); }
    }, 1200);

    // initial paint
    try { lastSig = JSON.stringify(C.currentSelection ? C.currentSelection() : {}); } catch (e) {}
    refresh();
  });
})();
