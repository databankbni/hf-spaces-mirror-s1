/**
 * voyager-worker.js
 * KOMBAZ.ME — Voyager Live Telemetry Web Worker
 * Runs in background thread, no UI blocking
 */

const V1_REF_AU  = 172.59;
const V1_KM_S    = 17.043;
const V2_REF_AU  = 143.10;
const V2_KM_S    = 15.40;
const AU_KM      = 149597870.7;
const LIGHT_KM_S = 299792.458;
const REF_MS     = Date.UTC(2026, 3, 19);
const MILESTONE  = Date.UTC(2026, 10, 15);

function calc() {
  const now = Date.now();
  const sec = (now - REF_MS) / 1000;

  const v1km = V1_REF_AU * AU_KM + V1_KM_S * sec;
  const v1au = v1km / AU_KM;
  const v1del = v1km / LIGHT_KM_S;

  const v2km = V2_REF_AU * AU_KM + V2_KM_S * sec;
  const v2au = v2km / AU_KM;
  const v2del = v2km / LIGHT_KM_S;

  const fmtD = s => {
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    return `${h}h ${String(m).padStart(2,'0')}m`;
  };
  const fmtKm = km => km >= 1e9
    ? (km/1e9).toFixed(2) + 'B km'
    : (km/1e6).toFixed(0) + 'M km';

  const daysLeft = Math.max(0, Math.round((MILESTONE - now) / 86400000));

  return {
    v1: { au: v1au.toFixed(2), km: fmtKm(v1km), delay: fmtD(v1del), speed: '17.043 km/s' },
    v2: { au: v2au.toFixed(2), delay: fmtD(v2del), speed: '15.400 km/s' },
    milestone: { passed: now > MILESTONE, daysLeft },
    ts: now
  };
}

// Send immediately, then every 30s
self.postMessage(calc());
setInterval(() => self.postMessage(calc()), 30000);
