/* CRIA — the "Ask RIA" showcase card opens the RIA assistant, and the 3D value
   tiles count up when they first scroll into view. Self-contained. */
(function () {
  "use strict";

  function wire() {
    var c = document.getElementById("tabcard-ria");
    if (!c || c.dataset.wired) return;
    c.dataset.wired = "1";
    c.addEventListener("click", function () {
      // If the Quick View board (z-index 5000) is open, close it first — otherwise the
      // RIA panel (z-index 1300) opens hidden behind it and nothing appears to happen.
      var qv = document.getElementById("qv-overlay");
      if (qv && qv.classList.contains("open")) {
        var qc = qv.querySelector("#qv-close, .qv-close");
        if (qc) qc.click(); else qv.classList.remove("open");
      }
      var f = document.getElementById("ria-fab-sb") || document.getElementById("ria-fab");
      if (f) setTimeout(function () { f.click(); }, 40);
    });
  }

  // ── count-up for the 3D value tiles ──
  function fmt(v, dec) {
    var s = (dec > 0) ? v.toFixed(dec) : String(Math.round(v));
    return s;
  }
  function run(el) {
    var to = parseFloat(el.getAttribute("data-to"));
    var dec = parseInt(el.getAttribute("data-dec") || "0", 10);
    if (isNaN(to)) return;
    var dur = 1100, t0 = null;
    function step(ts) {
      if (t0 === null) t0 = ts;
      var p = Math.min(1, (ts - t0) / dur);
      var e = 1 - Math.pow(1 - p, 3);            // easeOutCubic
      el.textContent = fmt(to * e, dec);
      if (p < 1) requestAnimationFrame(step);
      else el.textContent = fmt(to, dec);
    }
    requestAnimationFrame(step);
  }
  function countup() {
    var nums = document.querySelectorAll(".tvt-num");
    if (!nums.length) return;
    if (typeof IntersectionObserver === "undefined") {
      nums.forEach(function (n) { if (!n.dataset.ran) { n.dataset.ran = "1"; run(n); } });
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting && !en.target.dataset.ran) {
          en.target.dataset.ran = "1"; run(en.target); io.unobserve(en.target);
        }
      });
    }, { threshold: 0.4 });
    nums.forEach(function (n) { if (!n.dataset.obs) { n.dataset.obs = "1"; io.observe(n); } });
  }

  // ── cycle 3+ analyses in a single chart panel, one at a time ──
  function cycleMulti() {
    document.querySelectorAll(".tvt-chart.multiN").forEach(function (panel) {
      if (panel.dataset.cyc) return;
      var imgs = panel.querySelectorAll(".tabcard-img");
      if (imgs.length < 2) return;
      panel.dataset.cyc = "1";
      var i = 0; imgs[0].classList.add("on");
      setInterval(function () {
        imgs[i].classList.remove("on");
        i = (i + 1) % imgs.length;
        imgs[i].classList.add("on");
      }, 4800);
    });
  }

  function tick() { wire(); countup(); cycleMulti(); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { setTimeout(tick, 400); });
  else setTimeout(tick, 400);
  setInterval(tick, 1500);
})();
