/* Testimonials carousels — shows 3 review cards at a time and auto-rotates.
   Handles ANY number of carousels on the page (Overview + Reviews page), each with its own
   .testi-track and a following .testi-dots. Robust to 0/1/2/many cards and to Dash re-rendering
   the list after a review is posted (a MutationObserver resets that carousel to page 1). */
(function () {
  function renderTrack(track) {
    if (!track) return;
    var carousel = track.closest(".testi-carousel") || track.parentNode;
    var dots = carousel ? carousel.querySelector(".testi-dots") : null;
    var cards = Array.prototype.slice.call(track.querySelectorAll(".testi-card"));
    if (cards.length === 0) { if (dots) dots.innerHTML = ""; return; }
    var nPages = Math.ceil(cards.length / 3);
    var idx = track._idx || 0;
    if (idx >= nPages) { idx = 0; track._idx = 0; }
    cards.forEach(function (c, i) {
      c.style.display = (Math.floor(i / 3) === idx) ? "" : "none";
    });
    // Slide the new group in from the right (only when the page actually changes,
    // so we don't re-trigger the animation on every housekeeping re-render).
    if (track._animIdx !== idx) {
      track._animIdx = idx;
      var pos = 0;
      cards.forEach(function (c) {
        if (c.style.display !== "none") {
          c.classList.remove("testi-in");
          void c.offsetWidth;               // force reflow → restart animation
          c.style.animationDelay = (pos * 0.07) + "s";
          c.classList.add("testi-in");
          pos++;
        }
      });
    }
    if (dots) {
      dots.innerHTML = "";
      if (nPages > 1) {
        for (var p = 0; p < nPages; p++) {
          var d = document.createElement("span");
          d.className = "testi-dot" + (p === idx ? " on" : "");
          dots.appendChild(d);
        }
      }
    }
  }

  function tick() {
    document.querySelectorAll(".testi-track").forEach(function (track) {
      var n = track.querySelectorAll(".testi-card").length;
      var nPages = Math.ceil(n / 3);
      if (nPages > 1) { track._idx = ((track._idx || 0) + 1) % nPages; renderTrack(track); }
    });
  }

  function init() {
    document.querySelectorAll(".testi-track").forEach(function (track) {
      renderTrack(track);
      if (!track._obs) {
        track._obs = new MutationObserver(function () { track._idx = 0; renderTrack(track); });
        track._obs.observe(track, { childList: true });
      }
    });
    if (!window._testiTimer) window._testiTimer = setInterval(tick, 5000);
  }

  setInterval(init, 2500);   // re-init when Dash re-mounts a page
  if (document.readyState !== "loading") init();
  else document.addEventListener("DOMContentLoaded", init);
})();
