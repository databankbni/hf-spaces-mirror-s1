/**
 * lens-flare.js
 * KOMBAZ.ME — Sun lens flare effect
 * Canvas-based, no Three.js dependency
 * Renders over the WebGL canvas
 */

window.KombazLensFlare = (function () {

  let overlay, ctx, sunScreenPos = null, enabled = true;

  function init(canvasEl) {
    overlay = document.createElement('canvas');
    overlay.style.cssText = [
      'position:fixed', 'inset:0', 'z-index:4',
      'pointer-events:none', 'opacity:0.55'
    ].join(';');
    document.body.appendChild(overlay);
    resize();
    window.addEventListener('resize', resize);
    requestAnimationFrame(loop);
  }

  function resize() {
    overlay.width  = window.innerWidth;
    overlay.height = window.innerHeight;
    ctx = overlay.getContext('2d');
  }

  // Call this from your animate() loop with projected sun position
  function setSunPos(x, y) {
    sunScreenPos = { x, y };
  }

  function setEnabled(val) { enabled = val; }

  function drawFlare(cx, cy) {
    if (!ctx) return;
    ctx.clearRect(0, 0, overlay.width, overlay.height);
    if (!enabled || !sunScreenPos) return;

    // Main glow
    const g1 = ctx.createRadialGradient(cx, cy, 0, cx, cy, 80);
    g1.addColorStop(0,   'rgba(255,240,180,0.35)');
    g1.addColorStop(0.4, 'rgba(255,200,80,0.12)');
    g1.addColorStop(1,   'rgba(255,150,30,0)');
    ctx.fillStyle = g1;
    ctx.beginPath(); ctx.arc(cx, cy, 80, 0, Math.PI * 2); ctx.fill();

    // Streak toward centre
    const dx = overlay.width  / 2 - cx;
    const dy = overlay.height / 2 - cy;
    const steps = [0.2, 0.4, 0.6, 0.8];
    steps.forEach((t, i) => {
      const fx = cx + dx * t;
      const fy = cy + dy * t;
      const r  = 18 - i * 3;
      const g2 = ctx.createRadialGradient(fx, fy, 0, fx, fy, r);
      g2.addColorStop(0,   `rgba(255,220,120,${0.18 - i * 0.03})`);
      g2.addColorStop(1,   'rgba(255,180,60,0)');
      ctx.fillStyle = g2;
      ctx.beginPath(); ctx.arc(fx, fy, r, 0, Math.PI * 2); ctx.fill();
    });
  }

  function loop() {
    if (sunScreenPos) drawFlare(sunScreenPos.x, sunScreenPos.y);
    requestAnimationFrame(loop);
  }

  return { init, setSunPos, setEnabled };
})();
