/* Ashiya Limousine — customer e-signature for the digital service agreement.
 * Owns modal #als-contract. Detects ?sign=<token>, fetches the contract,
 * renders booking summary + numbered terms, captures name + agree + signature.
 * Depends on window.ALSCore = { L, tt, esc, yen, openModal, closeModal }.
 * Loaded via <script defer> after the main inline script. */
(function () {
  "use strict";
  if (window.__alsContractInit) return;
  window.__alsContractInit = true;

  var MODAL_ID = "als-contract";

  /* ---- safe access to core helpers (never throw if core is late/missing) ---- */
  function core() { return window.ALSCore || {}; }
  function isJA() { try { return core().L === "ja"; } catch (e) { return false; } }
  function esc(s) {
    try { if (core().esc) return core().esc(s); } catch (e) {}
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function yen(n) {
    try { if (core().yen) return core().yen(n); } catch (e) {}
    var v = Number(n);
    return "¥" + (isFinite(v) ? v.toLocaleString("en-US") : "0");
  }
  function openModal(id) {
    try { if (core().openModal) { core().openModal(id); return; } } catch (e) {}
    var el = document.getElementById(id); if (el) el.classList.add("open");
  }
  function closeModal(id) {
    try { if (core().closeModal) { core().closeModal(id); return; } } catch (e) {}
    var el = document.getElementById(id); if (el) el.classList.remove("open");
  }
  function toast(msg) {
    try { if (typeof window.toast === "function") { window.toast(msg); return; } } catch (e) {}
    try { if (core().toast) { core().toast(msg); return; } } catch (e) {}
  }

  /* ---- i18n strings ---- */
  function T() {
    var ja = isJA();
    return {
      title: ja ? "利用規約への署名" : "Service agreement",
      sub: ja ? "ご予約内容をご確認のうえ、下記に同意して署名してください。"
             : "Please review your reservation and the terms below, then sign to confirm.",
      booking: ja ? "ご予約内容" : "Reservation",
      terms: ja ? "利用規約" : "Terms of service",
      termsIntro: ja ? "以下の各項目をご確認ください。" : "Please read each of the following terms.",
      name: ja ? "ご署名（フルネーム）" : "Full name",
      namePh: ja ? "山田 太郎" : "Your full legal name",
      agree: ja ? "上記に同意します" : "I agree to these terms",
      sign: ja ? "署名する" : "Sign",
      errName: ja ? "お名前をご入力ください。" : "Please enter your full name.",
      errAgree: ja ? "規約への同意にチェックを入れてください。" : "Please check the box to agree.",
      errNet: ja ? "送信に失敗しました。もう一度お試しください。" : "Could not submit. Please try again.",
      errLoad: ja ? "契約情報を読み込めませんでした。" : "Could not load this agreement.",
      signing: ja ? "送信中…" : "Signing…",
      thanks: ja ? "ありがとうございます — 同意を記録しました。" : "Thank you — your agreement is recorded.",
      toastDone: ja ? "規約に署名しました。" : "Agreement signed.",
      signedBy: ja ? "署名済み" : "Signed",
      close: ja ? "閉じる" : "Close",
      lRef: ja ? "予約番号" : "Reference",
      lPlan: ja ? "プラン" : "Plan",
      lDate: ja ? "日付" : "Date",
      lTime: ja ? "時間" : "Time",
      lVeh: ja ? "車両" : "Vehicle",
      lPax: ja ? "人数" : "Guests",
      lTotal: ja ? "合計" : "Total",
      lDeposit: ja ? "手付金" : "Deposit"
    };
  }

  /* ---- style + modal injection ---- */
  function injectStyle() {
    if (document.getElementById("als-contract-style")) return;
    var css =
      "#" + MODAL_ID + " .alsc{width:100%;max-width:520px;border:1px solid var(--line,rgba(212,175,55,.22));border-radius:18px;" +
      "background:linear-gradient(170deg,#151B33,var(--ink2,#0F1425) 75%);padding:30px 30px 26px;position:relative;" +
      "max-height:88vh;overflow-y:auto;text-align:left;color:var(--cream,#F3EDDC);font-family:var(--sans,sans-serif);" +
      "animation:alscPop .3s cubic-bezier(.2,.9,.3,1.2)}" +
      "@keyframes alscPop{from{transform:scale(.95) translateY(10px);opacity:0}to{transform:none;opacity:1}}" +
      "#" + MODAL_ID + " .alsc-x{position:absolute;top:13px;right:13px;width:32px;height:32px;border-radius:9px;" +
      "border:1px solid var(--hair,rgba(243,237,220,.09));display:grid;place-items:center;color:var(--muted,#98A0B8);" +
      "font-size:16px;line-height:1;transition:.15s;background:none}" +
      "#" + MODAL_ID + " .alsc-x:hover{color:var(--cream,#F3EDDC);border-color:var(--line,rgba(212,175,55,.22))}" +
      "#" + MODAL_ID + " .alsc-eyebrow{font-family:var(--mono,monospace);font-size:10px;letter-spacing:.24em;" +
      "text-transform:uppercase;color:var(--gold,#D4AF37);margin-bottom:6px}" +
      "#" + MODAL_ID + " h3.alsc-h{font-family:var(--serif,serif);font-size:26px;font-weight:600;color:var(--gold2,#F1DFA6);" +
      "line-height:1.15;margin:0 0 8px}" +
      "#" + MODAL_ID + " .alsc-sub{font-size:13px;color:var(--muted,#98A0B8);margin-bottom:18px;line-height:1.55}" +
      "#" + MODAL_ID + " .alsc-sec{font-family:var(--mono,monospace);font-size:10px;letter-spacing:.2em;text-transform:uppercase;" +
      "color:var(--gold,#D4AF37);margin:20px 0 9px}" +
      "#" + MODAL_ID + " .alsc-sum{border:1px solid var(--line,rgba(212,175,55,.22));border-radius:12px;overflow:hidden}" +
      "#" + MODAL_ID + " .alsc-row{display:flex;justify-content:space-between;gap:14px;padding:8px 14px;font-size:13.5px}" +
      "#" + MODAL_ID + " .alsc-row:nth-child(odd){background:var(--panel,rgba(255,255,255,.028))}" +
      "#" + MODAL_ID + " .alsc-row .k{color:var(--muted,#98A0B8)}" +
      "#" + MODAL_ID + " .alsc-row .v{color:var(--cream,#F3EDDC);text-align:right;font-weight:500}" +
      "#" + MODAL_ID + " .alsc-row.tot .v{color:var(--gold2,#F1DFA6);font-family:var(--mono,monospace)}" +
      "#" + MODAL_ID + " ol.alsc-terms{margin:0;padding-left:20px;font-size:13px;color:var(--cream,#F3EDDC);line-height:1.6}" +
      "#" + MODAL_ID + " ol.alsc-terms li{margin-bottom:7px}" +
      "#" + MODAL_ID + " ol.alsc-terms li::marker{color:var(--gold,#D4AF37);font-family:var(--mono,monospace);font-size:11px}" +
      "#" + MODAL_ID + " .alsc-lbl{display:block;font-size:11px;letter-spacing:.14em;text-transform:uppercase;" +
      "color:var(--muted,#98A0B8);margin:16px 0 6px}" +
      "#" + MODAL_ID + " .alsc-in{width:100%;background:var(--ink,#0A0D18);border:1px solid var(--line,rgba(212,175,55,.22));" +
      "border-radius:10px;padding:11px 13px;color:var(--cream,#F3EDDC);font-family:var(--serif,serif);font-size:18px}" +
      "#" + MODAL_ID + " .alsc-in:focus{outline:none;border-color:var(--gold,#D4AF37)}" +
      "#" + MODAL_ID + " .alsc-agree{display:flex;align-items:flex-start;gap:10px;margin:16px 0 4px;font-size:13.5px;" +
      "color:var(--cream,#F3EDDC);cursor:pointer;line-height:1.45}" +
      "#" + MODAL_ID + " .alsc-agree input{margin-top:3px;width:16px;height:16px;accent-color:var(--gold,#D4AF37);flex-shrink:0;cursor:pointer}" +
      "#" + MODAL_ID + " .alsc-err{color:var(--bad,#F26D6D);font-size:12.5px;margin:10px 0 0;min-height:1px}" +
      "#" + MODAL_ID + " .alsc-btn{width:100%;margin-top:18px;padding:13px;border-radius:11px;font-weight:700;font-size:14px;" +
      "letter-spacing:.02em;color:#1b1503;background:linear-gradient(120deg,var(--gold,#D4AF37),var(--gold2,#F1DFA6) 55%,var(--gold,#D4AF37));" +
      "border:none;cursor:pointer;transition:.18s}" +
      "#" + MODAL_ID + " .alsc-btn:hover{filter:brightness(1.06)}" +
      "#" + MODAL_ID + " .alsc-btn[disabled]{opacity:.55;cursor:default}" +
      "#" + MODAL_ID + " .alsc-done{border:1px solid var(--ok,#57D98B);background:var(--okbg,rgba(87,217,139,.12));" +
      "border-radius:12px;padding:16px 16px;margin-top:18px;font-size:14px;color:var(--cream,#F3EDDC);display:flex;gap:11px;align-items:flex-start}" +
      "#" + MODAL_ID + " .alsc-done .ic{color:var(--ok,#57D98B);font-size:18px;line-height:1;margin-top:1px}" +
      "#" + MODAL_ID + " .alsc-done small{display:block;color:var(--muted,#98A0B8);font-size:12px;margin-top:4px}";
    var st = document.createElement("style");
    st.id = "als-contract-style";
    st.textContent = css;
    document.head.appendChild(st);
  }

  function ensureModal() {
    injectStyle();
    var m = document.getElementById(MODAL_ID);
    if (m) return m;
    m = document.createElement("div");
    m.className = "modal-bg";
    m.id = MODAL_ID;
    m.setAttribute("role", "dialog");
    m.setAttribute("aria-modal", "true");
    m.innerHTML =
      '<div class="alsc" role="document">' +
      '<button class="alsc-x" type="button" data-alsc-close aria-label="Close">✕</button>' +
      '<div class="alsc-body"></div>' +
      "</div>";
    document.body.appendChild(m);

    // close on X + backdrop
    m.addEventListener("click", function (e) {
      if (e.target === m || (e.target.closest && e.target.closest("[data-alsc-close]"))) {
        closeModal(MODAL_ID);
      }
    });
    return m;
  }

  // Escape key
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      var m = document.getElementById(MODAL_ID);
      if (m && m.classList.contains("open")) closeModal(MODAL_ID);
    }
  });

  function body() {
    var m = ensureModal();
    return m.querySelector(".alsc-body");
  }

  /* ---- rendering ---- */
  function row(k, v) {
    if (v == null || v === "") return "";
    return '<div class="alsc-row"><span class="k">' + esc(k) + '</span><span class="v">' + esc(v) + "</span></div>";
  }

  function summaryHTML(c, t) {
    var rows =
      row(t.lRef, c.ref) +
      row(t.lPlan, c.plan_name_en) +
      row(t.lDate, c.date) +
      row(t.lTime, c.time) +
      row(t.lVeh, c.veh) +
      row(t.lPax, c.pax);
    var money = "";
    if (c.total != null && c.total !== "") {
      money += '<div class="alsc-row tot"><span class="k">' + esc(t.lTotal) + '</span><span class="v">' + esc(yen(c.total)) + "</span></div>";
    }
    if (c.deposit != null && c.deposit !== "") {
      money += '<div class="alsc-row"><span class="k">' + esc(t.lDeposit) + '</span><span class="v">' + esc(yen(c.deposit)) + "</span></div>";
    }
    return '<div class="alsc-sec">' + esc(t.booking) + '</div><div class="alsc-sum">' + rows + money + "</div>";
  }

  function termsHTML(terms, t) {
    if (!terms || !terms.length) return "";
    var items = "";
    for (var i = 0; i < terms.length; i++) {
      items += "<li>" + esc(terms[i]) + "</li>";
    }
    return '<div class="alsc-sec">' + esc(t.terms) + '</div><p class="alsc-sub" style="margin-bottom:10px">' +
      esc(t.termsIntro) + '</p><ol class="alsc-terms">' + items + "</ol>";
  }

  function headHTML(t) {
    return '<div class="alsc-eyebrow">Ashiya Limousine</div>' +
      '<h3 class="alsc-h">' + esc(t.title) + "</h3>" +
      '<p class="alsc-sub">' + esc(t.sub) + "</p>";
  }

  function signedHTML(c, t) {
    var who = c.signer_name ? esc(c.signer_name) : "";
    var when = c.signed_at ? esc(c.signed_at) : "";
    var line = t.signedBy;
    if (when) line += " · " + when;
    if (who) line += " · " + who;
    return '<div class="alsc-done"><span class="ic">✓</span><div>' + esc(t.thanks) +
      "<small>" + line + "</small></div></div>";
  }

  function formHTML(t) {
    return '<label class="alsc-lbl" for="alsc-name">' + esc(t.name) + "</label>" +
      '<input id="alsc-name" class="alsc-in" type="text" autocomplete="name" placeholder="' + esc(t.namePh) + '">' +
      '<label class="alsc-agree"><input id="alsc-agree" type="checkbox"><span>' + esc(t.agree) + "</span></label>" +
      '<p class="alsc-err" id="alsc-err"></p>' +
      '<button class="alsc-btn" id="alsc-sign" type="button">' + esc(t.sign) + "</button>";
  }

  function renderContract(token, contract, terms) {
    var t = T();
    var c = contract || {};
    var signed = c.status === "signed";
    var html = headHTML(t) + summaryHTML(c, t) + termsHTML(terms, t);
    html += signed ? signedHTML(c, t) : formHTML(t);
    var b = body();
    b.innerHTML = html;
    openModal(MODAL_ID);
    if (!signed) wireForm(token, t);
  }

  function wireForm(token, t) {
    var b = body();
    var btn = b.querySelector("#alsc-sign");
    var nameEl = b.querySelector("#alsc-name");
    var agreeEl = b.querySelector("#alsc-agree");
    var errEl = b.querySelector("#alsc-err");
    if (!btn) return;
    if (nameEl) try { nameEl.focus(); } catch (e) {}

    function err(msg) { if (errEl) errEl.textContent = msg || ""; }

    btn.addEventListener("click", function () {
      err("");
      var name = nameEl ? nameEl.value.trim() : "";
      if (!name) { err(t.errName); if (nameEl) nameEl.focus(); return; }
      if (!agreeEl || !agreeEl.checked) { err(t.errAgree); return; }

      btn.disabled = true;
      var prev = btn.textContent;
      btn.textContent = t.signing;

      submitSign(token, name).then(function (ok) {
        if (ok) {
          b.innerHTML = headHTML(t) +
            '<div class="alsc-done"><span class="ic">✓</span><div>' + esc(t.thanks) + "</div></div>" +
            '<button class="alsc-btn" type="button" data-alsc-close style="background:none;border:1px solid var(--line,rgba(212,175,55,.22));color:var(--gold2,#F1DFA6)">' +
            esc(t.close) + "</button>";
          toast(t.toastDone);
          cleanUrl();
        } else {
          btn.disabled = false;
          btn.textContent = prev;
          err(t.errNet);
        }
      });
    });
  }

  function submitSign(token, name) {
    return fetch("/api/contracts/" + encodeURIComponent(token) + "/sign", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify({ signer_name: name, agreed: true })
    }).then(function (r) {
      return r.json().catch(function () { return {}; });
    }).then(function (d) {
      return !!(d && d.ok);
    }).catch(function () { return false; });
  }

  function loadContract(token) {
    return fetch("/api/contracts/" + encodeURIComponent(token), {
      credentials: "include",
      headers: { "Accept": "application/json" }
    }).then(function (r) {
      return r.json().catch(function () { return {}; });
    }).catch(function () { return {}; });
  }

  function open(token) {
    if (!token) return;
    ensureModal();
    loadContract(token).then(function (d) {
      if (d && d.ok && d.contract) {
        renderContract(token, d.contract, d.terms || []);
      } else {
        var t = T();
        var b = body();
        b.innerHTML = headHTML(t) +
          '<p class="alsc-err" style="min-height:auto">' + esc(t.errLoad) + "</p>" +
          '<button class="alsc-btn" type="button" data-alsc-close style="background:none;border:1px solid var(--line,rgba(212,175,55,.22));color:var(--gold2,#F1DFA6)">' +
          esc(t.close) + "</button>";
        openModal(MODAL_ID);
      }
    }).catch(function () {});
  }

  function cleanUrl() {
    try {
      var u = new URL(location.href);
      if (u.searchParams.has("sign")) {
        u.searchParams.delete("sign");
        history.replaceState(null, "", u.pathname + (u.search ? u.search : "") + u.hash);
      }
    } catch (e) {}
  }

  /* ---- public API ---- */
  window.ALS = window.ALS || {};
  window.ALS.openContract = function (token) {
    try { open(token); } catch (e) {}
  };

  /* ---- boot: detect ?sign=<token> ---- */
  function boot() {
    var token = null;
    try { token = new URLSearchParams(location.search).get("sign"); } catch (e) { token = null; }
    if (!token) return; // no param -> do nothing
    try { open(token); } catch (e) {}
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { try { boot(); } catch (e) {} });
  } else {
    try { boot(); } catch (e) {}
  }
})();
