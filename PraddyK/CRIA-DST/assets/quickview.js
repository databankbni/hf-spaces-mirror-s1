/* CRIA — Quick View: any ".qv-open" button pops the whole Vital Signs board into a
   full-screen accessible dialog. Pure client-side (event delegation, survives Dash re-renders).
   Also auto-opens when the page is reached with #quickview (blueprint deep-link). */
(function () {
  "use strict";
  var lastFocus = null;
  function ov() { return document.getElementById("qv-overlay"); }
  function focusables(root) {
    return Array.prototype.slice.call(root.querySelectorAll(
      'a[href],button:not([disabled]),input,select,textarea,[tabindex]:not([tabindex="-1"])'
    )).filter(function (el) { return el.offsetWidth || el.offsetHeight || el.getClientRects().length; });
  }
  function open() {
    var o = ov(); if (!o) return;
    lastFocus = document.activeElement;
    o.classList.add("open"); document.body.classList.add("qv-lock"); o.scrollTop = 0;
    o.setAttribute("role", "dialog"); o.setAttribute("aria-modal", "true");
    o.setAttribute("aria-label", "Colorado River Basin — Vital Signs, every analysis");
    var closeBtn = o.querySelector("#qv-close, .qv-close");
    setTimeout(function () { if (closeBtn) closeBtn.focus(); }, 30);
  }
  function close() {
    var o = ov(); if (!o) return;
    o.classList.remove("open"); document.body.classList.remove("qv-lock");
    o.setAttribute("aria-modal", "false");
    if (lastFocus && lastFocus.focus) { try { lastFocus.focus(); } catch (e) {} }
  }
  function isOpen() { var o = ov(); return o && o.classList.contains("open"); }
  document.addEventListener("click", function (e) {
    if (e.target.closest(".qv-open")) { e.preventDefault(); open(); return; }
    if (e.target.closest("#qv-close, .qv-close")) { e.preventDefault(); close(); return; }
    if (e.target.id === "qv-overlay") { close(); }  // click backdrop
  }, true);
  document.addEventListener("keydown", function (e) {
    if (!isOpen()) return;
    if (e.key === "Escape") { close(); return; }
    if (e.key === "Tab") {                          // trap focus inside the dialog
      var o = ov(), f = focusables(o);
      if (!f.length) { e.preventDefault(); return; }
      var first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      else if (!o.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
    }
  });
  // deep-link: #quickview opens the board once the overlay has rendered
  function maybeHashOpen() {
    if ((location.hash || "").toLowerCase() === "#quickview" && ov()) { open(); return true; }
    return false;
  }
  window.addEventListener("hashchange", maybeHashOpen);
  var tries = 0, t = setInterval(function () {
    tries++;
    if (maybeHashOpen() || tries > 40) clearInterval(t);
  }, 200);
})();
