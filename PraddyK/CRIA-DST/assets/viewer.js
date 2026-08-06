/* ============================================================================
   CRIA Interactive Image & Chart Viewer
   ----------------------------------------------------------------------------
   Adds a "⤢ View" button to every Plotly chart, map and image. Clicking it (or
   the element) opens it in a large in-page modal overlay that stays interactive:
   • Images / maps / GIFs  → zoom (wheel or +/−), pan (drag), reset.
   • Plotly charts         → the LIVE chart is moved into the modal, so native
     drag-to-zoom, pan and double-click-reset keep working; +/− and ⟲ also work.
   Close (✕), background-click or Esc returns to the page unchanged.
   Pure client-side — Dash auto-loads it; no app logic touched.
============================================================================ */
(function () {
  if (typeof window === "undefined") return;

  // ── build the overlay once ──
  var ov = document.createElement("div");
  ov.className = "cria-viewer";
  ov.innerHTML =
    '<div class="cv-bar">' +
      '<button class="cv-btn cv-zin"   title="Zoom in"  aria-label="Zoom in">+</button>' +
      '<button class="cv-btn cv-zout"  title="Zoom out" aria-label="Zoom out">−</button>' +
      '<button class="cv-btn cv-reset" title="Reset"    aria-label="Reset">⟲</button>' +
      '<button class="cv-btn cv-close" title="Close"    aria-label="Close">✕</button>' +
    "</div>" +
    '<div class="cv-hint">Scroll or +/− to zoom · drag to pan · Esc to close</div>' +
    '<div class="cv-stage"></div>';
  function ready() { document.body.appendChild(ov); }
  if (document.body) ready(); else document.addEventListener("DOMContentLoaded", ready);

  var stage = ov.querySelector(".cv-stage");
  var st = { mode: null, node: null, ph: null, img: null, scale: 1, x: 0, y: 0 };

  function applyImg() {
    if (st.img) st.img.style.transform =
      "translate(" + st.x + "px," + st.y + "px) scale(" + st.scale + ")";
  }
  function openImage(src) {
    st.mode = "img"; st.scale = 1; st.x = 0; st.y = 0;
    var img = document.createElement("img");
    img.className = "cv-img"; img.src = src; st.img = img;
    stage.innerHTML = ""; stage.appendChild(img); applyImg(); show();
  }
  function openPlot(node) {
    st.mode = "plot"; st.node = node;
    var ph = document.createElement("div"); ph.style.display = "none"; st.ph = ph;
    node.parentNode.insertBefore(ph, node);
    stage.innerHTML = "";
    var wrap = document.createElement("div"); wrap.className = "cv-plot";
    wrap.appendChild(node); stage.appendChild(wrap); show();
    resizePlot(node);
  }
  function resizePlot(node) {
    setTimeout(function () { if (window.Plotly) { try { window.Plotly.Plots.resize(node); } catch (e) {} } }, 70);
  }
  function show() { ov.classList.add("open"); document.body.style.overflow = "hidden"; }
  function close() {
    ov.classList.remove("open"); document.body.style.overflow = "";
    if (st.mode === "plot" && st.node && st.ph) {
      st.ph.parentNode.insertBefore(st.node, st.ph); st.ph.remove();
      resizePlot(st.node);
    }
    stage.innerHTML = "";
    st.mode = null; st.node = null; st.img = null; st.ph = null;
  }
  function zoom(f) {
    if (st.mode === "img") { st.scale = Math.max(0.4, Math.min(9, st.scale * f)); applyImg(); }
    else if (st.node && window.Plotly) {
      try {
        var fl = st.node._fullLayout;
        if (fl && fl.xaxis && fl.yaxis && fl.xaxis.range && fl.yaxis.range) {
          var xr = fl.xaxis.range.slice(), yr = fl.yaxis.range.slice();
          var cx = (+xr[0] + +xr[1]) / 2, cy = (+yr[0] + +yr[1]) / 2;
          var hw = (+xr[1] - +xr[0]) / 2 / f, hh = (+yr[1] - +yr[0]) / 2 / f;
          window.Plotly.relayout(st.node, { "xaxis.range": [cx - hw, cx + hw], "yaxis.range": [cy - hh, cy + hh] });
        }
      } catch (e) {}
    }
  }
  function reset() {
    if (st.mode === "img") { st.scale = 1; st.x = 0; st.y = 0; applyImg(); }
    else if (st.node && window.Plotly) {
      try { window.Plotly.relayout(st.node, { "xaxis.autorange": true, "yaxis.autorange": true }); } catch (e) {}
    }
  }

  ov.querySelector(".cv-close").onclick = close;
  ov.querySelector(".cv-zin").onclick   = function () { zoom(1.3); };
  ov.querySelector(".cv-zout").onclick  = function () { zoom(0.77); };
  ov.querySelector(".cv-reset").onclick = reset;
  ov.addEventListener("click", function (e) { if (e.target === ov || e.target === stage) close(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && ov.classList.contains("open")) close(); });

  // image pan + wheel-zoom
  var drag = false, sx = 0, sy = 0;
  stage.addEventListener("mousedown", function (e) {
    if (st.mode === "img") { drag = true; sx = e.clientX - st.x; sy = e.clientY - st.y; e.preventDefault(); }
  });
  window.addEventListener("mousemove", function (e) {
    if (drag && st.mode === "img") { st.x = e.clientX - sx; st.y = e.clientY - sy; applyImg(); }
  });
  window.addEventListener("mouseup", function () { drag = false; });
  stage.addEventListener("wheel", function (e) {
    if (st.mode === "img") { e.preventDefault(); zoom(e.deltaY < 0 ? 1.14 : 0.88); }
  }, { passive: false });

  // ── attach "View" buttons ──
  var seen = (typeof WeakSet !== "undefined") ? new WeakSet() : null;
  function attach(el, kind) {
    if (seen && seen.has(el)) return; if (seen) seen.add(el);
    var b = document.createElement("button");
    b.className = "cv-view"; b.type = "button";
    b.title = "Expand — open a large, zoomable view";
    b.setAttribute("aria-label", "Expand to a large, zoomable view");
    b.innerHTML = '<i class="bi bi-arrows-angle-expand"></i>';
    b.addEventListener("click", function (ev) {
      ev.preventDefault(); ev.stopPropagation();
      if (kind === "img") openImage(el.currentSrc || el.src); else openPlot(el);
    });
    var host = (kind === "plot") ? (el.closest(".dash-graph") || el.parentNode) : el.parentNode;
    if (!host) return;
    try { if (getComputedStyle(host).position === "static") host.style.position = "relative"; } catch (e) {}
    host.appendChild(b);
  }
  function scan() {
    document.querySelectorAll(".js-plotly-plot").forEach(function (n) { attach(n, "plot"); });
    document.querySelectorAll(".crb-card img, .tab-body img, .sig-card img").forEach(function (im) {
      if (im.classList.contains("cv-img")) return;
      if (im.classList.contains("tabcard-img") || im.closest(".tabshow-grid")) return;  // overview tab-preview cards
      if (im.closest(".app-header")) return;                 // NASA/ASU/CAP logos
      if (im.closest(".cria-viewer")) return;
      var w = im.naturalWidth || im.width || 0;
      if (w && w < 110) return;                              // small icons/avatars
      if (/logo|favicon|avatar|nasa|asu|cap\./i.test(im.src || "")) return;
      attach(im, "img");
    });
  }
  document.addEventListener("DOMContentLoaded", scan);
  window.addEventListener("load", scan);
  setInterval(scan, 1500);   // catch Dash re-renders / newly opened tabs
})();
