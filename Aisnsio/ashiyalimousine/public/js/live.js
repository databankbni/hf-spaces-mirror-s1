/* Ashiya Limousine — live customer layer: accounts (register/login), My Reservations,
   and deposit payments. Loads after the main inline script and reuses window.ALSCore
   helpers. Self-contained; no external dependencies. */
(function () {
  'use strict';
  var C = window.ALSCore || {};
  var tt = C.tt || function (k) { return k; };
  var yen = C.yen || function (n) { return '¥' + Number(n || 0).toLocaleString('en-US'); };
  var esc = C.esc || function (s) { return String(s == null ? '' : s); };
  var openModal = C.openModal || function (id) { var e = document.getElementById(id); if (e) e.classList.add('open'); };
  var closeModal = C.closeModal || function (id) { var e = document.getElementById(id); if (e) e.classList.remove('open'); };
  var isJA = function () { return (C.L || document.documentElement.lang) === 'ja'; };
  var T = function (en, ja) { return isJA() ? ja : en; };

  var api = function (path, opts) {
    opts = opts || {};
    return fetch(path, {
      method: opts.method || 'GET',
      headers: opts.body ? { 'content-type': 'application/json' } : undefined,
      credentials: 'include',
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, status: r.status, data: d }; }); });
  };
  var toast = function (msg) {
    var el = document.getElementById('toastMsg'), box = document.getElementById('toast');
    if (el && box) { el.textContent = msg; box.classList.add('show'); setTimeout(function () { box.classList.remove('show'); }, 3400); }
  };

  var state = { user: null, payEnabled: false };

  /* ---------- injected styles + markup ---------- */
  var css = document.createElement('style');
  css.textContent =
    '#alsAuthModal .modal,#alsMineModal .modal{max-width:440px;text-align:left}' +
    '.als-tabs{display:flex;gap:8px;margin-bottom:16px}' +
    '.als-tabs button{flex:1;padding:9px;border-radius:9px;border:1px solid var(--line);background:transparent;color:var(--muted);font-size:12px;letter-spacing:.04em;font-weight:700}' +
    '.als-tabs button.on{background:var(--golddim);border-color:var(--gold);color:var(--gold2)}' +
    '.als-field{display:block;margin-bottom:11px}' +
    '.als-field span{display:block;font-size:11px;letter-spacing:.05em;color:var(--faint);text-transform:uppercase;margin-bottom:5px}' +
    '.als-field input{width:100%;padding:11px 13px;border-radius:10px;border:1px solid var(--line);background:var(--panel);color:var(--cream);font-size:14px}' +
    '.als-err{color:var(--bad);font-size:12.5px;min-height:16px;margin:2px 0 8px}' +
    '.als-mine-row{border:1px solid var(--hair);border-radius:12px;padding:13px 14px;margin-bottom:11px}' +
    '.als-mine-row .top{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:6px}' +
    '.als-mine-row .ref{font-family:var(--mono);font-size:11px;color:var(--faint);letter-spacing:.08em}' +
    '.als-mine-row .pv{font-weight:600;color:var(--cream)}' +
    '.als-mine-row .sub{color:var(--muted);font-size:12.5px}' +
    '.als-mine-row .amt{font-family:var(--mono);color:var(--gold2)}' +
    '.als-mine-empty{color:var(--muted);text-align:center;padding:26px 0}' +
    '#okActions{display:flex;flex-direction:column;gap:9px;margin:4px 0 12px}';
  document.head.appendChild(css);

  var wrap = document.createElement('div');
  wrap.innerHTML =
    '<div class="modal-bg" id="alsAuthModal"><div class="modal">' +
    '<button class="x" id="alsAuthX"><svg><use href="#i-x"/></svg></button>' +
    '<h3 style="text-align:left" id="alsAuthTitle">Account</h3>' +
    '<p class="msub" style="text-align:left" id="alsAuthSub">Track your reservations and pay online.</p>' +
    '<div class="als-tabs"><button data-mode="login" class="on" id="alsTabLogin">Sign in</button><button data-mode="register" id="alsTabReg">Create account</button></div>' +
    '<label class="als-field" id="alsNameField"><span id="alsNameLbl">Full name</span><input id="alsName" autocomplete="name"></label>' +
    '<label class="als-field"><span id="alsEmailLbl">Email</span><input id="alsEmail" type="email" autocomplete="email"></label>' +
    '<label class="als-field" id="alsPhoneField"><span id="alsPhoneLbl">Phone</span><input id="alsPhone" autocomplete="tel"></label>' +
    '<label class="als-field"><span id="alsPwLbl">Password</span><input id="alsPw" type="password" autocomplete="current-password"></label>' +
    '<div class="als-err" id="alsAuthErr"></div>' +
    '<button class="btn btn-gold" style="width:100%" id="alsAuthGo">Sign in</button>' +
    '</div></div>' +
    '<div class="modal-bg" id="alsMineModal"><div class="modal">' +
    '<button class="x" id="alsMineX"><svg><use href="#i-x"/></svg></button>' +
    '<h3 style="text-align:left" id="alsMineTitle">My reservations</h3>' +
    '<p class="msub" style="text-align:left" id="alsMineSub"></p>' +
    '<div id="alsMineList"></div>' +
    '<button class="btn btn-dim btn-sm" style="width:100%;margin-top:6px" id="alsLogout">Log out</button>' +
    '</div></div>';
  document.body.appendChild(wrap);

  var $ = function (id) { return document.getElementById(id); };
  $('alsAuthX').onclick = function () { closeModal('alsAuthModal'); };
  $('alsMineX').onclick = function () { closeModal('alsMineModal'); };
  [$('alsAuthModal'), $('alsMineModal')].forEach(function (m) {
    m.addEventListener('click', function (e) { if (e.target === m) m.classList.remove('open'); });
  });

  var mode = 'login';
  function setMode(m) {
    mode = m;
    $('alsTabLogin').classList.toggle('on', m === 'login');
    $('alsTabReg').classList.toggle('on', m === 'register');
    $('alsNameField').style.display = m === 'register' ? 'block' : 'none';
    $('alsPhoneField').style.display = m === 'register' ? 'block' : 'none';
    $('alsPw').setAttribute('autocomplete', m === 'register' ? 'new-password' : 'current-password');
    $('alsAuthGo').textContent = m === 'register' ? T('Create account', 'アカウント作成') : T('Sign in', 'サインイン');
    $('alsAuthErr').textContent = '';
  }
  $('alsTabLogin').onclick = function () { setMode('login'); };
  $('alsTabReg').onclick = function () { setMode('register'); };

  function localizeAuth() {
    $('alsAuthTitle').textContent = T('Account', 'アカウント');
    $('alsAuthSub').textContent = T('Track your reservations and pay online.', 'ご予約の管理とオンライン決済ができます。');
    $('alsTabLogin').textContent = T('Sign in', 'サインイン');
    $('alsTabReg').textContent = T('Create account', 'アカウント作成');
    $('alsNameLbl').textContent = T('Full name', 'お名前');
    $('alsEmailLbl').textContent = T('Email', 'メールアドレス');
    $('alsPhoneLbl').textContent = T('Phone', 'お電話番号');
    $('alsPwLbl').textContent = T('Password', 'パスワード');
    $('alsMineTitle').textContent = T('My reservations', 'ご予約一覧');
    $('alsLogout').textContent = T('Log out', 'ログアウト');
    setMode(mode);
  }

  function openAuth(preMode) {
    localizeAuth();
    setMode(preMode || 'login');
    $('alsAuthErr').textContent = '';
    openModal('alsAuthModal');
    setTimeout(function () { $(mode === 'register' ? 'alsName' : 'alsEmail').focus(); }, 80);
  }

  $('alsAuthGo').onclick = function () {
    var email = $('alsEmail').value.trim(), pw = $('alsPw').value;
    var errEl = $('alsAuthErr');
    if (!email || !pw) { errEl.textContent = T('Enter your email and password.', 'メールとパスワードを入力してください。'); return; }
    var path, body;
    if (mode === 'register') {
      var name = $('alsName').value.trim();
      if (!name) { errEl.textContent = T('Enter your name.', 'お名前を入力してください。'); return; }
      if (pw.length < 8) { errEl.textContent = T('Password must be at least 8 characters.', 'パスワードは8文字以上にしてください。'); return; }
      var _ref = ''; try { _ref = new URLSearchParams(location.search).get('ref') || localStorage.getItem('als-ref') || ''; } catch (e) {}
      path = '/api/auth/register'; body = { email: email, password: pw, name: name, phone: $('alsPhone').value.trim(), ref: _ref };
    } else {
      path = '/api/auth/login'; body = { email: email, password: pw };
    }
    $('alsAuthGo').disabled = true;
    api(path, { method: 'POST', body: body }).then(function (res) {
      $('alsAuthGo').disabled = false;
      if (res.ok && res.data && res.data.ok) {
        state.user = res.data.user;
        updateAccountUI();
        closeModal('alsAuthModal');
        $('alsPw').value = '';
        toast(T('Signed in — welcome.', 'サインインしました。'));
      } else {
        var e = res.data && res.data.error;
        errEl.textContent = e === 'email_taken' ? T('That email is already registered.', 'このメールは登録済みです。')
          : e === 'bad_credentials' ? T('Email or password is incorrect.', 'メールまたはパスワードが違います。')
          : T('Something went wrong. Please try again.', 'エラーが発生しました。もう一度お試しください。');
      }
    }).catch(function () { $('alsAuthGo').disabled = false; errEl.textContent = T('Network error.', '通信エラーです。'); });
  };

  $('alsLogout').onclick = function () {
    api('/api/auth/logout', { method: 'POST' }).then(function () {
      state.user = null; updateAccountUI(); closeModal('alsMineModal');
      toast(T('Logged out.', 'ログアウトしました。'));
    });
  };

  /* ---------- account nav button ---------- */
  function acctLabel() {
    if (!state.user) return T('Account', 'アカウント');
    var n = (state.user.name || state.user.email || '').split(' ')[0];
    return (isJA() ? n + ' さん' : n) || T('Account', 'アカウント');
  }
  function updateAccountUI() {
    ['acctLink', 'acctLinkM'].forEach(function (id) {
      var el = $(id); if (el) el.textContent = acctLabel();
    });
  }
  function acctClick(e) {
    if (e) e.preventDefault();
    var mm = $('mMenu'); if (mm) mm.classList.remove('open');
    if (state.user) { openMine(); } else { openAuth('login'); }
  }
  ['acctLink', 'acctLinkM'].forEach(function (id) { var el = $(id); if (el) el.onclick = acctClick; });

  /* ---------- My Reservations ---------- */
  function statusLabel(s) { return tt('st_' + s) || s; }
  function planLabel(id) { return C.planName ? C.planName(id) : id; }
  function vehLabel(id) { return C.vehName ? C.vehName(id) : id; }
  function fmtD(ds) { return C.fmtDate ? C.fmtDate(ds) : ds; }
  var pill = C.pillCls || { pending: 'warn', confirmed: 'ok', completed: 'info', declined: 'bad', cancelled: 'bad' };

  function payButton(b) {
    if (b.pay_status === 'paid') return '';
    if (b.status === 'declined' || b.status === 'cancelled') return '';
    var kind = b.pay_status === 'deposit_paid' ? 'full' : 'deposit';
    var amt = kind === 'full' ? (b.total - Math.round(b.total * 0.3)) : (b.deposit || Math.round(b.total * 0.3));
    var label = kind === 'full' ? T('Pay balance', '残金を支払う') : T('Pay deposit', '内金を支払う');
    return '<button class="btn btn-gold btn-sm" data-pay="' + esc(b.ref) + '" data-kind="' + kind + '">' +
      label + ' · ' + yen(amt) + '</button>';
  }

  function openMine() {
    openModal('alsMineModal');
    $('alsMineSub').textContent = state.user ? (state.user.email || '') : '';
    var list = $('alsMineList');
    list.innerHTML = '<div class="als-mine-empty">' + T('Loading…', '読み込み中…') + '</div>';
    api('/api/bookings/mine').then(function (res) {
      if (res.status === 401) { closeModal('alsMineModal'); state.user = null; updateAccountUI(); openAuth('login'); return; }
      var bs = (res.data && res.data.bookings) || [];
      if (!bs.length) { list.innerHTML = '<div class="als-mine-empty">' + T('No reservations yet.', 'まだご予約はありません。') + '</div>'; return; }
      list.innerHTML = bs.map(function (b) {
        return '<div class="als-mine-row">' +
          '<div class="top"><span class="ref">' + esc(b.ref) + '</span>' +
          '<span class="pill ' + (pill[b.status] || 'info') + '">' + statusLabel(b.status) + '</span></div>' +
          '<div class="pv">' + esc(planLabel(b.plan)) + '</div>' +
          '<div class="sub">' + fmtD(b.date) + ' · ' + esc(b.time) + ' · ' + esc(vehLabel(b.veh)) + '</div>' +
          '<div class="top" style="margin-top:8px"><span class="amt">' + yen(b.total) + '</span>' + payButton(b) + '</div>' +
          '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px">' +
            '<button class="btn btn-ghost btn-sm" data-inv="' + esc(b.ref) + '">' + T('Invoice', '請求書') + '</button>' +
            ((b.status === 'pending' || b.status === 'confirmed') ? '<button class="btn btn-ghost btn-sm" data-resched="' + esc(b.ref) + '">' + T('Reschedule', '日程変更') + '</button>' : '') +
            ((b.status !== 'completed' && b.status !== 'cancelled') ? '<button class="btn btn-dim btn-sm" data-cancel="' + esc(b.ref) + '">' + T('Cancel', 'キャンセル') + '</button>' : '') +
          '</div>' +
          '</div>';
      }).join('');
      list.querySelectorAll('[data-pay]').forEach(function (btn) {
        btn.onclick = function () { pay(btn.getAttribute('data-pay'), btn.getAttribute('data-kind')); };
      });
      list.querySelectorAll('[data-inv]').forEach(function (btn) {
        btn.onclick = function () { window.open('/api/selfservice/invoice/' + encodeURIComponent(btn.getAttribute('data-inv')), '_blank'); };
      });
      list.querySelectorAll('[data-resched]').forEach(function (btn) {
        btn.onclick = function () { reschedule(btn.getAttribute('data-resched')); };
      });
      list.querySelectorAll('[data-cancel]').forEach(function (btn) {
        btn.onclick = function () { cancelBooking(btn.getAttribute('data-cancel')); };
      });
    }).catch(function () { list.innerHTML = '<div class="als-mine-empty">' + T('Could not load.', '読み込めませんでした。') + '</div>'; });
  }

  /* ---------- payments ---------- */
  function pay(ref, kind) {
    api('/api/payments/checkout', { method: 'POST', body: { ref: ref, kind: kind || 'deposit' } }).then(function (res) {
      if (res.status === 401) { openAuth('login'); return; }
      var d = res.data || {};
      if (d.ok && d.url) { window.location.href = d.url; return; }
      if (d.ok && d.manual) { toast(d.message || T('We will send payment details shortly.', '追ってお支払い方法をご案内します。')); return; }
      toast(T('Could not start payment.', '決済を開始できませんでした。'));
    }).catch(function () { toast(T('Network error.', '通信エラーです。')); });
  }

  /* ---------- self-service (reschedule / cancel) ---------- */
  function reschedule(ref) {
    var date = prompt(T('New date (YYYY-MM-DD):', '新しい日付 (YYYY-MM-DD):'));
    if (!date) return;
    var time = prompt(T('New time (HH:MM):', '新しい時間 (HH:MM):'));
    if (!time) return;
    api('/api/selfservice/reschedule', { method: 'POST', body: { ref: ref, date: date, time: time } }).then(function (res) {
      var d = res.data || {};
      if (d.ok) { toast(T('Reservation updated.', '予約を更新しました。')); openMine(); }
      else if (d.error === 'slot_taken') toast(T('That slot is already taken.', 'その時間はすでに予約済みです。'));
      else toast(T('Could not reschedule.', '変更できませんでした。'));
    }).catch(function () { toast(T('Network error.', '通信エラーです。')); });
  }
  function cancelBooking(ref) {
    if (!confirm(T('Cancel this reservation? This cannot be undone.', 'この予約をキャンセルしますか？（取り消せません）'))) return;
    api('/api/selfservice/cancel', { method: 'POST', body: { ref: ref } }).then(function (res) {
      var d = res.data || {};
      if (d.ok) { toast(d.policy_note || T('Reservation cancelled.', 'キャンセルしました。')); openMine(); }
      else toast(T('Could not cancel.', 'キャンセルできませんでした。'));
    }).catch(function () { toast(T('Network error.', '通信エラーです。')); });
  }

  /* Called by index.html right after a booking is created. */
  window.ALS = {
    afterBooking: function (bk) {
      var box = document.getElementById('okActions');
      if (!box) return;
      var dep = bk.deposit || Math.round((bk.total || 0) * 0.3);
      var html = '';
      if (state.user) {
        if (state.payEnabled) {
          html += '<button class="btn btn-gold" style="width:100%" id="okPay">' +
            T('Pay deposit now', '内金を支払う') + ' · ' + yen(dep) + '</button>';
        }
        html += '<button class="btn btn-ghost btn-sm" style="width:100%" id="okMine">' +
          T('View my reservations', 'ご予約一覧を見る') + '</button>';
      } else {
        html += '<button class="btn btn-gold" style="width:100%" id="okReg">' +
          T('Create an account to track & pay', 'アカウントを作成して管理・支払い') + '</button>';
        html += '<div class="msub" style="margin:2px 0 0">' +
          T('Deposit due after we confirm: ', '確定後の内金: ') + yen(dep) + '</div>';
      }
      box.innerHTML = html;
      var p = document.getElementById('okPay'); if (p) p.onclick = function () { pay(bk.ref, 'deposit'); };
      var m = document.getElementById('okMine'); if (m) m.onclick = function () { closeModal('okModal'); openMine(); };
      var r = document.getElementById('okReg'); if (r) r.onclick = function () { closeModal('okModal'); openAuth('register'); };
    },
    openAuth: openAuth,
    openMine: openMine,
  };

  /* ---------- boot ---------- */
  function refreshLang() { updateAccountUI(); }
  document.querySelectorAll('#langTg button,#langTgA button').forEach(function (b) {
    b.addEventListener('click', function () { setTimeout(refreshLang, 20); });
  });

  try { var _r = new URLSearchParams(location.search).get('ref'); if (_r) localStorage.setItem('als-ref', _r); } catch (e) {}
  api('/api/payments/config').then(function (res) { state.payEnabled = !!(res.data && res.data.enabled); }).catch(function () {});
  api('/api/auth/me').then(function (res) {
    if (res.data && res.data.ok && res.data.user) state.user = res.data.user;
    updateAccountUI();
  }).catch(function () { updateAccountUI(); });

  /* payment return from Stripe: ?paid=REF */
  try {
    var qs = new URLSearchParams(location.search);
    if (qs.get('paid')) {
      toast(T('Payment received — thank you!', 'お支払いを受け付けました。ありがとうございます。'));
      history.replaceState(null, '', location.pathname);
      setTimeout(function () { if (state.user) openMine(); }, 600);
    }
  } catch (e) {}
})();
