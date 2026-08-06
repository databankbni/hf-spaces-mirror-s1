/* Ashiya Limousine — Corporate accounts (B2B) */
/* Owns: public/js/corporate.js — loads via <script defer> after main inline script. */
(function () {
  "use strict";
  if (window.__ALS_CORPORATE__) return;
  window.__ALS_CORPORATE__ = true;

  var C = window.ALSCore || {};

  // Local escape fallback so we never depend on ALSCore being complete.
  var esc =
    typeof C.esc === "function"
      ? C.esc
      : function (s) {
          return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
          });
        };

  // Local i18n fallback (matches the site dictionary keys, degrades gracefully).
  function isJa() {
    try {
      if (C && C.L) return C.L === "ja";
    } catch (e) {}
    return (document.documentElement.getAttribute("lang") || "").toLowerCase() === "ja";
  }

  var LOCAL = {
    en: {
      corp_eb: "For business",
      corp_h: "Corporate accounts &<br>monthly invoicing.",
      corp_cta: "Request a corporate account",
      corp_sub: "Move your executives, guests and events with one trusted operator across Kansai.",
      corp_p1t: "Monthly consolidated invoicing",
      corp_p1d: "Every ride on a single itemised statement — no per-trip settlements.",
      corp_p2t: "Priority dispatch",
      corp_p2d: "Your account is held first in the queue for peak dates and last-minute requests.",
      corp_p3t: "Negotiated corporate rates",
      corp_p3d: "Volume pricing and fixed airport transfers tailored to your travel pattern.",
      corp_form_h: "Request a corporate account",
      corp_form_sub: "Tell us a little about your company. Our team replies within one business day.",
      corp_company: "Company",
      corp_contact: "Contact name",
      corp_email: "Email",
      corp_phone: "Phone",
      corp_monthly: "Estimated rides / month",
      corp_note: "Notes (optional)",
      corp_m1: "1–3 rides/mo",
      corp_m2: "4–10",
      corp_m3: "10+",
      corp_submit: "Submit application",
      corp_sending: "Sending…",
      corp_req: "Please enter your company and an email or phone.",
      corp_err: "Something went wrong. Please try again or call us.",
      corp_ok_h: "Thank you",
      corp_ok_sub: "Thank you — our team will contact you about your corporate account.",
      corp_close: "Close",
    },
    ja: {
      corp_eb: "法人のお客様へ",
      corp_h: "法人契約・<br>月次請求書払い。",
      corp_cta: "法人アカウントを申請",
      corp_sub: "役員・ご来賓・イベントの送迎を、関西全域で信頼できる一社にお任せください。",
      corp_p1t: "月次一括請求",
      corp_p1d: "ご利用ごとの精算は不要。すべての乗車を一枚の明細にまとめてご請求します。",
      corp_p2t: "優先配車",
      corp_p2d: "繁忙期や直前のご依頼でも、貴社のアカウントを優先的に手配します。",
      corp_p3t: "法人向け特別料金",
      corp_p3d: "ご利用実績に合わせたボリューム価格と、定額の空港送迎をご用意します。",
      corp_form_h: "法人アカウントの申請",
      corp_form_sub: "貴社について少しお聞かせください。担当より翌営業日以内にご連絡します。",
      corp_company: "会社名",
      corp_contact: "ご担当者名",
      corp_email: "メールアドレス",
      corp_phone: "電話番号",
      corp_monthly: "月間ご利用回数の目安",
      corp_note: "ご要望（任意）",
      corp_m1: "月1〜3回",
      corp_m2: "4〜10回",
      corp_m3: "10回以上",
      corp_submit: "申請を送信",
      corp_sending: "送信中…",
      corp_req: "会社名と、メールまたは電話番号をご入力ください。",
      corp_err: "送信に失敗しました。時間をおいて再度お試しいただくか、お電話ください。",
      corp_ok_h: "ありがとうございます",
      corp_ok_sub: "ありがとうございます。担当より法人アカウントについてご連絡いたします。",
      corp_close: "閉じる",
    },
  };

  // Prefer the site dictionary via ALSCore.tt; fall back to our local strings.
  function t(k) {
    try {
      if (typeof C.tt === "function") {
        var v = C.tt(k);
        // tt returns the key itself when unknown — treat that as a miss.
        if (v != null && v !== k && v !== "") return v;
      }
    } catch (e) {}
    var lang = isJa() ? "ja" : "en";
    return (LOCAL[lang] && LOCAL[lang][k]) != null ? LOCAL[lang][k] : (LOCAL.en[k] != null ? LOCAL.en[k] : k);
  }

  function injectStyle() {
    if (document.getElementById("als-corp-style")) return;
    var css =
      "#corporate{padding:96px 0;position:relative}" +
      "#corporate .corp-wrap{max-width:1080px;margin:0 auto;padding:0 22px}" +
      "#corporate .corp-band{border:1px solid var(--hair);border-radius:22px;" +
        "background:linear-gradient(168deg,rgba(212,175,55,.07),transparent 62%),linear-gradient(170deg,var(--panel),transparent 80%);" +
        "padding:clamp(30px,4.4vw,52px);display:grid;grid-template-columns:1.15fr .85fr;gap:clamp(28px,4vw,54px);align-items:center}" +
      "#corporate .corp-eb{font-family:var(--mono);font-size:10.5px;letter-spacing:.28em;text-transform:uppercase;" +
        "color:var(--gold);font-weight:700;display:flex;align-items:center;gap:12px}" +
      "#corporate .corp-eb::before{content:'';width:26px;height:1px;background:var(--gold)}" +
      "html[lang='ja'] #corporate .corp-eb{letter-spacing:.42em}" +
      "#corporate h2.corp-h{font-family:var(--serif);font-weight:600;line-height:1.14;color:var(--cream);" +
        "font-size:clamp(28px,4.1vw,44px);margin:14px 0 12px}" +
      "#corporate .corp-sub{font-size:14px;line-height:1.6;color:var(--muted);max-width:38ch;margin-bottom:26px}" +
      "#corporate .corp-cta{display:inline-flex;align-items:center;justify-content:center;gap:9px;cursor:pointer;" +
        "padding:13px 26px;border-radius:99px;font-weight:700;font-size:13.5px;letter-spacing:.06em;transition:.22s;" +
        "border:0;font-family:var(--sans);white-space:nowrap;" +
        "background:linear-gradient(120deg,var(--gold) 0%,var(--gold2) 55%,var(--gold) 100%);" +
        "color:#1b1503;box-shadow:0 10px 30px -10px rgba(212,175,55,.45)}" +
      "#corporate .corp-cta:hover{transform:translateY(-2px);box-shadow:0 16px 36px -10px rgba(212,175,55,.55)}" +
      "#corporate .corp-points{list-style:none;display:flex;flex-direction:column;gap:16px;margin:0;padding:0}" +
      "#corporate .corp-points li{display:flex;gap:13px;align-items:flex-start}" +
      "#corporate .corp-points .ck{flex-shrink:0;width:26px;height:26px;border-radius:8px;display:grid;place-items:center;" +
        "border:1px solid var(--line);color:var(--gold);background:rgba(212,175,55,.08);font-size:13px;line-height:1}" +
      "#corporate .corp-points b{display:block;font-size:13.5px;color:var(--cream);font-weight:700;margin-bottom:2px;letter-spacing:.01em}" +
      "#corporate .corp-points span{display:block;font-size:12.5px;color:var(--muted);line-height:1.5}" +
      "#als-corp .corp-frm{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:20px}" +
      "#als-corp .corp-frm .full{grid-column:1/-1}" +
      "#als-corp .corp-fld label{display:block;font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;" +
        "color:var(--faint);margin-bottom:6px;font-weight:700}" +
      "#als-corp .corp-fld label .req{color:var(--gold)}" +
      "#als-corp .corp-fld input,#als-corp .corp-fld select,#als-corp .corp-fld textarea{" +
        "width:100%;background:rgba(10,13,24,.6);border:1px solid var(--hair);border-radius:10px;" +
        "padding:11px 13px;font-size:14px;outline:none;transition:.2s;color:var(--cream);font-family:inherit}" +
      "#als-corp .corp-fld input:focus,#als-corp .corp-fld select:focus,#als-corp .corp-fld textarea:focus{border-color:var(--gold)}" +
      "#als-corp .corp-fld textarea{resize:vertical;min-height:74px}" +
      "#als-corp .corp-fld select{appearance:none;" +
        "background-image:linear-gradient(45deg,transparent 50%,var(--gold) 50%),linear-gradient(135deg,var(--gold) 50%,transparent 50%);" +
        "background-position:calc(100% - 18px) 50%,calc(100% - 13px) 50%;background-size:5px 5px;background-repeat:no-repeat}" +
      "#als-corp .corp-err{color:var(--bad);font-size:12.5px;margin-bottom:14px;min-height:1em}" +
      "#als-corp .corp-submit{width:100%}" +
      "#als-corp .corp-ok{text-align:center;padding:8px 4px}" +
      "@media(max-width:820px){#corporate .corp-band{grid-template-columns:1fr}#corporate{padding:70px 0}" +
        "#als-corp .corp-frm{grid-template-columns:1fr}}";
    var st = document.createElement("style");
    st.id = "als-corp-style";
    st.textContent = css;
    (document.head || document.documentElement).appendChild(st);
  }

  var CHECK =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" ' +
    'stroke-linecap="round" stroke-linejoin="round" width="14" height="14"><path d="M20 6 9 17l-5-5"/></svg>';

  function pointHTML(tKey, dKey) {
    return (
      '<li><span class="ck">' + CHECK + "</span>" +
      "<span><b>" + esc(t(tKey)) + "</b>" +
      "<span>" + esc(t(dKey)) + "</span></span></li>"
    );
  }

  function buildSection() {
    if (document.getElementById("corporate")) return;
    injectStyle();

    var sec = document.createElement("section");
    sec.id = "corporate";
    // corp_h / corp_sub intentionally allow <br> from the dictionary (br-aware).
    sec.innerHTML =
      '<div class="corp-wrap">' +
      '<div class="corp-band">' +
      "<div>" +
      '<span class="corp-eb">' + esc(t("corp_eb")) + "</span>" +
      '<h2 class="corp-h">' + t("corp_h") + "</h2>" +
      '<p class="corp-sub">' + esc(t("corp_sub")) + "</p>" +
      '<button type="button" class="corp-cta">' + esc(t("corp_cta")) + "</button>" +
      "</div>" +
      '<ul class="corp-points">' +
      pointHTML("corp_p1t", "corp_p1d") +
      pointHTML("corp_p2t", "corp_p2d") +
      pointHTML("corp_p3t", "corp_p3d") +
      "</ul>" +
      "</div>" +
      "</div>";

    var btn = sec.querySelector(".corp-cta");
    if (btn) btn.addEventListener("click", openModal);

    // Inject BEFORE #contact; fallback before <footer>; else append to body.
    var anchor = document.getElementById("contact");
    if (!anchor) anchor = document.querySelector("footer");
    if (anchor && anchor.parentNode) {
      anchor.parentNode.insertBefore(sec, anchor);
    } else {
      (document.body || document.documentElement).appendChild(sec);
    }
  }

  var modalEl = null;

  function fldHTML(name, labelKey, type, required) {
    var reqMark = required ? ' <span class="req">*</span>' : "";
    return (
      '<div class="corp-fld' + (type === "textarea" ? " full" : "") + '">' +
      "<label>" + esc(t(labelKey)) + reqMark + "</label>" +
      (type === "textarea"
        ? '<textarea name="' + name + '"></textarea>'
        : '<input type="' + esc(type) + '" name="' + name + '" autocomplete="off">') +
      "</div>"
    );
  }

  function buildModal() {
    if (modalEl) return modalEl;
    injectStyle();

    var m = document.createElement("div");
    m.className = "modal-bg";
    m.id = "als-corp";
    m.setAttribute("role", "dialog");
    m.setAttribute("aria-modal", "true");

    var selOpts =
      '<option value="1-3">' + esc(t("corp_m1")) + "</option>" +
      '<option value="4-10">' + esc(t("corp_m2")) + "</option>" +
      '<option value="10+">' + esc(t("corp_m3")) + "</option>";

    m.innerHTML =
      '<div class="modal">' +
      '<button type="button" class="x" aria-label="Close">' +
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">' +
        '<path d="M18 6 6 18M6 6l12 12"/></svg></button>' +
      '<div class="corp-body">' +
      "<h3>" + esc(t("corp_form_h")) + "</h3>" +
      '<p class="msub">' + esc(t("corp_form_sub")) + "</p>" +
      '<form class="corp-frm" novalidate>' +
      fldHTML("company", "corp_company", "text", true) +
      fldHTML("contact_name", "corp_contact", "text", false) +
      fldHTML("email", "corp_email", "email", false) +
      fldHTML("phone", "corp_phone", "tel", false) +
      '<div class="corp-fld full"><label>' + esc(t("corp_monthly")) + "</label>" +
        '<select name="monthly_est">' + selOpts + "</select></div>" +
      fldHTML("note", "corp_note", "textarea", false) +
      '<div class="corp-err full" aria-live="polite"></div>' +
      '<button type="submit" class="btn btn-gold corp-submit full">' + esc(t("corp_submit")) + "</button>" +
      "</form>" +
      "</div>" +
      "</div>";

    var closeBtn = m.querySelector(".x");
    if (closeBtn) closeBtn.addEventListener("click", closeModal);

    // Backdrop click closes.
    m.addEventListener("click", function (e) {
      if (e.target === m) closeModal();
    });

    var form = m.querySelector("form");
    if (form) form.addEventListener("submit", onSubmit);

    (document.body || document.documentElement).appendChild(m);
    modalEl = m;
    return m;
  }

  function onEsc(e) {
    if (e.key === "Escape" || e.key === "Esc") closeModal();
  }

  function openModal() {
    try {
      var m = buildModal();
      m.classList.add("open");
      document.addEventListener("keydown", onEsc);
      var first = m.querySelector('input[name="company"]');
      if (first) setTimeout(function () { try { first.focus(); } catch (e) {} }, 30);
    } catch (e) {
      /* never throw */
    }
  }

  function closeModal() {
    try {
      if (modalEl) modalEl.classList.remove("open");
      document.removeEventListener("keydown", onEsc);
    } catch (e) {}
  }

  function onSubmit(e) {
    if (e && e.preventDefault) e.preventDefault();
    if (!modalEl) return;

    var form = modalEl.querySelector("form");
    var errEl = modalEl.querySelector(".corp-err");
    var submitBtn = modalEl.querySelector(".corp-submit");
    if (!form) return;

    function val(name) {
      var el = form.querySelector('[name="' + name + '"]');
      return el ? String(el.value || "").trim() : "";
    }

    var payload = {
      company: val("company"),
      contact_name: val("contact_name"),
      email: val("email"),
      phone: val("phone"),
      monthly_est: val("monthly_est"),
      note: val("note"),
    };

    // Client-side: company + (email OR phone).
    if (!payload.company || (!payload.email && !payload.phone)) {
      if (errEl) errEl.textContent = t("corp_req");
      return;
    }
    if (errEl) errEl.textContent = "";

    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = t("corp_sending");
    }

    fetch("/api/corporate", {
      method: "POST",
      headers: { "content-type": "application/json", Accept: "application/json" },
      credentials: "include",
      body: JSON.stringify(payload),
    })
      .then(function (r) {
        return r
          .json()
          .catch(function () { return {}; })
          .then(function (data) { return { ok: r.ok, data: data }; });
      })
      .then(function (res) {
        if (!res.ok || !res.data || res.data.ok === false) throw new Error("failed");
        showSuccess();
      })
      .catch(function () {
        if (errEl) errEl.textContent = t("corp_err");
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = t("corp_submit");
        }
      });
  }

  function showSuccess() {
    if (!modalEl) return;
    var body = modalEl.querySelector(".corp-body");
    if (body) {
      body.innerHTML =
        '<div class="corp-ok">' +
        '<div class="ok-ring">' +
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" ' +
        'stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>' +
        "</div>" +
        "<h3>" + esc(t("corp_ok_h")) + "</h3>" +
        '<p class="msub">' + esc(t("corp_ok_sub")) + "</p>" +
        "</div>";
    }
    // Auto-close shortly after showing the confirmation.
    setTimeout(closeModal, 2600);
  }

  function boot() {
    try {
      buildSection();
    } catch (e) {
      /* never throw */
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
