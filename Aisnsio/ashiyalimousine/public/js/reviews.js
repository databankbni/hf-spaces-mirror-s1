/* Ashiya Limousine — Guest Reviews */
/* Owns: public/js/reviews.js — loads via <script defer> after main inline script. */
(function () {
  "use strict";
  if (window.__ALS_REVIEWS__) return;
  window.__ALS_REVIEWS__ = true;

  var C = window.ALSCore || {};
  var esc = typeof C.esc === "function" ? C.esc : function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };
  var tt = typeof C.tt === "function" ? C.tt : function () { return ""; };
  function isJa() { return C.L === "ja"; }

  /* ---------- i18n (self-contained strings not in main dict) ---------- */
  var T = {
    en: {
      reviews_word: "reviews",
      review_word: "review",
      based_on: "Based on",
      no_reviews: "Be the first to share your experience.",
      modal_h: "Write a review",
      modal_p: "Tell us about your journey. Reviews appear after a brief moderation.",
      f_name: "Your name",
      f_rating: "Rating",
      f_title: "Title",
      f_occasion: "Occasion (optional)",
      f_body: "Your review",
      f_body_ph: "What made the experience memorable?",
      f_occasion_ph: "e.g. Wedding, Anniversary, Airport",
      submit: "Submit review",
      sending: "Sending…",
      thanks: "Thank you — your review will appear after moderation.",
      err_name: "Please enter your name.",
      err_rating: "Please choose a rating.",
      err_fail: "Sorry, something went wrong. Please try again.",
      close: "Close",
      stars_label: "stars"
    },
    ja: {
      reviews_word: "件のレビュー",
      review_word: "件のレビュー",
      based_on: "評価件数",
      no_reviews: "最初のご感想をぜひお寄せください。",
      modal_h: "レビューを書く",
      modal_p: "ご乗車の思い出をお聞かせください。レビューは確認後に掲載されます。",
      f_name: "お名前",
      f_rating: "評価",
      f_title: "タイトル",
      f_occasion: "ご利用シーン（任意）",
      f_body: "レビュー内容",
      f_body_ph: "印象に残った点をお聞かせください。",
      f_occasion_ph: "例：ご結婚式、記念日、空港送迎",
      submit: "レビューを送信",
      sending: "送信中…",
      thanks: "ありがとうございます。レビューは確認後に掲載されます。",
      err_name: "お名前をご入力ください。",
      err_rating: "評価をお選びください。",
      err_fail: "送信に失敗しました。もう一度お試しください。",
      close: "閉じる",
      stars_label: "つ星"
    }
  };
  function L(k) { return (T[isJa() ? "ja" : "en"][k]) || ""; }

  /* ---------- helpers ---------- */
  function starHTML(rating) {
    var r = Math.max(0, Math.min(5, Math.round(Number(rating) || 0)));
    var out = "";
    for (var i = 1; i <= 5; i++) out += (i <= r ? "★" : "☆");
    return out;
  }

  function injectStyle() {
    if (document.getElementById("als-rev-style")) return;
    var css =
      "#reviews{padding:96px 0;position:relative}" +
      "#reviews .rev-wrap{max-width:1180px;margin:0 auto;padding:0 22px}" +
      "#reviews .rev-head{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:26px;margin-bottom:42px}" +
      "#reviews .rev-eb{font-family:var(--mono);font-size:10.5px;letter-spacing:.28em;text-transform:uppercase;" +
        "color:var(--gold);font-weight:700;display:flex;align-items:center;gap:12px}" +
      "#reviews .rev-eb::before{content:'';width:26px;height:1px;background:var(--gold)}" +
      "html[lang='ja'] #reviews .rev-eb{letter-spacing:.42em}" +
      "#reviews h2.rev-h{font-family:var(--serif);font-weight:600;line-height:1.14;color:var(--cream);" +
        "font-size:clamp(30px,4.4vw,46px);margin:14px 0 0}" +
      "#reviews .rev-score{display:flex;flex-direction:column;gap:8px;align-items:flex-start;min-width:220px}" +
      "#reviews .rev-score .avg{display:flex;align-items:baseline;gap:12px}" +
      "#reviews .rev-score .num{font-family:var(--serif);font-size:52px;font-weight:600;color:var(--gold2);line-height:.9}" +
      "#reviews .rev-score .stars{font-size:22px;color:var(--gold);letter-spacing:2px;line-height:1}" +
      "#reviews .rev-score .meta{font-size:12px;color:var(--muted);letter-spacing:.04em}" +
      "#reviews .rev-write-top{margin-top:4px;display:inline-flex;align-items:center;justify-content:center;gap:9px;" +
        "padding:12px 24px;border-radius:99px;font-weight:700;font-size:13px;letter-spacing:.06em;cursor:pointer;" +
        "font-family:var(--sans);border:1px solid var(--line);color:var(--gold2);background:transparent;transition:.22s}" +
      "#reviews .rev-write-top:hover{border-color:var(--gold);background:var(--golddim)}" +
      "#reviews .rev-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}" +
      "#reviews .rev-card{border:1px solid var(--hair);border-radius:16px;padding:26px 24px;" +
        "background:linear-gradient(172deg,var(--panel),transparent 72%);display:flex;flex-direction:column;gap:12px;transition:.25s}" +
      "#reviews .rev-card:hover{border-color:var(--line);transform:translateY(-3px)}" +
      "#reviews .rev-card .rc-stars{color:var(--gold);font-size:15px;letter-spacing:2px;line-height:1}" +
      "#reviews .rev-card .rc-title{font-family:var(--serif);font-size:21px;font-weight:600;line-height:1.22;color:var(--cream)}" +
      "#reviews .rev-card .rc-body{font-size:13.5px;line-height:1.6;color:var(--muted);flex:1}" +
      "#reviews .rev-card .rc-foot{display:flex;align-items:center;gap:10px;margin-top:4px;padding-top:14px;border-top:1px solid var(--hair)}" +
      "#reviews .rev-card .rc-author{font-size:12.5px;font-weight:700;color:var(--cream);letter-spacing:.02em}" +
      "#reviews .rev-card .rc-occ{font-family:var(--mono);font-size:10px;letter-spacing:.16em;text-transform:uppercase;color:var(--gold);white-space:nowrap}" +
      "#reviews .rev-empty{color:var(--faint);font-size:14px;padding:8px 0}" +
      /* modal */
      "#reviews-modal.modal-bg{position:fixed;inset:0;z-index:1200;display:none;align-items:center;justify-content:center;" +
        "padding:22px;background:rgba(5,7,14,.72);backdrop-filter:blur(6px)}" +
      "#reviews-modal.modal-bg.open{display:flex}" +
      "#reviews-modal .modal-card{width:100%;max-width:520px;max-height:90vh;overflow:auto;border:1px solid var(--line);" +
        "border-radius:18px;padding:32px 30px;background:linear-gradient(172deg,#141A31,var(--ink2) 78%);position:relative;" +
        "box-shadow:0 40px 90px -30px rgba(0,0,0,.7)}" +
      "#reviews-modal .modal-x{position:absolute;top:16px;right:16px;width:34px;height:34px;border-radius:50%;" +
        "border:1px solid var(--hair);background:transparent;color:var(--muted);cursor:pointer;font-size:18px;line-height:1;transition:.2s}" +
      "#reviews-modal .modal-x:hover{border-color:var(--gold);color:var(--gold2)}" +
      "#reviews-modal .modal-eb{font-family:var(--mono);font-size:10px;letter-spacing:.26em;text-transform:uppercase;color:var(--gold);font-weight:700}" +
      "#reviews-modal h3{font-family:var(--serif);font-size:28px;font-weight:600;color:var(--cream);margin:8px 0 6px;line-height:1.15}" +
      "#reviews-modal .modal-sub{font-size:12.5px;color:var(--muted);line-height:1.5;margin-bottom:20px}" +
      "#reviews-modal .fld{margin-bottom:16px}" +
      "#reviews-modal label{display:block;font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--faint);font-weight:700;margin-bottom:7px}" +
      "#reviews-modal input,#reviews-modal textarea{width:100%;background:rgba(255,255,255,.03);border:1px solid var(--hair);" +
        "border-radius:10px;padding:12px 14px;color:var(--cream);font-family:var(--sans);font-size:14px;transition:.2s}" +
      "#reviews-modal input:focus,#reviews-modal textarea:focus{outline:none;border-color:var(--gold);background:rgba(255,255,255,.05)}" +
      "#reviews-modal textarea{resize:vertical;min-height:96px}" +
      "#reviews-modal .rate-pick{display:flex;gap:6px;font-size:30px;line-height:1;user-select:none}" +
      "#reviews-modal .rate-pick .st{cursor:pointer;color:var(--faint);transition:.15s;color:var(--hair)}" +
      "#reviews-modal .rate-pick .st.on{color:var(--gold)}" +
      "#reviews-modal .rate-pick:hover .st{color:var(--hair)}" +
      "#reviews-modal .rate-pick .st.hov{color:var(--gold2)}" +
      "#reviews-modal .err{color:var(--bad);font-size:12px;margin-top:-8px;margin-bottom:12px;min-height:0}" +
      "#reviews-modal .modal-submit{width:100%;display:inline-flex;align-items:center;justify-content:center;gap:9px;" +
        "padding:14px 26px;border-radius:99px;font-weight:700;font-size:14px;letter-spacing:.06em;cursor:pointer;border:0;" +
        "font-family:var(--sans);color:#1b1503;margin-top:6px;transition:.22s;" +
        "background:linear-gradient(120deg,var(--gold) 0%,var(--gold2) 55%,var(--gold) 100%);box-shadow:0 10px 30px -10px rgba(212,175,55,.45)}" +
      "#reviews-modal .modal-submit:hover{transform:translateY(-2px)}" +
      "#reviews-modal .modal-submit:disabled{opacity:.6;cursor:default;transform:none}" +
      "#reviews-modal .thanks{text-align:center;padding:24px 6px}" +
      "#reviews-modal .thanks .tick{font-size:44px;color:var(--gold);line-height:1}" +
      "#reviews-modal .thanks p{font-family:var(--serif);font-size:20px;color:var(--cream);line-height:1.4;margin-top:14px}" +
      "@media(max-width:900px){#reviews .rev-grid{grid-template-columns:1fr}#reviews{padding:70px 0}" +
        "#reviews .rev-head{flex-direction:column;align-items:flex-start}}";
    var st = document.createElement("style");
    st.id = "als-rev-style";
    st.textContent = css;
    document.head.appendChild(st);
  }

  /* ---------- modal ---------- */
  var modal, curRating = 0, escHandler = null;

  function buildModal() {
    if (modal) return modal;
    modal = document.createElement("div");
    modal.id = "reviews-modal";
    modal.className = "modal-bg";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");

    var starsMarkup = "";
    for (var i = 1; i <= 5; i++) starsMarkup += '<span class="st" data-v="' + i + '">☆</span>';

    modal.innerHTML =
      '<div class="modal-card">' +
      '<button type="button" class="modal-x" aria-label="' + esc(L("close")) + '">&times;</button>' +
      '<div class="modal-body">' +
      '<span class="modal-eb">' + esc(L("modal_h")) + "</span>" +
      "<h3>" + esc(L("modal_h")) + "</h3>" +
      '<p class="modal-sub">' + esc(L("modal_p")) + "</p>" +
      '<form class="rev-form" novalidate>' +
      '<div class="fld"><label>' + esc(L("f_name")) + '</label><input type="text" name="name" autocomplete="name" maxlength="80"></div>' +
      '<div class="fld"><label>' + esc(L("f_rating")) + '</label><div class="rate-pick" role="radiogroup">' + starsMarkup + "</div></div>" +
      '<div class="fld"><label>' + esc(L("f_title")) + '</label><input type="text" name="title" maxlength="120"></div>' +
      '<div class="fld"><label>' + esc(L("f_occasion")) + '</label><input type="text" name="occasion" maxlength="80" placeholder="' + esc(L("f_occasion_ph")) + '"></div>' +
      '<div class="fld"><label>' + esc(L("f_body")) + '</label><textarea name="body" maxlength="1200" placeholder="' + esc(L("f_body_ph")) + '"></textarea></div>' +
      '<div class="err" role="alert"></div>' +
      '<button type="submit" class="modal-submit">' + esc(L("submit")) + "</button>" +
      "</form>" +
      "</div>" +
      "</div>";

    document.body.appendChild(modal);

    var card = modal.querySelector(".modal-card");
    modal.addEventListener("mousedown", function (e) { if (e.target === modal) closeModal(); });
    modal.querySelector(".modal-x").addEventListener("click", closeModal);
    if (card) card.addEventListener("mousedown", function (e) { e.stopPropagation(); });

    // star selector
    var pick = modal.querySelector(".rate-pick");
    var sts = pick.querySelectorAll(".st");
    function paint(n) {
      sts.forEach(function (s) {
        var v = Number(s.getAttribute("data-v"));
        s.textContent = v <= n ? "★" : "☆";
        s.classList.toggle("on", v <= curRating);
        s.classList.toggle("hov", n > 0 && v <= n);
      });
    }
    sts.forEach(function (s) {
      var v = Number(s.getAttribute("data-v"));
      s.addEventListener("mouseenter", function () { paint(v); });
      s.addEventListener("click", function () { curRating = v; paint(0); });
    });
    pick.addEventListener("mouseleave", function () { paint(0); });

    modal.querySelector(".rev-form").addEventListener("submit", onSubmit);
    return modal;
  }

  function openModal() {
    buildModal();
    curRating = 0;
    resetForm();
    modal.classList.add("open");
    escHandler = function (e) { if (e.key === "Escape") closeModal(); };
    document.addEventListener("keydown", escHandler);
    var first = modal.querySelector('input[name="name"]');
    if (first) setTimeout(function () { try { first.focus(); } catch (e) {} }, 30);
  }

  function closeModal() {
    if (!modal) return;
    modal.classList.remove("open");
    if (escHandler) { document.removeEventListener("keydown", escHandler); escHandler = null; }
  }

  function resetForm() {
    if (!modal) return;
    var body = modal.querySelector(".modal-body");
    var form = modal.querySelector(".rev-form");
    if (form) {
      form.reset();
      form.style.display = "";
      var sts = form.querySelectorAll(".rate-pick .st");
      sts.forEach(function (s) { s.textContent = "☆"; s.classList.remove("on", "hov"); });
      var err = form.querySelector(".err");
      if (err) err.textContent = "";
      var btn = form.querySelector(".modal-submit");
      if (btn) { btn.disabled = false; btn.textContent = L("submit"); }
    }
    var th = body ? body.querySelector(".thanks") : null;
    if (th) th.parentNode.removeChild(th);
    var eb = body ? body.querySelector(".modal-eb") : null;
    var h3 = body ? body.querySelector("h3") : null;
    var sub = body ? body.querySelector(".modal-sub") : null;
    if (eb) eb.style.display = "";
    if (h3) h3.style.display = "";
    if (sub) sub.style.display = "";
  }

  function showThanks() {
    var body = modal.querySelector(".modal-body");
    var form = modal.querySelector(".rev-form");
    if (form) form.style.display = "none";
    ["modal-eb", "modal-sub"].forEach(function (c) {
      var el = body.querySelector("." + c); if (el) el.style.display = "none";
    });
    var h3 = body.querySelector("h3"); if (h3) h3.style.display = "none";
    var th = document.createElement("div");
    th.className = "thanks";
    th.innerHTML = '<div class="tick">&#10003;</div><p>' + esc(L("thanks")) + "</p>";
    body.appendChild(th);
    setTimeout(closeModal, 2600);
  }

  function onSubmit(e) {
    e.preventDefault();
    var form = e.currentTarget;
    var err = form.querySelector(".err");
    var name = (form.name.value || "").trim();
    if (!name) { if (err) err.textContent = L("err_name"); return; }
    if (!(curRating >= 1 && curRating <= 5)) { if (err) err.textContent = L("err_rating"); return; }
    if (err) err.textContent = "";

    var payload = {
      author_name: name,
      rating: curRating,
      title: (form.title.value || "").trim(),
      occasion: (form.occasion.value || "").trim(),
      body: (form.body.value || "").trim()
    };

    var btn = form.querySelector(".modal-submit");
    if (btn) { btn.disabled = true; btn.textContent = L("sending"); }

    fetch("/api/reviews", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload)
    })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json().catch(function () { return {}; }); })
      .then(function () { showThanks(); })
      .catch(function () {
        if (err) err.textContent = L("err_fail");
        if (btn) { btn.disabled = false; btn.textContent = L("submit"); }
      });
  }

  /* ---------- render section ---------- */
  function cardHTML(rv) {
    var occ = rv.occasion ? '<span class="rc-occ">' + esc(rv.occasion) + "</span>" : "";
    return (
      '<article class="rev-card">' +
      '<div class="rc-stars" aria-label="' + esc(rv.rating + " " + L("stars_label")) + '">' + starHTML(rv.rating) + "</div>" +
      (rv.title ? '<div class="rc-title">' + esc(rv.title) + "</div>" : "") +
      (rv.body ? '<div class="rc-body">' + esc(rv.body) + "</div>" : "") +
      '<div class="rc-foot"><span class="rc-author">' + esc(rv.author_name || "") + "</span>" + occ + "</div>" +
      "</article>"
    );
  }

  function render(data) {
    injectStyle();
    var reviews = (data && Array.isArray(data.reviews)) ? data.reviews : [];
    var count = (data && typeof data.count === "number") ? data.count : reviews.length;
    var avg = (data && typeof data.average === "number") ? data.average : 0;
    var avgTxt = avg ? avg.toFixed(1) : "—";
    var word = count === 1 ? L("review_word") : L("reviews_word");
    var meta = isJa() ? (count + word) : (count + " " + word);

    var sec = document.createElement("section");
    sec.id = "reviews";
    sec.innerHTML =
      '<div class="rev-wrap">' +
      '<div class="rev-head">' +
      "<div>" +
      '<span class="rev-eb">' + tt("rev_eb") + "</span>" +
      '<h2 class="rev-h">' + tt("rev_h") + "</h2>" +
      "</div>" +
      '<div class="rev-score">' +
      '<div class="avg"><span class="num">' + esc(avgTxt) + '</span><span class="stars">' + starHTML(avg) + "</span></div>" +
      '<span class="meta">' + esc(meta) + "</span>" +
      '<button type="button" class="rev-write-top">' + tt("rev_write") + "</button>" +
      "</div>" +
      "</div>" +
      (reviews.length
        ? '<div class="rev-grid">' + reviews.map(cardHTML).join("") + "</div>"
        : '<div class="rev-empty">' + esc(L("no_reviews")) + "</div>") +
      "</div>";

    var btn = sec.querySelector(".rev-write-top");
    if (btn) btn.addEventListener("click", openModal);

    var anchor = document.getElementById("contact") || document.getElementById("booking");
    if (anchor && anchor.parentNode) {
      anchor.parentNode.insertBefore(sec, anchor);
    } else {
      var main = document.querySelector("main") || document.body;
      if (main) main.appendChild(sec);
    }
  }

  function boot() {
    fetch("/api/reviews", { headers: { Accept: "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (data) { render(data || {}); })
      .catch(function (e) {
        console.warn("[reviews] could not load reviews:", e && e.message ? e.message : e);
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
