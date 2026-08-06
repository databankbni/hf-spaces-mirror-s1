/* CRIA — count-up animation for the cold-open headline number. Self-contained. */
(function () {
  "use strict";
  function animate(el) {
    var to = parseFloat(el.getAttribute("data-to"));
    if (isNaN(to)) return;
    var dur = 1100, t0 = null;
    function step(ts) {
      if (!t0) t0 = ts;
      var p = Math.min(1, (ts - t0) / dur);
      var e = 1 - Math.pow(1 - p, 3); // easeOutCubic
      el.textContent = Math.round(to * e).toString();
      if (p < 1) requestAnimationFrame(step);
      else el.textContent = Math.round(to).toString();
    }
    requestAnimationFrame(step);
  }
  function run() {
    var els = document.querySelectorAll(".cu-num");
    for (var i = 0; i < els.length; i++) {
      if (els[i].dataset.cuDone) continue;
      els[i].dataset.cuDone = "1";
      animate(els[i]);
    }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { setTimeout(run, 450); });
  } else {
    setTimeout(run, 450);
  }
  setInterval(run, 1500); // catch Dash re-render of the Overview
})();
