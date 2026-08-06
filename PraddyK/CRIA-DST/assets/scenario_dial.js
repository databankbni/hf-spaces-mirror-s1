/* CRIA — interactive animated warming dial for the landing page.
   Self-contained; reads the fitted response from the .scen-dial data attributes,
   auto-sweeps on load, then lets the user drag it live. No server round-trip. */
(function () {
  "use strict";
  function clamp(x, a, b) { a = a == null ? 0 : a; b = b == null ? 1 : b; return x < a ? a : x > b ? b : x; }
  function lerp(a, b, t) { return a + (b - a) * t; }
  function eInOut(x) { x = clamp(x); return x < .5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2; }

  var CX = 190, CY = 200, R = 150;
  function polar(d) { var r = d * Math.PI / 180; return [CX + R * Math.cos(r), CY - R * Math.sin(r)]; }
  function arc(d0, d1) {
    var a = polar(d0), b = polar(d1), large = Math.abs(d1 - d0) > 180 ? 1 : 0, sweep = d1 < d0 ? 1 : 0;
    return "M" + a[0].toFixed(1) + " " + a[1].toFixed(1) + " A" + R + " " + R + " 0 " + large + " " + sweep + " " + b[0].toFixed(1) + " " + b[1].toFixed(1);
  }
  function dtToDeg(dt) { return 180 - (dt / 5) * 180; }

  function build(el) {
    if (el.dataset.dialReady) return;
    var PROJ, R2;
    try { PROJ = JSON.parse(el.getAttribute("data-proj")); R2 = parseFloat(el.getAttribute("data-r2")) || 0.6; }
    catch (e) { return; }
    if (!PROJ || PROJ.length < 6) return;
    el.dataset.dialReady = "1";

    function proj(dt) {
      dt = clamp(dt, 0, 5); var i = Math.min(4, Math.floor(dt)), f = dt - i, a = PROJ[i], b = PROJ[i + 1];
      return { pct: lerp(a.pct, b.pct, f), maf: lerp(a.maf, b.maf, f), lo: lerp(a.lo, b.lo, f), hi: lerp(a.hi, b.hi, f) };
    }
    function statusOf(p) { return p >= -10 ? ["Normal", "#2E7D32"] : p > -25 ? ["Caution", "#E65100"] : ["Critical", "#B71C1C"]; }

    var ticks = "";
    for (var k = 0; k <= 5; k++) {
      var p = polar(dtToDeg(k)), lr = dtToDeg(k) * Math.PI / 180,
          lx = CX + (R + 26) * Math.cos(lr), ly = CY - (R + 26) * Math.sin(lr);
      ticks += '<circle cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1) + '" r="3" fill="#b0bcc9"/>'
             + '<text x="' + lx.toFixed(1) + '" y="' + (ly + 4).toFixed(1) + '" text-anchor="middle" class="sd-tick">+' + k + '</text>';
    }
    // ---- response curve (ΔT 0→5 vs % yield) with a 95% CI band ----
    function cxF(dt) { return 34 + dt / 5 * 252; }
    function cyF(v) { return 24 + (40 - v) / 110 * 160; }
    var linePts = "", hiPts = "", loPts = "";
    for (var j = 0; j < PROJ.length; j++) {
      linePts += (j ? " L" : "M") + cxF(PROJ[j].dt).toFixed(1) + " " + cyF(PROJ[j].pct).toFixed(1);
      hiPts += (j ? " L" : "M") + cxF(PROJ[j].dt).toFixed(1) + " " + cyF(PROJ[j].hi).toFixed(1);
    }
    for (var j2 = PROJ.length - 1; j2 >= 0; j2--) loPts += " L" + cxF(PROJ[j2].dt).toFixed(1) + " " + cyF(PROJ[j2].lo).toFixed(1);
    var band = hiPts + loPts + " Z", zeroY = cyF(0).toFixed(1);
    var curveSVG =
      '<div class="sd-curvetitle">Hotter → less water</div>'
      + '<svg class="sd-curve" viewBox="0 0 300 214">'
        + '<path d="' + band + '" fill="rgba(230,88,3,.10)"/>'
        + '<line x1="34" y1="' + zeroY + '" x2="286" y2="' + zeroY + '" stroke="#c9bfae" stroke-width="1.2" stroke-dasharray="4 3"/>'
        + '<path d="' + linePts + '" fill="none" stroke="#8C1D40" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>'
        + '<line class="sd-guide" x1="34" y1="24" x2="34" y2="184" stroke="#0D2137" stroke-width="1.2" stroke-dasharray="3 3" opacity=".4"/>'
        + '<circle class="sd-cmark" r="6.5" fill="#8C1D40" stroke="#fff" stroke-width="2.5"/>'
        + '<text class="sd-cmarklab" x="34" y="14" text-anchor="middle">0%</text>'
        + '<text x="34" y="206" class="sd-caxis" text-anchor="middle">today</text>'
        + '<text x="286" y="206" class="sd-caxis" text-anchor="middle">+5 °C</text>'
        + '<text x="30" y="' + (parseFloat(zeroY) + 3).toFixed(1) + '" class="sd-caxis" text-anchor="end">0%</text>'
      + '</svg>'
      + '<div class="sd-curvenote">the dot follows your dial · shaded = 95% confidence</div>';

    el.innerHTML =
      '<div class="sd-wrap">'
      + '<div class="sd-gaugecol">'
        + '<svg class="sd-svg" viewBox="0 0 380 236">'
          + '<defs><linearGradient id="sdG" x1="0" y1="0" x2="1" y2="0">'
            + '<stop offset="0" stop-color="#2fbf6b"/><stop offset=".5" stop-color="#f5a524"/><stop offset="1" stop-color="#ff5a4d"/></linearGradient></defs>'
          + '<path d="' + arc(180, 0) + '" fill="none" stroke="#e6ecf2" stroke-width="26" stroke-linecap="round"/>'
          + '<path class="sd-arc" d="' + arc(180, 0) + '" fill="none" stroke="url(#sdG)" stroke-width="26" stroke-linecap="round"/>'
          + '<g>' + ticks + '</g>'
          + '<line class="sd-needle" x1="' + CX + '" y1="' + CY + '" x2="' + CX + '" y2="' + (CY - R + 18) + '" stroke="#0D2137" stroke-width="5" stroke-linecap="round"/>'
          + '<circle cx="' + CX + '" cy="' + CY + '" r="13" fill="#fff" stroke="#0D2137" stroke-width="3"/>'
          + '<circle class="sd-dot" r="9" fill="#fff" stroke="#0D2137" stroke-width="2" opacity="0"/>'
        + '</svg>'
        + '<div class="sd-setrow">'
          + '<div class="sd-setval">+0.0 °C</div>'
          + '<div class="sd-setcap">warming above today</div>'
          + '<div class="sd-sethint"><span>◂</span> drag the dial to change <span>▸</span></div>'
        + '</div>'
      + '</div>'
      + '<div class="sd-readcol">'
        + '<div class="sd-pct">0%</div><div class="sd-cap">Colorado River water yield</div>'
        + '<div class="sd-mafrow"><span class="sd-maf">≈ 0.0</span><span class="sd-cap2">MAF less water — every year</span></div>'
        + '<div class="sd-badge">Normal</div>'
        + '<div class="sd-ci"></div>'
      + '</div>'
      + '<div class="sd-curvecol">' + curveSVG + '</div>'
      + '</div>';

    var q = function (s) { return el.querySelector(s); };
    var svg = q(".sd-svg"), arcEl = q(".sd-arc"), needle = q(".sd-needle"), dot = q(".sd-dot"),
        setv = q(".sd-setval"), pctEl = q(".sd-pct"), mafEl = q(".sd-maf"), badge = q(".sd-badge"), ci = q(".sd-ci"),
        cmark = q(".sd-cmark"), guide = q(".sd-guide"), cmarklab = q(".sd-cmarklab");

    function render(dt) {
      dt = clamp(dt, 0, 5); var deg = dtToDeg(dt), tp = polar(deg);
      needle.setAttribute("x2", tp[0].toFixed(1)); needle.setAttribute("y2", tp[1].toFixed(1));
      arcEl.setAttribute("d", arc(180, deg));
      dot.setAttribute("cx", tp[0].toFixed(1)); dot.setAttribute("cy", tp[1].toFixed(1)); dot.setAttribute("opacity", 1);
      var pr = proj(dt), st = statusOf(pr.pct);
      if (setv) { setv.textContent = "+" + dt.toFixed(1) + " °C"; setv.style.color = st[1]; }
      pctEl.textContent = Math.round(pr.pct) + "%"; pctEl.style.color = st[1];
      mafEl.textContent = "≈ " + pr.maf.toFixed(1); mafEl.style.color = st[1];
      badge.textContent = st[0]; badge.style.background = st[1];
      ci.innerHTML = "95% CI " + Math.round(pr.lo) + "% to " + Math.round(pr.hi) + "%  ·  fit R² = " + R2.toFixed(2);
      if (cmark) {
        var mx = cxF(dt), my = cyF(pr.pct);
        cmark.setAttribute("cx", mx.toFixed(1)); cmark.setAttribute("cy", my.toFixed(1)); cmark.setAttribute("fill", st[1]);
        guide.setAttribute("x1", mx.toFixed(1)); guide.setAttribute("x2", mx.toFixed(1));
        if (cmarklab) {
          cmarklab.setAttribute("x", mx.toFixed(1));
          cmarklab.setAttribute("y", Math.max(12, my - 11).toFixed(1));
          cmarklab.setAttribute("fill", st[1]);
          cmarklab.textContent = Math.round(pr.pct) + "%";
        }
      }
    }

    var cur = 0, target = 0, introDone = false;
    (function loop() { cur += (target - cur) * 0.18; if (Math.abs(target - cur) < 0.0008) cur = target; render(cur); requestAnimationFrame(loop); })();

    var t0 = null;
    (function intro(ts) {
      if (introDone) return;
      if (t0 == null) t0 = ts; var e = (ts - t0) / 1000;
      if (e < 2.4) target = 5 * eInOut(e / 2.4);
      else if (e < 4.0) target = lerp(5, 2, eInOut((e - 2.6) / 1.4));
      else { target = 2; introDone = true; return; }
      requestAnimationFrame(intro);
    })(performance.now());

    function ptTo(ev) {
      var r = svg.getBoundingClientRect(), sc = r.width / 380;
      var x = (ev.clientX - r.left) / sc - CX, y = CY - (ev.clientY - r.top) / sc;
      var ang = Math.atan2(y, x) * 180 / Math.PI; if (ang < 0) ang += 360;
      ang = clamp(ang, 0, 180);
      return clamp((180 - ang) / 180 * 5, 0, 5);
    }
    var dragging = false;
    function move(ev) { if (dragging) { target = ptTo(ev); ev.preventDefault(); } }
    function up() { dragging = false; window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); }
    svg.addEventListener("pointerdown", function (ev) {
      dragging = true; introDone = true; target = ptTo(ev); ev.preventDefault();
      window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
    });
  }

  function scan() { var els = document.querySelectorAll(".scen-dial"); for (var i = 0; i < els.length; i++) build(els[i]); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { setTimeout(scan, 300); });
  else setTimeout(scan, 300);
  setInterval(scan, 1500); // re-init after any Dash re-render of the Overview
})();
