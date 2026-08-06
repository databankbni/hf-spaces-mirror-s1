/* CRIA — lightweight self-contained onboarding tour (no libraries).
   The highlight ring CONTINUOUSLY tracks its target for a short window after each
   step, so it stays locked on even while the page scrolls or content reflows. */
(function () {
  // Ordered top-to-bottom so the page only ever scrolls DOWN — never jumps back up.
  var STEPS = [
    { sel: "#sidebar", t: "Every analysis lives here",
      d: "All 32 analyses across 6 decision themes. Click a theme to open its tabs — supply, drought, scenarios, maps, governance." },
    { sel: "#ria-fab-sb, #ria-fab", t: "Ask RIA, your assistant",
      d: "Ask any question in plain language on any tab. RIA can take you to any analysis. Confidential items (budgets, salaries) are blocked by design." },
    { sel: ".tk-bar", t: "Live basin signals",
      d: "The key numbers from 43 water years, scrolling. Red = concerning, green = validated — each one is real and computed from the record." },
    { sel: ".re-grid", t: "Start with your role",
      d: "New here? Pick who you are and we point you straight to the analyses that matter most. Nothing is locked — every tab stays open to everyone." },
    { sel: ".oq-wrap, .sig-card", t: "Proven — and honest",
      d: "Every headline number is validated against NASA GRACE, SMAP and SNOTEL and matched to a peer-reviewed paper. The tool also shows what is still open." }
  ];

  var overlay, spot, tip, i = 0, active = false;
  var curTgt = null, rafId = 0, trackUntil = 0, completed = false;

  // Where the guided workflow leads once the tour ends — the first analysis to open.
  var NEXT = { href: "/snowpack", label: "Snowpack & Runoff" };

  // A small "tour complete → next step" toast, shown only on genuine completion.
  function showToast() {
    var old = document.getElementById("tour-toast"); if (old) old.remove();
    var t = document.createElement("div"); t.id = "tour-toast";
    t.style.cssText = "position:fixed;left:50%;bottom:26px;transform:translateX(-50%) translateY(14px);" +
      "z-index:100000;display:flex;align-items:center;gap:14px;background:#fff;border:1px solid #eadfe4;" +
      "border-top:3px solid #FFC627;border-radius:14px;box-shadow:0 16px 40px rgba(13,33,55,.24);" +
      "padding:13px 16px;opacity:0;transition:opacity .3s ease,transform .3s cubic-bezier(.2,.7,.3,1);" +
      "font-family:inherit;max-width:min(92vw,460px);";
    t.innerHTML =
      '<span style="display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;' +
      'border-radius:50%;background:#e9f7ee;color:#1f7a3d;flex:0 0 auto;">' +
      '<i class="bi bi-check-lg" style="font-size:17px;"></i></span>' +
      '<div style="display:flex;flex-direction:column;min-width:0;">' +
      '<span style="font-size:12px;font-weight:800;color:#0D2137;">Tour complete — you\'re oriented.</span>' +
      '<span style="font-size:11px;color:#64748b;">Next in the workflow: start with an analysis.</span></div>' +
      '<a href="' + NEXT.href + '" id="tour-toast-go" style="white-space:nowrap;background:#8C1D40;color:#fff;' +
      'border-radius:9px;padding:8px 12px;font-size:11.5px;font-weight:800;text-decoration:none;' +
      'display:inline-flex;align-items:center;gap:6px;">' + NEXT.label +
      ' <i class="bi bi-arrow-right"></i></a>' +
      '<button id="tour-toast-x" aria-label="Dismiss" style="background:none;border:none;cursor:pointer;' +
      'color:#94a3b8;font-size:16px;line-height:1;padding:2px;">&times;</button>';
    document.body.appendChild(t);
    requestAnimationFrame(function () { requestAnimationFrame(function () {
      t.style.opacity = "1"; t.style.transform = "translateX(-50%) translateY(0)"; }); });
    var hide = function () { t.style.opacity = "0"; t.style.transform = "translateX(-50%) translateY(14px)";
      setTimeout(function () { if (t.parentNode) t.remove(); }, 320); };
    t.querySelector("#tour-toast-x").onclick = hide;
    t.querySelector("#tour-toast-go").addEventListener("click", hide);
    setTimeout(hide, 9000);   // auto-dismiss
  }

  function el(tag, cls) { var e = document.createElement(tag); if (cls) e.className = cls; return e; }

  function build() {
    overlay = el("div", "tour-overlay");
    spot = el("div", "tour-spot");
    tip = el("div", "tour-tip");
    overlay.appendChild(spot);
    document.body.appendChild(overlay);
    document.body.appendChild(tip);
    overlay.addEventListener("click", end);
  }

  function target(step) {
    var sels = step.sel.split(",");
    for (var k = 0; k < sels.length; k++) {
      var e = document.querySelector(sels[k].trim());
      if (e && e.getClientRects().length && e.getBoundingClientRect().width > 0) return e;
    }
    return null;
  }

  // Position the ring on the target's CURRENT rect (clamped to the viewport).
  function positionSpot(tgt) {
    var r = tgt.getBoundingClientRect(), pad = 8;
    var sTop = r.top - pad, sH = r.height + pad * 2;
    var vT = 10, vB = window.innerHeight - 10;
    if (sTop < vT) { sH -= (vT - sTop); sTop = vT; }
    if (sTop + sH > vB) { sH = vB - sTop; }
    sH = Math.max(30, sH);
    spot.style.top = sTop + "px";
    spot.style.left = (r.left - pad) + "px";
    spot.style.width = (r.width + pad * 2) + "px";
    spot.style.height = sH + "px";
    return { r: r, sTop: sTop, sH: sH };
  }

  function positionTip(r, sTop, sH) {
    var tr = tip.getBoundingClientRect();
    var visBottom = sTop + sH;
    var top = visBottom + 14;
    if (top + tr.height > window.innerHeight - 10) top = sTop - tr.height - 14;
    top = Math.max(10, Math.min(top, window.innerHeight - tr.height - 10));
    var left = r.left + r.width / 2 - tr.width / 2;
    left = Math.min(Math.max(10, left), window.innerWidth - tr.width - 10);
    if (!isFinite(left) || left < 0) left = 10;
    tip.style.top = top + "px";
    tip.style.left = left + "px";
  }

  function reflow() {
    if (!active || !curTgt) return;
    var p = positionSpot(curTgt);
    positionTip(p.r, p.sTop, p.sH);
  }

  // rAF loop: keep the ring glued to the target while it scrolls / the page reflows.
  function track() {
    if (!active || !curTgt) return;
    reflow();
    if (Date.now() < trackUntil) rafId = requestAnimationFrame(track);
  }

  function show() {
    if (i < 0) i = 0;
    if (i >= STEPS.length) { completed = true; return end(); }
    var step = STEPS[i], tgt = target(step);
    if (!tgt) { i++; return show(); }
    curTgt = tgt;
    // tip content (set once per step; only its POSITION updates during tracking)
    tip.innerHTML =
      '<div class="tour-step">Step ' + (i + 1) + ' of ' + STEPS.length + '</div>' +
      '<div class="tour-t">' + step.t + '</div>' +
      '<div class="tour-d">' + step.d + '</div>' +
      '<div class="tour-btns">' +
        '<button class="tour-skip">Skip</button>' +
        '<span style="flex:1"></span>' +
        (i > 0 ? '<button class="tour-prev">Back</button>' : '') +
        '<button class="tour-next">' + (i === STEPS.length - 1 ? "Done" : "Next →") + '</button>' +
      '</div>';
    tip.querySelector(".tour-skip").onclick = end;
    tip.querySelector(".tour-next").onclick = function () { i++; show(); };
    var pv = tip.querySelector(".tour-prev"); if (pv) pv.onclick = function () { i--; show(); };
    // scroll the target into view (instant), then TRACK it for a moment so the ring
    // lands correctly no matter how long the scroll / chart reflow takes.
    var r0 = tgt.getBoundingClientRect();
    var inView = r0.top >= 0 && r0.bottom <= window.innerHeight;
    var tall = r0.height > window.innerHeight * 0.7;
    if (!inView) tgt.scrollIntoView({ block: tall ? "start" : "center", inline: "nearest", behavior: "auto" });
    reflow();                       // immediate best-effort placement
    trackUntil = Date.now() + 1400; // then glue to it for 1.4s (absorbs scroll + reflow)
    if (rafId) cancelAnimationFrame(rafId);
    rafId = requestAnimationFrame(track);
  }

  function start() {
    if (active) return;
    active = true; i = 0;
    build();
    requestAnimationFrame(show);
  }

  function end() {
    active = false; curTgt = null;
    if (rafId) { cancelAnimationFrame(rafId); rafId = 0; }
    if (overlay) overlay.remove();
    if (tip) tip.remove();
    overlay = tip = spot = null;
    if (completed) { completed = false; showToast(); }   // only on genuine completion
  }

  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("#tour-btn");
    if (b) { e.preventDefault(); start(); }
  });
  // keep the ring aligned if the user scrolls or resizes mid-step
  window.addEventListener("scroll", reflow, true);
  window.addEventListener("resize", reflow);
})();
