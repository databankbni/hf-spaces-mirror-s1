/* Ashiya Limousine — abandoned-booking recovery / "email me this quote" capture.
   Injects a subtle secondary CTA directly above #submitBk (after the #als-extras
   panel when present). On click it reads the current booking selection, fetches a
   live server-authoritative total (POST /api/pricing/quote, best-effort), and
   captures the lead (POST /api/leads/quote) for follow-up. Bilingual EN/JA,
   self-contained, vanilla JS, never throws. Loads deferred after the main inline
   script and booking-extras.js. */
(function () {
  'use strict';

  if (window.__alsQuoteLeadInit) return;      // guard double-init
  window.__alsQuoteLeadInit = true;

  var C = window.ALSCore || {};
  var EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  var esc = C.esc || function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  };
  var isJA = function () { return (C.L || document.documentElement.lang) === 'ja'; };
  var T = function (en, ja) { return isJA() ? ja : en; };
  // Prefer a real i18n value from ALSCore.tt; fall back to an EN/JA literal.
  var lab = function (key, en, ja) {
    try { if (C.tt) { var v = C.tt(key); if (v && v !== key) return v; } } catch (_) {}
    return T(en, ja);
  };
  var val = function (id) {
    var el = document.getElementById(id);
    return el && typeof el.value === 'string' ? el.value.trim() : '';
  };

  function ready(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }

  ready(function () {
    try { init(); } catch (_) { /* never throw */ }
  });

  function init() {
    var submit = document.getElementById('submitBk');
    if (!submit || !submit.parentNode) return;                       // no-op if absent

    /* ---------- scoped styles (site CSS vars) ---------- */
    var css = document.createElement('style');
    css.textContent =
      '#als-ql{margin:0 0 14px;display:flex;flex-direction:column;gap:9px;text-align:center}' +
      '#als-ql .ql-cta{background:none;border:none;padding:2px 4px;cursor:pointer;' +
        'color:var(--gold2);font-family:inherit;font-size:12.5px;letter-spacing:.04em;' +
        'text-decoration:underline;text-underline-offset:3px;text-decoration-color:var(--line);' +
        'transition:.15s;align-self:center}' +
      '#als-ql .ql-cta:hover{color:var(--gold);text-decoration-color:var(--gold)}' +
      '#als-ql .ql-hint{color:var(--muted);font-size:12px;min-height:0}' +
      '#als-ql .ql-hint.warn{color:var(--gold2)}' +
      '#als-ql .ql-form{display:none;gap:8px;align-items:stretch;width:100%}' +
      '#als-ql .ql-form.show{display:flex}' +
      '#als-ql .ql-form input{flex:1;min-width:0;padding:10px 12px;border-radius:10px;' +
        'border:1px solid var(--line);background:var(--panel);color:var(--cream);' +
        'font-family:inherit;font-size:13px;letter-spacing:.02em}' +
      '#als-ql .ql-form input:focus{outline:none;border-color:var(--gold)}' +
      '#als-ql .ql-send{flex:0 0 auto;padding:0 16px;border-radius:10px;border:1px solid var(--line);' +
        'background:var(--golddim);color:var(--gold2);font-size:12px;letter-spacing:.04em;' +
        'font-weight:700;cursor:pointer;transition:.15s;white-space:nowrap}' +
      '#als-ql .ql-send:hover{background:linear-gradient(130deg,var(--gold),var(--gold2));color:#1b1503;border-color:transparent}' +
      '#als-ql .ql-send[disabled]{opacity:.55;cursor:default}' +
      '#als-ql .ql-done{color:var(--ok,#57D98B);font-size:12.5px;letter-spacing:.02em}';
    document.head.appendChild(css);

    /* ---------- markup ---------- */
    var row = document.createElement('div');
    row.id = 'als-ql';
    row.innerHTML =
      '<button type="button" class="ql-cta" id="ql-cta">' +
        esc(lab('ql_cta', 'Email me this quote', 'この見積をメールで受け取る')) + '</button>' +
      '<div class="ql-form" id="ql-form">' +
        '<input id="ql-mail" type="email" inputmode="email" autocomplete="email" ' +
          'spellcheck="false" placeholder="you@example.com">' +
        '<button type="button" class="ql-send" id="ql-send">' +
          esc(T('Send', '送信')) + '</button>' +
      '</div>' +
      '<div class="ql-hint" id="ql-hint"></div>';
    submit.parentNode.insertBefore(row, submit);   // before #submitBk, after #als-extras

    var $ = function (id) { return document.getElementById(id); };
    var cta = $('ql-cta'), form = $('ql-form'), mailIn = $('ql-mail');
    var sendBtn = $('ql-send'), hint = $('ql-hint');

    function setHint(msg, warn) {
      hint.textContent = msg || '';
      hint.className = 'ql-hint' + (warn ? ' warn' : '');
    }

    function selection() {
      try {
        if (typeof C.currentSelection === 'function') return C.currentSelection() || {};
      } catch (_) {}
      return {};
    }

    cta.addEventListener('click', function () {
      var s = selection();
      if (!s.plan || !s.date) {
        // Gently prompt; do not throw or block.
        setHint(T('Pick a date first and we’ll email your quote.',
                  'まず日付をお選びください。見積をメールでお送りします。'), true);
        return;
      }
      setHint('');
      form.classList.add('show');
      // Reuse an email the guest already typed in the booking form, if any.
      if (!mailIn.value) {
        var existing = val('fMail');
        if (existing) mailIn.value = existing;
      }
      try { mailIn.focus(); } catch (_) {}
    });

    sendBtn.addEventListener('click', function () { submitLead(); });
    mailIn.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); submitLead(); }
    });

    // Best-effort live total from the server; resolves to a number or null.
    function fetchTotal(s) {
      var X = window.ALSExtras || {};
      var payload = {
        plan: s.plan, addons: s.addons || [], pax: s.pax,
        date: s.date, time: s.time,
        couponCode: X.coupon || '', giftCode: X.gift || '', tip: X.tip || 0,
      };
      return fetch('/api/pricing/quote', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(payload),
      }).then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          var t = d && d.quote && d.quote.total;
          return typeof t === 'number' ? t : null;
        })
        .catch(function () { return null; });   // omit total on any failure
    }

    function submitLead() {
      var email = (mailIn.value || '').trim();
      if (!EMAIL_RE.test(email)) {
        setHint(T('Please enter a valid email address.',
                  '有効なメールアドレスをご入力ください。'), true);
        try { mailIn.focus(); } catch (_) {}
        return;
      }
      var s = selection();
      if (!s.plan || !s.date) {
        setHint(T('Pick a date first and we’ll email your quote.',
                  'まず日付をお選びください。見積をメールでお送りします。'), true);
        return;
      }
      setHint('');
      sendBtn.disabled = true;
      mailIn.disabled = true;

      fetchTotal(s).then(function (total) {
        var body = {
          email: email,
          name: val('fName') || '',
          plan: s.plan,
          date: s.date,
          time: s.time || '',
          pax: s.pax != null ? s.pax : null,
          selection: s,
        };
        if (total != null) body.quote_total = total;
        return fetch('/api/leads/quote', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify(body),
        });
      }).then(function (r) {
        return r && r.ok ? r.json() : null;
      }).then(function (d) {
        if (d && d.ok) {
          row.innerHTML = '<div class="ql-done">' +
            esc(lab('ql_ok', 'Sent — we’ll follow up with your quote.',
                    '送信しました。追ってご連絡します。')) + '</div>';
        } else {
          sendBtn.disabled = false;
          mailIn.disabled = false;
          setHint(T('Something went wrong — please try again.',
                    '送信に失敗しました。もう一度お試しください。'), true);
        }
      }).catch(function () {
        sendBtn.disabled = false;
        mailIn.disabled = false;
        setHint(T('Something went wrong — please try again.',
                  '送信に失敗しました。もう一度お試しください。'), true);
      });
    }
  }
})();
