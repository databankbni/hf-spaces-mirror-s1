/* Ashiya Limousine — Newsletter capture band */
/* Owns: public/js/newsletter.js — loads via <script defer> after main inline script. */
(function () {
  "use strict";
  if (window.__ALS_NEWSLETTER__) return;
  window.__ALS_NEWSLETTER__ = true;

  var C = window.ALSCore;
  if (!C) {
    console.warn("[newsletter] ALSCore unavailable — skipping newsletter band.");
    return;
  }

  var esc = typeof C.esc === "function" ? C.esc : function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };
  var tt = typeof C.tt === "function" ? C.tt : function (k) { return String(k); };
  var isJA = function () { return C.L === "ja"; };

  var EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  function injectStyle() {
    if (document.getElementById("als-news-style")) return;
    var css =
      "#newsletter{padding:72px 0;border-top:1px solid var(--hair)}" +
      "#newsletter .nl-wrap{max-width:920px;margin:0 auto;padding:0 22px;text-align:center}" +
      "#newsletter h2.nl-h{font-family:var(--serif);font-weight:600;line-height:1.14;color:var(--cream);" +
        "font-size:clamp(26px,3.6vw,38px);margin:0 0 12px}" +
      "#newsletter .nl-p{font-family:var(--sans);color:var(--muted);font-size:15px;line-height:1.6;" +
        "max-width:540px;margin:0 auto 26px}" +
      "#newsletter .nl-form{display:flex;gap:10px;max-width:480px;margin:0 auto;flex-wrap:wrap;" +
        "justify-content:center}" +
      "#newsletter .nl-input{flex:1 1 240px;min-width:0;background:var(--panel);border:1px solid var(--hair);" +
        "border-radius:12px;padding:13px 16px;color:var(--cream);font-family:var(--sans);font-size:15px;" +
        "outline:none;transition:.2s}" +
      "#newsletter .nl-input::placeholder{color:var(--ink3)}" +
      "#newsletter .nl-input:focus{border-color:var(--gold);box-shadow:0 0 0 3px rgba(212,175,55,.14)}" +
      "#newsletter .nl-input.nl-err{border-color:var(--bad)}" +
      "#newsletter .nl-btn{flex:0 0 auto;background:var(--gold);color:#1a1408;border:0;border-radius:12px;" +
        "padding:13px 26px;font-family:var(--sans);font-weight:700;font-size:14px;letter-spacing:.02em;" +
        "cursor:pointer;transition:.2s}" +
      "#newsletter .nl-btn:hover{background:var(--gold2,var(--gold))}" +
      "#newsletter .nl-btn:disabled{opacity:.55;cursor:default}" +
      "#newsletter .nl-ok{font-family:var(--serif);font-size:18px;color:var(--gold);margin:8px 0 0}" +
      "html[lang='ja'] #newsletter .nl-p{letter-spacing:.02em}" +
      "@media(max-width:520px){#newsletter .nl-form{flex-direction:column}" +
        "#newsletter .nl-btn{width:100%}}";
    var st = document.createElement("style");
    st.id = "als-news-style";
    st.textContent = css;
    (document.head || document.documentElement).appendChild(st);
  }

  function build() {
    var sec = document.createElement("section");
    sec.id = "newsletter";
    var ph = isJA() ? "メールアドレス" : "Email address";

    sec.innerHTML =
      '<div class="nl-wrap">' +
        '<h2 class="nl-h">' + esc(tt("news_h")) + "</h2>" +
        '<p class="nl-p">' + esc(tt("news_p")) + "</p>" +
        '<form class="nl-form" novalidate>' +
          '<input type="email" class="nl-input" autocomplete="email" ' +
            'aria-label="' + esc(ph) + '" placeholder="' + esc(ph) + '">' +
          '<button type="submit" class="nl-btn">' + esc(tt("news_cta")) + "</button>" +
        "</form>" +
      "</div>";

    var form = sec.querySelector(".nl-form");
    var input = sec.querySelector(".nl-input");
    var btn = sec.querySelector(".nl-btn");

    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var email = String(input.value || "").trim();
      if (!EMAIL_RE.test(email)) {
        input.classList.add("nl-err");
        input.focus();
        return;
      }
      input.classList.remove("nl-err");
      btn.disabled = true;
      input.disabled = true;

      subscribe(email).then(function (ok) {
        if (ok) {
          var wrap = sec.querySelector(".nl-wrap");
          var msg = document.createElement("p");
          msg.className = "nl-ok";
          msg.setAttribute("role", "status");
          msg.textContent = tt("news_ok");
          if (form.parentNode) form.parentNode.removeChild(form);
          wrap.appendChild(msg);
        } else {
          btn.disabled = false;
          input.disabled = false;
        }
      });
    });

    return sec;
  }

  function subscribe(email) {
    var body;
    try {
      body = JSON.stringify({ email: email, lang: C.L });
    } catch (e) {
      return Promise.resolve(false);
    }
    return fetch("/api/newsletter/subscribe", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: body
    }).then(function (res) {
      return !!(res && res.ok);
    }).catch(function () {
      return false;
    });
  }

  function inject() {
    try {
      if (document.getElementById("newsletter")) return;
      injectStyle();
      var sec = build();
      var footer = document.querySelector("footer");
      if (footer && footer.parentNode) {
        footer.parentNode.insertBefore(sec, footer);
        return;
      }
      var contact = document.getElementById("contact");
      if (contact && contact.parentNode) {
        contact.parentNode.insertBefore(sec, contact);
        return;
      }
      document.body.appendChild(sec);
    } catch (e) {
      console.warn("[newsletter] inject failed:", e);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", inject, { once: true });
  } else {
    inject();
  }
})();
