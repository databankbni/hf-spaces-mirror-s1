/* Ashiya Limousine — Journal (blog) teaser + Help Center.
   Owns: public/js/content.js — loads via <script defer>.
   Reads the public content API and adds a Journal section, a post-reader
   modal, and a Help Center accordion modal reachable from the footer. */
(function () {
  "use strict";
  if (window.__ALS_CONTENT__) return;
  window.__ALS_CONTENT__ = true;

  var C = window.ALSCore || {};

  var esc =
    typeof C.esc === "function"
      ? C.esc
      : function (s) {
          return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
            return {
              "&": "&amp;",
              "<": "&lt;",
              ">": "&gt;",
              '"': "&quot;",
              "'": "&#39;"
            }[c];
          });
        };
  var tt =
    typeof C.tt === "function"
      ? C.tt
      : function (k) {
          return k;
        };
  function isJa() {
    return C.L === "ja";
  }

  // ---- i18n fallbacks (tt keys blog_eb/blog_h/help_h exist site-wide) ------
  function L(en, ja) {
    return isJa() ? ja : en;
  }
  function readMore() {
    return L("Read", "続きを読む") + " →";
  }
  function helpLabel() {
    return tt("help_h") || L("Help center", "ヘルプセンター");
  }

  // ---- API -----------------------------------------------------------------
  function apiList(kind) {
    return fetch("/api/content?kind=" + encodeURIComponent(kind), {
      headers: { Accept: "application/json" }
    })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (d) {
        return d && Array.isArray(d.posts) ? d.posts : [];
      });
  }
  function apiPost(slug) {
    return fetch("/api/content/" + encodeURIComponent(slug), {
      headers: { Accept: "application/json" }
    })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (d) {
        return d && d.post ? d.post : null;
      });
  }

  // ---- styles --------------------------------------------------------------
  function injectStyle() {
    if (document.getElementById("als-content-style")) return;
    var css =
      "#journal{padding:96px 0}" +
      "#journal .jr-wrap{max-width:1180px;margin:0 auto;padding:0 22px}" +
      "#journal .jr-head{margin-bottom:40px}" +
      "#journal .jr-eb{font-family:var(--mono);font-size:10.5px;letter-spacing:.28em;text-transform:uppercase;" +
        "color:var(--gold);font-weight:700;display:flex;align-items:center;gap:12px}" +
      "#journal .jr-eb::before{content:'';width:26px;height:1px;background:var(--gold)}" +
      "html[lang='ja'] #journal .jr-eb{letter-spacing:.42em}" +
      "#journal h2.jr-h{font-family:var(--serif);font-weight:600;line-height:1.14;color:var(--cream);" +
        "font-size:clamp(30px,4.4vw,46px);margin:14px 0 0}" +
      "#journal .jr-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}" +
      "#journal .jr-card{border:1px solid var(--hair);border-radius:16px;padding:26px 24px;" +
        "background:linear-gradient(172deg,var(--panel),transparent 72%);display:flex;flex-direction:column;" +
        "gap:12px;transition:.25s;cursor:pointer;text-align:left;color:inherit;font:inherit}" +
      "#journal .jr-card:hover{border-color:var(--line);transform:translateY(-3px)}" +
      "#journal .jr-date{font-family:var(--mono);font-size:10px;letter-spacing:.16em;text-transform:uppercase;color:var(--faint)}" +
      "#journal .jr-title{font-family:var(--serif);font-size:22px;font-weight:600;line-height:1.22;color:var(--cream)}" +
      "#journal .jr-ex{font-size:12.5px;line-height:1.6;color:var(--muted);flex:1}" +
      "#journal .jr-more{margin-top:4px;font-size:11.5px;letter-spacing:.12em;text-transform:uppercase;" +
        "color:var(--gold);font-weight:700}" +
      "@media(max-width:900px){#journal .jr-grid{grid-template-columns:1fr}#journal{padding:70px 0}}" +
      // post reader body
      "#als-post .modal{max-width:640px;text-align:left}" +
      "#als-post .pr-date{font-family:var(--mono);font-size:10px;letter-spacing:.16em;text-transform:uppercase;" +
        "color:var(--faint);margin-bottom:8px}" +
      "#als-post h3{text-align:left}" +
      "#als-post .pr-body{margin-top:16px;display:flex;flex-direction:column;gap:14px}" +
      "#als-post .pr-body p{font-size:14px;line-height:1.75;color:var(--muted)}" +
      // help center accordion
      "#als-help .modal{max-width:600px;text-align:left}" +
      "#als-help h3{text-align:left}" +
      "#als-help .hc-list{margin-top:18px;display:flex;flex-direction:column;gap:8px}" +
      "#als-help .hc-item{border:1px solid var(--hair);border-radius:12px;overflow:hidden}" +
      "#als-help .hc-q{width:100%;text-align:left;background:none;border:0;cursor:pointer;font:inherit;" +
        "color:var(--cream);padding:15px 18px;display:flex;justify-content:space-between;align-items:center;gap:12px;" +
        "font-family:var(--serif);font-size:16px;font-weight:600}" +
      "#als-help .hc-q .hc-ic{color:var(--gold);flex-shrink:0;transition:transform .2s;font-family:var(--sans);font-size:18px}" +
      "#als-help .hc-item.open .hc-q .hc-ic{transform:rotate(45deg)}" +
      "#als-help .hc-a{max-height:0;overflow:hidden;transition:max-height .25s ease}" +
      "#als-help .hc-item.open .hc-a{max-height:1200px}" +
      "#als-help .hc-a-in{padding:0 18px 16px;display:flex;flex-direction:column;gap:12px}" +
      "#als-help .hc-a-in p{font-size:13px;line-height:1.7;color:var(--muted)}" +
      "footer a#helpLink{cursor:pointer}";
    var st = document.createElement("style");
    st.id = "als-content-style";
    st.textContent = css;
    document.head.appendChild(st);
  }

  // ---- helpers -------------------------------------------------------------
  function fmtDate(iso) {
    if (!iso) return "";
    if (typeof C.fmtDate === "function") {
      try {
        var v = C.fmtDate(iso);
        if (v) return v;
      } catch (_e) {}
    }
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    try {
      return d.toLocaleDateString(isJa() ? "ja-JP" : "en-US", {
        year: "numeric",
        month: "short",
        day: "numeric"
      });
    } catch (_e2) {
      return "";
    }
  }

  // Render a body string as escaped paragraphs, split on blank lines.
  function bodyHTML(body) {
    var text = String(body == null ? "" : body);
    var blocks = text.split(/\n\s*\n/);
    var out = [];
    for (var i = 0; i < blocks.length; i++) {
      var b = blocks[i].trim();
      if (!b) continue;
      // single newlines within a block -> <br>
      out.push("<p>" + esc(b).replace(/\n/g, "<br>") + "</p>");
    }
    if (!out.length) out.push("<p>" + esc(text) + "</p>");
    return out.join("");
  }

  var svgX =
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
    'stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>';

  // Generic modal shell with X / backdrop / Escape close.
  function makeModal(id) {
    var existing = document.getElementById(id);
    if (existing) return existing;
    var bg = document.createElement("div");
    bg.className = "modal-bg";
    bg.id = id;
    var modal = document.createElement("div");
    modal.className = "modal";
    var close = document.createElement("button");
    close.className = "x";
    close.setAttribute("aria-label", "close");
    close.innerHTML = svgX;
    var body = document.createElement("div");
    body.className = "modal-body";
    modal.appendChild(close);
    modal.appendChild(body);
    bg.appendChild(modal);
    document.body.appendChild(bg);

    function closeIt() {
      bg.classList.remove("open");
    }
    close.addEventListener("click", closeIt);
    bg.addEventListener("click", function (e) {
      if (e.target === bg) closeIt();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && bg.classList.contains("open")) closeIt();
    });
    bg._body = body;
    return bg;
  }

  // ---- post reader ---------------------------------------------------------
  function openPost(slug) {
    if (!slug) return;
    var bg = makeModal("als-post");
    var body = bg._body;
    body.innerHTML = '<p class="pr-date">' + esc(L("Loading…", "読み込み中…")) + "</p>";
    bg.classList.add("open");
    apiPost(slug)
      .then(function (post) {
        if (!post) {
          body.innerHTML =
            "<h3>" + esc(L("Not found", "見つかりません")) + "</h3>";
          return;
        }
        var dateStr = fmtDate(post.created_at);
        body.innerHTML =
          (dateStr ? '<div class="pr-date">' + esc(dateStr) + "</div>" : "") +
          "<h3>" + esc(post.title || "") + "</h3>" +
          '<div class="pr-body">' + bodyHTML(post.body) + "</div>";
      })
      .catch(function () {
        body.innerHTML =
          "<h3>" + esc(L("Unavailable", "ご利用いただけません")) + "</h3>";
      });
  }

  // ---- journal section -----------------------------------------------------
  function cardEl(p) {
    var card = document.createElement("button");
    card.type = "button";
    card.className = "jr-card";
    var dateStr = fmtDate(p.created_at);
    card.innerHTML =
      (dateStr ? '<div class="jr-date">' + esc(dateStr) + "</div>" : "") +
      '<div class="jr-title">' + esc(p.title || "") + "</div>" +
      (p.excerpt ? '<div class="jr-ex">' + esc(p.excerpt) + "</div>" : "") +
      '<div class="jr-more">' + esc(readMore()) + "</div>";
    card.addEventListener("click", function () {
      openPost(p.slug);
    });
    return card;
  }

  function renderJournal(posts) {
    if (!Array.isArray(posts) || !posts.length) return;
    if (document.getElementById("journal")) return;
    injectStyle();

    var sec = document.createElement("section");
    sec.id = "journal";
    sec.innerHTML =
      '<div class="jr-wrap">' +
      '<div class="jr-head">' +
      '<span class="jr-eb">' + tt("blog_eb") + "</span>" +
      '<h2 class="jr-h">' + tt("blog_h") + "</h2>" +
      "</div>" +
      '<div class="jr-grid"></div>' +
      "</div>";
    var grid = sec.querySelector(".jr-grid");
    posts.slice(0, 3).forEach(function (p) {
      grid.appendChild(cardEl(p));
    });

    var footer = document.querySelector("footer");
    if (footer && footer.parentNode) {
      footer.parentNode.insertBefore(sec, footer);
    } else {
      document.body.appendChild(sec);
    }
  }

  // ---- help center ---------------------------------------------------------
  var helpPosts = [];

  function openHelp() {
    injectStyle();
    var bg = makeModal("als-help");
    var body = bg._body;
    var items = helpPosts
      .map(function (p) {
        return (
          '<div class="hc-item">' +
          '<button type="button" class="hc-q"><span>' +
          esc(p.title || "") +
          '</span><span class="hc-ic">+</span></button>' +
          '<div class="hc-a"><div class="hc-a-in">' +
          bodyHTML(p.body) +
          "</div></div>" +
          "</div>"
        );
      })
      .join("");
    body.innerHTML =
      "<h3>" + esc(helpLabel()) + "</h3>" +
      '<div class="hc-list">' +
      (items || "<p style='color:var(--muted);font-size:13px'>" +
        esc(L("No articles yet.", "記事はまだありません。")) +
        "</p>") +
      "</div>";

    // Accordion: help list may lack bodies (list API omits body) — fetch lazily.
    var itemEls = body.querySelectorAll(".hc-item");
    helpPosts.forEach(function (p, i) {
      var el = itemEls[i];
      if (!el) return;
      var q = el.querySelector(".hc-q");
      var ain = el.querySelector(".hc-a-in");
      var loaded = p.body != null && p.body !== "";
      q.addEventListener("click", function () {
        var willOpen = !el.classList.contains("open");
        el.classList.toggle("open");
        if (willOpen && !loaded && p.slug) {
          loaded = true;
          apiPost(p.slug)
            .then(function (full) {
              if (full && full.body != null) ain.innerHTML = bodyHTML(full.body);
            })
            .catch(function () {});
        }
      });
    });

    bg.classList.add("open");
  }

  function wireHelpLink() {
    var footer = document.querySelector("footer");
    if (footer) {
      if (!document.getElementById("helpLink")) {
        var col = footer.querySelector(".ft-grid > div:last-child") || footer.querySelector(".ft-grid > div") || footer.querySelector(".wrap") || footer;
        var a = document.createElement("a");
        a.href = "#";
        a.id = "helpLink";
        a.textContent = helpLabel();
        a.addEventListener("click", function (e) {
          e.preventDefault();
          openHelp();
        });
        col.appendChild(a);
      }
    }
    // Always expose a programmatic entry point too.
    window.ALS = window.ALS || {};
    window.ALS.openHelp = openHelp;
  }

  // ---- deep link ?post=<slug> ---------------------------------------------
  function handleDeepLink() {
    try {
      var params = new URLSearchParams(window.location.search);
      var slug = params.get("post");
      if (slug) openPost(slug);
    } catch (_e) {}
  }

  // ---- boot ----------------------------------------------------------------
  function boot() {
    // Blog teaser
    apiList("blog")
      .then(function (posts) {
        renderJournal(posts);
      })
      .catch(function () {});
    // Help center
    apiList("help")
      .then(function (posts) {
        helpPosts = posts || [];
        wireHelpLink();
      })
      .catch(function () {
        wireHelpLink();
      });
    handleDeepLink();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
