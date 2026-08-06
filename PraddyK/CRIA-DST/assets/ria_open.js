/* Watches the RIA chat modal:
   - the instant the user CLOSES it → stop RIA speaking, then reload the iframe so the
     next open starts a FRESH chat (no old conversation).
   - the instant the user MINIMISES it → stop RIA speaking (keep the conversation). */
(function () {
  if (typeof window === "undefined") return;

  function frame() { return document.querySelector(".ria-frame"); }
  function stop() {
    var f = frame();
    if (f && f.contentWindow) {
      try { f.contentWindow.postMessage("ria-stop", "*"); } catch (e) {}
    }
  }
  function wire() {
    var modal = document.getElementById("ria-modal");
    if (!modal) { return setTimeout(wire, 500); }
    var wasOpen = /\bopen\b/.test(modal.className || "");
    var wasMini = /\bmini\b/.test(modal.className || "");
    new MutationObserver(function () {
      var cls = modal.className || "";
      var open = /\bopen\b/.test(cls);
      var mini = /\bmini\b/.test(cls);
      if (wasOpen && !open) {                 // closed
        stop();
        var f = frame();
        if (f) { setTimeout(function () { try { f.src = f.src; } catch (e) {} }, 250); }
      } else if (open && mini && !wasMini) {   // minimised
        stop();
      }
      wasOpen = open;
      wasMini = mini;
    }).observe(modal, { attributes: true, attributeFilter: ["class"] });
  }
  wire();
})();
