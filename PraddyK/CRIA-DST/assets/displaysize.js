/* Display-size A/A/A — robust handler that works on mobile too.
   The Dash clientside callback can be flaky for taps inside the mobile drawer,
   so we also attach direct DOM click/touch listeners, persist the choice in
   localStorage, and re-apply it on load. Idempotent with the Dash callback. */
(function () {
  if (typeof window === "undefined") return;
  var KEY = "cria-display-size";

  function apply(lv) {
    var b = document.body; if (!b) return;
    b.classList.remove("zoom-lv2", "zoom-lv3");
    if (lv === 2) b.classList.add("zoom-lv2");
    if (lv === 3) b.classList.add("zoom-lv3");
    ["zoom-1", "zoom-2", "zoom-3"].forEach(function (id, i) {
      var el = document.getElementById(id);
      if (el) el.classList.toggle("active", (i + 1) === lv);
    });
    try { localStorage.setItem(KEY, String(lv)); } catch (e) {}
  }

  function wire() {
    [["zoom-1", 1], ["zoom-2", 2], ["zoom-3", 3]].forEach(function (p) {
      var el = document.getElementById(p[0]);
      if (el && !el._dsWired) {
        el._dsWired = true;
        var h = function (ev) { apply(p[1]); };
        el.addEventListener("click", h);
        el.addEventListener("touchend", function (ev) { ev.preventDefault(); h(); }, { passive: false });
      }
    });
  }

  function init() {
    wire();
    var lv = 1;
    try { lv = parseInt(localStorage.getItem(KEY) || "1", 10) || 1; } catch (e) {}
    if (lv !== 1) apply(lv);
  }

  if (document.readyState !== "loading") init();
  else document.addEventListener("DOMContentLoaded", init);
  window.addEventListener("load", init);
  setInterval(wire, 2000);   // re-attach if Dash re-renders the sidebar
})();
