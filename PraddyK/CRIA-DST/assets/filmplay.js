/* CRIA — story film: a ".film-open" button pops the player into a full-screen accessible dialog.
   Native controls (scrub / speed / download), plays on open, pauses & resets on close.
   Pure client-side (event delegation, survives Dash re-renders). */
(function () {
  "use strict";
  var lastFocus = null;
  function ov() { return document.getElementById("film-overlay"); }
  function vid() { var o = ov(); return o ? o.querySelector("video") : null; }
  function focusables(root) {
    return Array.prototype.slice.call(root.querySelectorAll(
      'a[href],button:not([disabled]),video,[tabindex]:not([tabindex="-1"])'
    )).filter(function (el) { return el.offsetWidth || el.offsetHeight || el.getClientRects().length; });
  }
  function open() {
    var o = ov(); if (!o) return;
    lastFocus = document.activeElement;
    o.classList.add("open"); document.body.classList.add("qv-lock");
    o.setAttribute("role", "dialog"); o.setAttribute("aria-modal", "true");
    o.setAttribute("aria-label", "The Colorado Basin — story film");
    var v = vid(); if (v) { try { v.currentTime = 0; var p = v.play(); if (p && p.catch) p.catch(function(){}); } catch (e) {} }
    var closeBtn = o.querySelector(".film-close");
    setTimeout(function () { if (closeBtn) closeBtn.focus(); }, 30);
  }
  function close() {
    var o = ov(); if (!o) return;
    o.classList.remove("open"); document.body.classList.remove("qv-lock");
    o.setAttribute("aria-modal", "false");
    var v = vid(); if (v) { try { v.pause(); } catch (e) {} }
    if (lastFocus && lastFocus.focus) { try { lastFocus.focus(); } catch (e) {} }
  }
  function isOpen() { var o = ov(); return o && o.classList.contains("open"); }
  document.addEventListener("click", function (e) {
    if (e.target.closest(".film-open")) { e.preventDefault(); open(); return; }
    if (e.target.closest(".film-close")) { e.preventDefault(); close(); return; }
    if (e.target.id === "film-overlay") { close(); }   // click backdrop
  }, true);
  document.addEventListener("keydown", function (e) {
    if (!isOpen()) return;
    if (e.key === "Escape") { close(); return; }
    if (e.key === "Tab") {
      var o = ov(), f = focusables(o);
      if (!f.length) { e.preventDefault(); return; }
      var first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      else if (!o.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
    }
  });
})();
