/* CRIA — gentle first-visit onboarding.
   Draws the eye to the existing "Take a tour" button (next to the Overview
   title) with a soft pulse + a tiny dismissible hint.

   Show rules (by request):
     • Shows on EVERY page load / refresh by default.
     • "Skip"  → hides for THIS page view only; a refresh shows it again.
     • "Don't show again" (or taking the tour) → hides for the rest of this
       browser tab session (survives refresh); reopening the tab shows it again.
   Nothing is remembered permanently (no localStorage).
   Self-contained; touches nothing in the Dash React tree. */
(function () {
  "use strict";
  var SESSION_KEY = "cria_welcome_dismissed"; // per-tab session dismiss
  var dismissedNow = false;                    // in-memory: "skip" for this load only

  function sessionDismissed() {
    try { return sessionStorage.getItem(SESSION_KEY) === "1"; } catch (e) { return false; }
  }
  function markSessionDismiss() { try { sessionStorage.setItem(SESSION_KEY, "1"); } catch (e) {} }
  function forced() { return /[?&]welcome=1(&|$)/.test(location.search || ""); }

  function onHome() {
    var p = (location.pathname || "/").replace(/\/+$/, "");
    return p === "" || p === "/home";
  }

  function injectStyles() {
    if (document.getElementById("cria-welcome-style")) return;
    var css = ''
      + '@keyframes criaTourPulse{0%,100%{transform:scale(1);}'
      + '50%{transform:scale(1.11);}}'
      + '@keyframes criaTourGlow{0%,100%{box-shadow:0 6px 16px rgba(140,29,64,.30);}'
      + '50%{box-shadow:0 0 0 6px rgba(255,198,39,.30),0 8px 22px rgba(140,29,64,.45);}}'
      + '.cria-tour-attn{animation:criaTourPulse 1.15s ease-in-out infinite,'
      + 'criaTourGlow 1.15s ease-in-out infinite!important;}'
      + '.cria-hint{position:fixed;z-index:99999;max-width:250px;background:#fff;'
      + 'border:1px solid #eadfe4;border-top:3px solid #FFC627;border-radius:12px;'
      + 'box-shadow:0 12px 30px rgba(13,33,55,.22);padding:11px 13px 10px;'
      + 'font-size:12.5px;color:#37474f;opacity:0;transform:translateY(-4px);'
      + 'transition:opacity .25s ease,transform .25s ease;}'
      + '.cria-hint.in{opacity:1;transform:none;}'
      + '.cria-hint-arrow{position:absolute;top:-7px;width:12px;height:12px;'
      + 'background:#fff;border-left:1px solid #eadfe4;border-top:1px solid #eadfe4;'
      + 'transform:rotate(45deg);}'
      + '.cria-hint b{color:#8C1D40;}'
      + '.cria-hint-row{display:flex;gap:12px;margin-top:8px;align-items:center;}'
      + '.cria-hint-link{background:none;border:none;padding:0;cursor:pointer;'
      + 'font-size:11.5px;font-weight:700;color:#64748b;text-decoration:underline;font-family:inherit;}'
      + '.cria-hint-go{background:#8C1D40;color:#fff;border:none;border-radius:8px;'
      + 'padding:6px 11px;font-size:11.5px;font-weight:800;cursor:pointer;font-family:inherit;}'
      + '@media (prefers-reduced-motion:reduce){.cria-tour-attn{animation:criaTourGlow 1.6s ease-in-out infinite!important;}}';
    var s = document.createElement("style");
    s.id = "cria-welcome-style";
    s.textContent = css;
    document.head.appendChild(s);
  }

  var hintEl = null, btnEl = null, repositionBound = null, pulseTimer = null;

  // session=true → hide for the rest of this tab session; session=false → just this page view
  function cleanup(session) {
    if (btnEl) btnEl.classList.remove("cria-tour-attn");
    if (pulseTimer) { clearTimeout(pulseTimer); pulseTimer = null; }
    if (hintEl) {
      hintEl.classList.remove("in");
      var h = hintEl; setTimeout(function () { if (h && h.parentNode) h.parentNode.removeChild(h); }, 260);
      hintEl = null;
    }
    if (repositionBound) {
      window.removeEventListener("scroll", repositionBound, true);
      window.removeEventListener("resize", repositionBound);
      repositionBound = null;
    }
    if (session) markSessionDismiss(); else dismissedNow = true;
  }

  function reposition() {
    if (!hintEl || !btnEl) return;
    var r = btnEl.getBoundingClientRect();
    if (r.bottom < 0 || r.top > window.innerHeight) { hintEl.style.display = "none"; return; }
    hintEl.style.display = "block";
    var w = hintEl.offsetWidth || 250;
    // Anchor the hint directly below the tour button (arrow points up at it).
    var left = Math.min(Math.max(8, r.left), window.innerWidth - w - 10);
    hintEl.style.top = (r.bottom + 10) + "px";
    hintEl.style.left = left + "px";
    var arrow = hintEl.querySelector(".cria-hint-arrow");
    if (arrow) arrow.style.left = Math.max(10, Math.min(r.left + r.width / 2 - left - 6, w - 22)) + "px";
  }

  function show(btn) {
    btnEl = btn;
    injectStyles();
    btn.classList.add("cria-tour-attn");
    pulseTimer = setTimeout(function () { if (btnEl) btnEl.classList.remove("cria-tour-attn"); }, 14000);

    hintEl = document.createElement("div");
    hintEl.className = "cria-hint";
    hintEl.innerHTML =
      '<div class="cria-hint-arrow"></div>' +
      '<div>👋 <b>New here?</b> A quick guided tour shows you around.</div>' +
      '<div class="cria-hint-row">' +
        '<button class="cria-hint-go" id="cria-hint-go">Take the tour</button>' +
        '<button class="cria-hint-link" id="cria-hint-skip">Skip</button>' +
        '<button class="cria-hint-link" id="cria-hint-never">Don\'t show again</button>' +
      '</div>';
    document.body.appendChild(hintEl);
    reposition();
    requestAnimationFrame(function () { requestAnimationFrame(function () { hintEl.classList.add("in"); }); });

    repositionBound = function () { reposition(); };
    window.addEventListener("scroll", repositionBound, true);
    window.addEventListener("resize", repositionBound);

    // Take the tour → engaged, hide for the rest of this session
    hintEl.querySelector("#cria-hint-go").onclick = function () { cleanup(false); btn.click(); };
    // Skip → hide for this page view only (a refresh brings it back)
    hintEl.querySelector("#cria-hint-skip").onclick = function () { cleanup(false); };
    // Don't show again → hide for the rest of this browser session
    hintEl.querySelector("#cria-hint-never").onclick = function () { cleanup(true); };
    // clicking the real tour button = engaged for this session
    btn.addEventListener("click", function once() { cleanup(false); btn.removeEventListener("click", once); });
  }

  function maybeShow() {
    var f = forced();
    if (!f && (sessionDismissed() || dismissedNow || !onHome())) return;
    var start = Date.now(), obs = null, timer = null, done = false;
    function tryShow() {
      if (done || hintEl) return true;
      if (!f && (sessionDismissed() || dismissedNow || !onHome())) { stop(); return true; }
      var btn = document.getElementById("tour-btn");
      if (btn) { done = true; stop(); show(btn); return true; }
      if (Date.now() - start > 30000) { stop(); return true; }  // give up after 30s
      return false;
    }
    function stop() { if (obs) { obs.disconnect(); obs = null; } if (timer) { clearInterval(timer); timer = null; } }
    if (tryShow()) return;
    // The overview (with #tour-btn) is rendered by a Dash callback that can be slow,
    // so watch the DOM AND poll — the hint appears whenever the button shows up.
    if (window.MutationObserver) { obs = new MutationObserver(tryShow); obs.observe(document.body, { childList: true, subtree: true }); }
    timer = setInterval(tryShow, 400);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { setTimeout(maybeShow, 700); });
  } else {
    setTimeout(maybeShow, 700);
  }
})();
