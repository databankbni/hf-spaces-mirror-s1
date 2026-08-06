/* Ashiya Limousine — Packages (curated tiered bundles) */
/* Owns: public/js/bundles.js — loads via <script defer> after main inline script. */
(function () {
  "use strict";
  if (window.__ALS_BUNDLES__) return;
  window.__ALS_BUNDLES__ = true;

  var C = window.ALSCore;
  if (!C || typeof C.applyBundle !== "function") {
    console.warn("[bundles] ALSCore unavailable — skipping packages section.");
    return;
  }

  var esc = typeof C.esc === "function" ? C.esc : function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };
  var yen = typeof C.yen === "function" ? C.yen : function (n) { return "¥" + n; };
  var tt = typeof C.tt === "function" ? C.tt : function () { return ""; };

  function injectStyle() {
    if (document.getElementById("als-pkg-style")) return;
    var css =
      "#packages{padding:96px 0}" +
      "#packages .pkg-wrap{max-width:1180px;margin:0 auto;padding:0 22px}" +
      "#packages .pkg-head{margin-bottom:44px}" +
      "#packages .pkg-eb{font-family:var(--mono);font-size:10.5px;letter-spacing:.28em;text-transform:uppercase;" +
        "color:var(--gold);font-weight:700;display:flex;align-items:center;gap:12px}" +
      "#packages .pkg-eb::before{content:'';width:26px;height:1px;background:var(--gold)}" +
      "html[lang='ja'] #packages .pkg-eb{letter-spacing:.42em}" +
      "#packages h2.pkg-h{font-family:var(--serif);font-weight:600;line-height:1.14;color:var(--cream);" +
        "font-size:clamp(30px,4.4vw,46px);margin:14px 0 10px}" +
      "#packages .pkg-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}" +
      "#packages .pkg-card{border:1px solid var(--hair);border-radius:16px;padding:28px 24px;" +
        "background:linear-gradient(172deg,var(--panel),transparent 72%);display:flex;flex-direction:column;" +
        "gap:14px;transition:.25s;position:relative}" +
      "#packages .pkg-card:hover{border-color:var(--line);transform:translateY(-3px)}" +
      "#packages .pkg-card.feat{border-color:var(--line);background:linear-gradient(172deg,rgba(212,175,55,.09),transparent 75%)}" +
      "#packages .pkg-badge{position:absolute;top:-11px;left:22px;font-size:9.5px;font-weight:800;" +
        "letter-spacing:.2em;text-transform:uppercase;color:#1b1503;" +
        "background:linear-gradient(120deg,var(--gold),var(--gold2));padding:4px 12px;border-radius:99px}" +
      "#packages .pkg-name{font-family:var(--serif);font-size:23px;font-weight:600;line-height:1.2;color:var(--cream)}" +
      "#packages .pkg-plan{font-size:10px;letter-spacing:.26em;text-transform:uppercase;color:var(--gold);font-weight:700}" +
      "#packages .pkg-list{list-style:none;display:flex;flex-direction:column;gap:7px;font-size:12.5px;color:var(--muted);margin:2px 0}" +
      "#packages .pkg-list li{display:flex;gap:8px;align-items:flex-start}" +
      "#packages .pkg-list li .ck{color:var(--gold);flex-shrink:0;margin-top:1px;font-size:12px;line-height:1.3}" +
      "#packages .pkg-price{font-family:var(--mono);font-size:30px;color:var(--gold2);letter-spacing:-.01em;margin-top:4px}" +
      "#packages .pkg-price small{font-size:11px;color:var(--faint);letter-spacing:.05em}" +
      "#packages .pkg-btn{margin-top:auto;display:inline-flex;align-items:center;justify-content:center;gap:9px;" +
        "padding:13px 26px;border-radius:99px;font-weight:700;font-size:13.5px;letter-spacing:.06em;transition:.22s;" +
        "cursor:pointer;border:0;white-space:nowrap;font-family:var(--sans);" +
        "background:linear-gradient(120deg,var(--gold) 0%,var(--gold2) 55%,var(--gold) 100%);" +
        "color:#1b1503;box-shadow:0 10px 30px -10px rgba(212,175,55,.45)}" +
      "#packages .pkg-btn:hover{transform:translateY(-2px);box-shadow:0 16px 36px -10px rgba(212,175,55,.55)}" +
      "@media(max-width:900px){#packages .pkg-grid{grid-template-columns:1fr}#packages{padding:70px 0}}";
    var st = document.createElement("style");
    st.id = "als-pkg-style";
    st.textContent = css;
    document.head.appendChild(st);
  }

  function cardHTML(b) {
    var feat = b.badge ? " feat" : "";
    var badge = b.badge
      ? '<span class="pkg-badge">' + esc(b.badge) + "</span>"
      : "";
    var addons = Array.isArray(b.addons) ? b.addons : [];
    var items = addons
      .map(function (a) {
        return '<li><span class="ck">&#10003;</span><span>' + esc(a.name_en) + "</span></li>";
      })
      .join("");
    var planLabel = b.plan_name_en || b.plan || "";
    return (
      '<article class="pkg-card' + feat + '">' +
      badge +
      '<div class="pkg-plan">' + esc(planLabel) + "</div>" +
      '<div class="pkg-name">' + esc(b.name_en) + "</div>" +
      '<ul class="pkg-list">' + items + "</ul>" +
      '<div class="pkg-price">' + esc(yen(b.price)) + "</div>" +
      '<button type="button" class="pkg-btn"></button>' +
      "</article>"
    );
  }

  function render(bundles) {
    if (!Array.isArray(bundles) || !bundles.length) return;
    injectStyle();

    var isJa = C.L === "ja";
    var btnLabel = isJa ? "このパッケージで予約" : "Book this package";

    var sec = document.createElement("section");
    sec.id = "packages";
    sec.innerHTML =
      '<div class="pkg-wrap">' +
      '<div class="pkg-head">' +
      '<span class="pkg-eb">' + tt("pkg_eb") + "</span>" +
      '<h2 class="pkg-h">' + tt("pkg_h") + "</h2>" +
      "</div>" +
      '<div class="pkg-grid">' +
      bundles.map(cardHTML).join("") +
      "</div>" +
      "</div>";

    // Wire up buttons safely (avoid inline handlers / injection).
    var cards = sec.querySelectorAll(".pkg-card");
    bundles.forEach(function (b, i) {
      var card = cards[i];
      if (!card) return;
      var btn = card.querySelector(".pkg-btn");
      if (!btn) return;
      btn.textContent = btnLabel;
      var addonIds = (Array.isArray(b.addons) ? b.addons : []).map(function (a) {
        return a.id;
      });
      btn.addEventListener("click", function () {
        try {
          C.applyBundle(b.plan, addonIds);
        } catch (e) {
          console.warn("[bundles] applyBundle failed", e);
        }
      });
    });

    var anchor = document.getElementById("booking");
    if (anchor && anchor.parentNode) {
      anchor.parentNode.insertBefore(sec, anchor);
    } else {
      var main = document.querySelector("main") || document.body;
      if (main) main.appendChild(sec);
      else return;
    }
  }

  function boot() {
    fetch("/api/pricing/bundles", { headers: { Accept: "application/json" } })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        if (!data || data.ok !== true) throw new Error("bad payload");
        render(data.bundles);
      })
      .catch(function (e) {
        console.warn("[bundles] could not load packages:", e && e.message ? e.message : e);
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
