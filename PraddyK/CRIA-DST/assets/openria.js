/* CRIA — auto-open the RIA assistant when the app is reached with ?ria=1
   (used by the Blueprint's "Ask RIA" card, which links to the live tool + this flag,
   so a click there opens the app AND pops the RIA chat). Self-contained; harmless
   when the flag is absent. */
(function () {
  "use strict";
  function wants() {
    return /[?&]ria=1(&|$)/.test(location.search || "") || (location.hash || "") === "#ask-ria";
  }
  if (!wants()) return;

  var tries = 0, done = false;
  var timer = setInterval(function () {
    if (done) { clearInterval(timer); return; }
    tries++;
    var modal = document.getElementById("ria-modal");
    if (modal && (modal.className || "").indexOf("open") !== -1) {   // already open
      done = true; clearInterval(timer); return;
    }
    var fab = document.getElementById("ria-fab-sb") || document.getElementById("ria-fab");
    if (fab && modal) {
      fab.click();               // triggers the Dash clientside callback → ria-modal opens
      done = true; clearInterval(timer); return;
    }
    if (tries > 60) { clearInterval(timer); }   // give up after ~30s (slow render)
  }, 500);
})();
