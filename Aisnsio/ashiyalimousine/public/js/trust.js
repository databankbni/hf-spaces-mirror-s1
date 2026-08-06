/* Ashiya Limousine — Trust badges band + floating chat widget */
/* Owns: public/js/trust.js — loads via <script defer> after main inline script. */
(function () {
  "use strict";
  if (window.__ALS_TRUST__) return;
  window.__ALS_TRUST__ = true;

  var C = window.ALSCore;
  if (!C) {
    console.warn("[trust] ALSCore unavailable — skipping trust band + chat.");
    return;
  }

  var esc = typeof C.esc === "function" ? C.esc : function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };
  var tt = typeof C.tt === "function" ? C.tt : function (k) { return String(k); };
  var isJA = function () { return C.L === "ja"; };
  var t = function (en, ja) { return isJA() ? ja : en; };

  var EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  /* Escape text but preserve <br> tags (for br-aware headings). */
  function brSafe(str) {
    return String(str == null ? "" : str)
      .split(/<br\s*\/?>/i)
      .map(esc)
      .join("<br>");
  }

  var BADGES = [
    {
      sym: "i-shield",
      title: t("Licensed operator", "認可事業者"),
      line: t("Class-2 licensed professional chauffeurs", "第二種免許を持つプロの運転手")
    },
    {
      sym: "i-verified",
      title: t("Fully insured", "保険完備"),
      line: t("Passenger + vehicle coverage", "乗客・車両ともに補償")
    },
    {
      sym: "i-star",
      title: t("4.9★ rating", "高評価 4.9★"),
      line: t("From 2,400+ happy guests", "2,400名以上のお客様より")
    },
    {
      sym: "i-clock",
      title: t("Daily dispatch", "年中無休"),
      line: t("9:00–22:00, every day", "毎日 9:00〜22:00 運行")
    }
  ];

  /* ---------------- shared styles ---------------- */
  function injectStyle() {
    if (document.getElementById("als-trust-style")) return;
    var css =
      /* trust band */
      "#trust{padding:64px 0;border-top:1px solid var(--hair)}" +
      "#trust .tr-wrap{max-width:1080px;margin:0 auto;padding:0 22px;text-align:center}" +
      "#trust .tr-eb{font-family:var(--sans);text-transform:uppercase;letter-spacing:.22em;" +
        "font-size:11px;font-weight:700;color:var(--gold);margin:0 0 12px}" +
      "#trust h2.tr-h{font-family:var(--serif);font-weight:600;line-height:1.16;color:var(--cream);" +
        "font-size:clamp(24px,3.4vw,36px);margin:0 0 40px}" +
      "#trust .tr-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:18px}" +
      "#trust .tr-card{background:var(--panel);border:1px solid var(--hair);border-radius:16px;" +
        "padding:28px 20px;text-align:center;transition:.2s}" +
      "#trust .tr-card:hover{border-color:var(--gold);transform:translateY(-2px)}" +
      "#trust .tr-ico{width:46px;height:46px;border-radius:50%;margin:0 auto 16px;display:grid;" +
        "place-items:center;background:rgba(212,175,55,.12);color:var(--gold)}" +
      "#trust .tr-ico svg{width:22px;height:22px}" +
      "#trust .tr-t{font-family:var(--serif);font-size:18px;color:var(--cream);margin:0 0 6px}" +
      "#trust .tr-l{font-family:var(--sans);font-size:13px;line-height:1.5;color:var(--muted);margin:0}" +
      "@media(max-width:820px){#trust .tr-grid{grid-template-columns:repeat(2,1fr)}}" +
      "@media(max-width:440px){#trust .tr-grid{grid-template-columns:1fr}}" +
      /* chat launcher */
      "#als-chat-btn{position:fixed;right:20px;bottom:150px;z-index:85;width:50px;height:50px;" +
        "border:0;border-radius:99px;cursor:pointer;display:grid;place-items:center;" +
        "background:linear-gradient(130deg,var(--gold),var(--gold2));color:#1b1503;" +
        "box-shadow:0 12px 30px -8px rgba(0,0,0,.6);transition:transform .2s}" +
      "#als-chat-btn:hover{transform:translateY(-3px)}" +
      "#als-chat-btn svg{width:22px;height:22px}" +
      /* chat panel */
      "#als-chat-panel{position:fixed;right:20px;bottom:210px;z-index:86;width:300px;max-width:calc(100vw - 40px);" +
        "max-height:min(70vh,520px);overflow-y:auto;background:var(--panel);border:1px solid var(--hair);" +
        "border-radius:16px;box-shadow:0 24px 60px -12px rgba(0,0,0,.7);" +
        "font-family:var(--sans);display:none}" +
      "#als-chat-panel.open{display:block}" +
      "#als-chat-panel .cw-head{display:flex;align-items:center;justify-content:space-between;gap:10px;" +
        "padding:16px 16px 10px}" +
      "#als-chat-panel .cw-title{font-family:var(--serif);font-size:17px;color:var(--cream);margin:0}" +
      "#als-chat-panel .cw-x{background:none;border:0;color:var(--muted);cursor:pointer;padding:2px;" +
        "line-height:0;border-radius:8px}" +
      "#als-chat-panel .cw-x:hover{color:var(--cream)}" +
      "#als-chat-panel .cw-x svg{width:16px;height:16px}" +
      "#als-chat-panel .cw-body{padding:0 16px 16px}" +
      "#als-chat-panel .cw-greet{font-size:13px;line-height:1.55;color:var(--muted);margin:0 0 14px}" +
      "#als-chat-panel .cw-line{display:flex;align-items:center;justify-content:center;gap:8px;" +
        "background:#06C755;color:#fff;text-decoration:none;border-radius:12px;padding:11px 14px;" +
        "font-weight:700;font-size:14px;margin-bottom:14px}" +
      "#als-chat-panel .cw-line svg{width:18px;height:18px}" +
      "#als-chat-panel .cw-or{text-align:center;font-size:11px;letter-spacing:.14em;text-transform:uppercase;" +
        "color:var(--ink3);margin:0 0 12px}" +
      "#als-chat-panel .cw-field{width:100%;box-sizing:border-box;background:var(--panel);" +
        "border:1px solid var(--hair);border-radius:10px;padding:10px 12px;color:var(--cream);" +
        "font-family:var(--sans);font-size:14px;outline:none;margin-bottom:10px;transition:.2s}" +
      "#als-chat-panel textarea.cw-field{resize:vertical;min-height:64px}" +
      "#als-chat-panel .cw-field::placeholder{color:var(--ink3)}" +
      "#als-chat-panel .cw-field:focus{border-color:var(--gold);box-shadow:0 0 0 3px rgba(212,175,55,.14)}" +
      "#als-chat-panel .cw-field.cw-err{border-color:var(--bad)}" +
      "#als-chat-panel .cw-send{width:100%;background:var(--gold);color:#1a1408;border:0;border-radius:12px;" +
        "padding:12px;font-family:var(--sans);font-weight:700;font-size:14px;cursor:pointer;transition:.2s}" +
      "#als-chat-panel .cw-send:hover{background:var(--gold2,var(--gold))}" +
      "#als-chat-panel .cw-send:disabled{opacity:.55;cursor:default}" +
      "#als-chat-panel .cw-ok{text-align:center;padding:8px 0 4px}" +
      "#als-chat-panel .cw-ok-t{font-family:var(--serif);font-size:17px;color:var(--gold);margin:0}" +
      "@media(max-width:520px){#als-chat-panel{bottom:210px}}";
    var st = document.createElement("style");
    st.id = "als-trust-style";
    st.textContent = css;
    (document.head || document.documentElement).appendChild(st);
  }

  function svg(sym) {
    return '<svg aria-hidden="true"><use href="#' + esc(sym) + '"/></svg>';
  }

  /* ---------------- trust band ---------------- */
  function buildBand() {
    var cards = BADGES.map(function (b) {
      return (
        '<div class="tr-card">' +
          '<div class="tr-ico">' + svg(b.sym) + "</div>" +
          '<h3 class="tr-t">' + esc(b.title) + "</h3>" +
          '<p class="tr-l">' + esc(b.line) + "</p>" +
        "</div>"
      );
    }).join("");

    var sec = document.createElement("section");
    sec.id = "trust";
    sec.innerHTML =
      '<div class="tr-wrap">' +
        '<p class="tr-eb">' + esc(tt("trust_eb")) + "</p>" +
        '<h2 class="tr-h">' + brSafe(tt("trust_h")) + "</h2>" +
        '<div class="tr-grid">' + cards + "</div>" +
      "</div>";
    return sec;
  }

  function injectBand() {
    if (document.getElementById("trust")) return;
    var sec = buildBand();
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
  }

  /* ---------------- chat widget ---------------- */
  function buildChat() {
    if (document.getElementById("als-chat-btn")) return;

    var btn = document.createElement("button");
    btn.id = "als-chat-btn";
    btn.type = "button";
    btn.setAttribute("aria-label", t("Chat with us", "チャットで相談"));
    btn.setAttribute("aria-expanded", "false");
    btn.innerHTML = svg("i-cmt");

    var panel = document.createElement("div");
    panel.id = "als-chat-panel";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", t("Chat with us", "チャットで相談"));

    panel.innerHTML =
      '<div class="cw-head">' +
        '<h3 class="cw-title">' + esc(t("Chat with us", "チャットで相談")) + "</h3>" +
        '<button type="button" class="cw-x" aria-label="' + esc(t("Close", "閉じる")) + '">' +
          svg("i-x") +
        "</button>" +
      "</div>" +
      '<div class="cw-body">' +
        '<p class="cw-greet">' +
          esc(t(
            "Hi! Questions about a booking or a quote? We usually reply within minutes.",
            "こんにちは！ご予約やお見積りのご相談はこちらから。数分以内に返信します。"
          )) +
        "</p>" +
        '<a class="cw-line" href="https://line.me/" target="_blank" rel="noopener">' +
          svg("i-line") + "<span>" + esc(t("Chat on LINE", "LINEで相談")) + "</span>" +
        "</a>" +
        '<p class="cw-or">' + esc(t("or send a message", "またはメッセージを送信")) + "</p>" +
        '<form class="cw-form" novalidate>' +
          '<input type="text" class="cw-field cw-name" autocomplete="name" ' +
            'aria-label="' + esc(t("Your name", "お名前")) + '" ' +
            'placeholder="' + esc(t("Your name", "お名前")) + '">' +
          '<input type="email" class="cw-field cw-email" autocomplete="email" ' +
            'aria-label="' + esc(t("Email", "メールアドレス")) + '" ' +
            'placeholder="' + esc(t("Email", "メールアドレス")) + '">' +
          '<textarea class="cw-field cw-msg" ' +
            'aria-label="' + esc(t("How can we help?", "ご相談内容")) + '" ' +
            'placeholder="' + esc(t("How can we help?", "ご相談内容")) + '"></textarea>' +
          '<button type="submit" class="cw-send">' + esc(t("Send", "送信")) + "</button>" +
        "</form>" +
      "</div>";

    var body = document.body;
    body.appendChild(btn);
    body.appendChild(panel);

    function open() {
      panel.classList.add("open");
      btn.setAttribute("aria-expanded", "true");
      var nm = panel.querySelector(".cw-name");
      if (nm) { try { nm.focus(); } catch (e) {} }
    }
    function close() {
      panel.classList.remove("open");
      btn.setAttribute("aria-expanded", "false");
    }
    function toggle() {
      if (panel.classList.contains("open")) close(); else open();
    }

    btn.addEventListener("click", toggle);
    var xb = panel.querySelector(".cw-x");
    if (xb) xb.addEventListener("click", close);
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && panel.classList.contains("open")) close();
    });

    var form = panel.querySelector(".cw-form");
    var nameEl = panel.querySelector(".cw-name");
    var emailEl = panel.querySelector(".cw-email");
    var msgEl = panel.querySelector(".cw-msg");
    var sendBtn = panel.querySelector(".cw-send");

    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var email = String(emailEl.value || "").trim();
      if (!EMAIL_RE.test(email)) {
        emailEl.classList.add("cw-err");
        try { emailEl.focus(); } catch (e) {}
        return;
      }
      emailEl.classList.remove("cw-err");

      var payload = {
        name: String(nameEl.value || "").trim(),
        email: email,
        selection: { message: String(msgEl.value || "").trim() }
      };

      sendBtn.disabled = true;
      nameEl.disabled = emailEl.disabled = msgEl.disabled = true;

      sendQuote(payload).then(function (ok) {
        if (ok) {
          var b = panel.querySelector(".cw-body");
          if (b) {
            b.innerHTML =
              '<div class="cw-ok" role="status">' +
                '<p class="cw-ok-t">' +
                  esc(t("Thanks — we'll reply shortly.", "ありがとうございます。まもなくご連絡します。")) +
                "</p>" +
              "</div>";
          }
        } else {
          sendBtn.disabled = false;
          nameEl.disabled = emailEl.disabled = msgEl.disabled = false;
        }
      });
    });
  }

  function sendQuote(payload) {
    var body;
    try {
      body = JSON.stringify(payload);
    } catch (e) {
      return Promise.resolve(false);
    }
    return fetch("/api/leads/quote", {
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

  /* ---------------- boot ---------------- */
  function init() {
    try {
      injectStyle();
      injectBand();
      buildChat();
    } catch (e) {
      console.warn("[trust] init failed:", e);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
