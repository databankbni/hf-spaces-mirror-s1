/* Ashiya Limousine — privacy-light analytics beacon (no deps, silent on failure) */
(function () {
  'use strict';
  if (window.__ALSTrackInit) return;
  window.__ALSTrackInit = true;

  function post(body) {
    try {
      fetch('/api/analytics/track', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        credentials: 'include',
        keepalive: true,
        body: JSON.stringify(body)
      }).catch(function () {});
    } catch (e) { /* never throw */ }
  }

  // 1) Initial visit beacon
  post({ kind: 'visit', path: location.pathname + location.hash });

  // 2) Public logger for other modules (book_start / book_submit / pay_click …)
  window.ALSTrack = function (kind, ref) {
    post({ kind: kind, ref: ref || '', path: location.pathname });
  };

  // 3) Best-effort hooks — all optional, wrapped, never throw
  try {
    var submitBtn = document.getElementById('submitBk');
    if (submitBtn) {
      submitBtn.addEventListener('click', function () {
        window.ALSTrack('book_submit');
      }, true);
    }
  } catch (e) {}

  try {
    var booking = document.getElementById('booking');
    if (booking && 'IntersectionObserver' in window) {
      var io = new IntersectionObserver(function (entries) {
        for (var i = 0; i < entries.length; i++) {
          if (entries[i].isIntersecting) {
            window.ALSTrack('book_start');
            io.disconnect();
            break;
          }
        }
      });
      io.observe(booking);
    }
  } catch (e) {}
})();
