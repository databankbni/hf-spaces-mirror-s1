// Step 4 — Live camera + capture coach.
//
// Drives the existing `static/preview/*` modules (camera lifecycle,
// MediaPipe Hands, DeviceOrientation, torch) inside the step
// lifecycle: mount() opens the camera and starts the gate loop,
// unmount() tears everything down. On shutter, captures a frame and
// hands the blob to the confirm step (step 5) — the actual
// /api/measure POST happens there.
//
// Most of the gate-loop logic mirrors the desktop implementation in
// `web_demo/static/app.js` (anti-jitter counters, telemetry shape,
// MediaPipe-not-loaded fallback). The desktop and mobile copies will
// converge into a shared module in a later phase once the mobile flow
// is validated end-to-end.

import { session } from "../session.js";

const LEVEL_NO_DATA_TIMEOUT_MS = 2000;

let detectionTimer = null;
let consecutiveDistanceGreen = 0;
let consecutiveLevelGreen = 0;
let mediaPipeReady = false;
let orientationStatus = "unsupported";
let latestOrientation = null;
let levelStartedAtMs = null;
let levelMarkedSkipped = false;
let gateTelemetry = createTelemetry();
let videoEl = null;
let distanceChip = null;
let levelChip = null;
let levelBubble = null;
let levelDot = null;
let shutterBtn = null;
let flashBtn = null;
let statusEl = null;
let viewportListener = null;
// Bumped on every mount; the async startup IIFE compares its captured
// generation to this after each await to detect that unmount has fired
// while it was suspended. Without this, a quick Back tap can let the
// IIFE start a setInterval *after* unmount has run, leaking it forever.
let mountGeneration = 0;

function createTelemetry() {
  return {
    started_at_ms: null,
    distance_first_green_ms: null,
    distance_green_frames: 0,
    distance_red_frames: 0,
    distance_amber_frames: 0,
    distance_no_hand_frames: 0,
    level_first_green_ms: null,
    level_green_frames: 0,
    level_red_frames: 0,
    level_amber_frames: 0,
    level_no_data_frames: 0,
    orientation_status: "unsupported",
    threshold_used: null,
  };
}

function setChip(chipEl, state, label) {
  if (!chipEl) return;
  chipEl.className = `status-chip ${state}`;
  const labelEl = chipEl.querySelector(".chip-label");
  if (labelEl) labelEl.textContent = label;
}

function setStatus(text, isError = false) {
  if (!statusEl) return;
  statusEl.textContent = text || "";
  statusEl.classList.toggle("error", !!isError);
}

function evaluateDistance(T) {
  // Mobile collapses the desktop's 5-band gauge (red / amber /
  // green / amber / red) to a strict 3-state read: too far / OK /
  // too close. The amber soft-zone is gone — clearer single-action
  // feedback at the cost of fewer intermediate hints.
  const minRatio = T.HAND_SPAN_RATIO_MIN ?? 0.3;
  const maxRatio = T.HAND_SPAN_RATIO_MAX ?? 0.45;

  let result = null;
  try {
    result = window.HandsDetector ? window.HandsDetector.detect(videoEl) : null;
  } catch (err) {
    return { state: "skipped", label: "Detection error", isGreen: false };
  }
  const ratio = result ? result.ratio : null;
  if (ratio === null) {
    return { state: "red", label: "Hand not detected", isGreen: false };
  }
  if (ratio < minRatio) {
    return { state: "red", label: "Move closer", isGreen: false };
  }
  if (ratio > maxRatio) {
    return { state: "red", label: "Pull back", isGreen: false };
  }
  return { state: "green", label: "Distance OK", isGreen: true };
}

function evaluateLevel(T) {
  if (orientationStatus !== "granted") {
    return { included: false, state: "skipped", label: "" };
  }
  if (!latestOrientation) {
    if (levelStartedAtMs !== null && Date.now() - levelStartedAtMs > LEVEL_NO_DATA_TIMEOUT_MS) {
      return { included: false, state: "skipped", label: "Level: no sensor" };
    }
    return { included: true, state: "pending", label: "Level: detecting…", isGreen: false };
  }
  // Same red/green collapse as the distance gate — drop the desktop's
  // amber "Hold steady" middle band. Tighter ±5° green threshold (set
  // in thresholds.js) gets the user closer to a clean top-down shot.
  const beta = Math.abs(latestOrientation.beta);
  const gamma = Math.abs(latestOrientation.gamma);
  const bmax = T.LEVEL_BETA_MAX_DEG ?? 5;
  const gmax = T.LEVEL_GAMMA_MAX_DEG ?? 5;
  if (beta < bmax && gamma < gmax) {
    return { included: true, state: "green", label: "Level OK", isGreen: true };
  }
  return { included: true, state: "red", label: "Camera not level", isGreen: false };
}

// Bubble-level visualization. Dot moves toward the *high* side of the
// device (matches a real spirit level): tilting the right edge down
// (γ > 0) leaves the left edge high, so the dot drifts left. Saturates
// at ±15° so wild tilts don't fly off the rim. Color states are derived
// from raw degrees independent of the gate's anti-jitter counter — the
// bubble is purely visual feedback; the gate still owns shutter unlock.
function updateLevelBubble(lvl, T) {
  if (!levelBubble || !levelDot) return;
  if (!lvl.included) {
    levelBubble.hidden = true;
    return;
  }
  levelBubble.hidden = false;
  // Belt-and-braces guard: orientation.js already filters non-finite
  // readings, but treat anything we can't read as pending so a bad
  // sample never propagates into the CSS transform as NaN.
  if (
    lvl.state === "pending" ||
    !latestOrientation ||
    !Number.isFinite(latestOrientation.beta) ||
    !Number.isFinite(latestOrientation.gamma)
  ) {
    levelBubble.dataset.state = "pending";
    levelDot.style.transform = "translate(-50%, -50%)";
    return;
  }
  // Two-state behavior:
  //   green → indicator snaps to the center cross, so the user sees a
  //           single merged cross flash green when they're in tolerance.
  //   red   → indicator floats out toward the high side of the device,
  //           clamped to a max radius so wild tilts don't fly off-canvas.
  if (lvl.isGreen) {
    levelDot.style.transform = "translate(-50%, -50%)";
    levelBubble.dataset.state = "green";
    return;
  }
  const SATURATION_DEG = 15;
  const MAX_RADIUS_PX = 52;
  const clamp = (v) => Math.max(-1, Math.min(1, v / SATURATION_DEG));
  const dx = -clamp(latestOrientation.gamma) * MAX_RADIUS_PX;
  const dy = -clamp(latestOrientation.beta) * MAX_RADIUS_PX;
  levelDot.style.transform = `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px))`;
  levelBubble.dataset.state = "red";
}

function runDetectionTick() {
  if (!videoEl || videoEl.paused || videoEl.readyState < 2) return;
  const T = window.PreviewThresholds || {};
  const requiredFrames = T.GATE_CONSECUTIVE_FRAMES ?? 3;

  const dist = evaluateDistance(T);
  setChip(distanceChip, dist.state, dist.label);
  if (dist.isGreen) {
    consecutiveDistanceGreen++;
    gateTelemetry.distance_green_frames++;
    if (
      consecutiveDistanceGreen === requiredFrames &&
      gateTelemetry.distance_first_green_ms === null &&
      gateTelemetry.started_at_ms !== null
    ) {
      gateTelemetry.distance_first_green_ms = Date.now() - gateTelemetry.started_at_ms;
    }
  } else {
    consecutiveDistanceGreen = 0;
    if (dist.state === "red") gateTelemetry.distance_red_frames++;
    else if (dist.state === "amber") gateTelemetry.distance_amber_frames++;
    else gateTelemetry.distance_no_hand_frames++;
  }

  const lvl = evaluateLevel(T);
  updateLevelBubble(lvl, T);
  if (lvl.included) {
    if (levelChip) {
      levelChip.hidden = false;
      setChip(levelChip, lvl.state, lvl.label);
    }
    if (lvl.isGreen) {
      consecutiveLevelGreen++;
      gateTelemetry.level_green_frames++;
      if (
        consecutiveLevelGreen === requiredFrames &&
        gateTelemetry.level_first_green_ms === null &&
        gateTelemetry.started_at_ms !== null
      ) {
        gateTelemetry.level_first_green_ms = Date.now() - gateTelemetry.started_at_ms;
      }
    } else {
      consecutiveLevelGreen = 0;
      if (lvl.state === "red") gateTelemetry.level_red_frames++;
      else if (lvl.state === "amber") gateTelemetry.level_amber_frames++;
      else gateTelemetry.level_no_data_frames++;
    }
  } else if (lvl.state === "skipped" && lvl.label) {
    if (levelChip && !levelMarkedSkipped) {
      levelChip.hidden = false;
      setChip(levelChip, "skipped", lvl.label);
      levelMarkedSkipped = true;
    }
  } else if (levelChip) {
    levelChip.hidden = true;
  }

  const distancePass = consecutiveDistanceGreen >= requiredFrames;
  const levelPass = !lvl.included || consecutiveLevelGreen >= requiredFrames;
  if (shutterBtn) shutterBtn.disabled = !(distancePass && levelPass);
}

function abandonGate(distanceLabel) {
  if (window.OrientationDetector) window.OrientationDetector.stop();
  if (levelChip) levelChip.hidden = true;
  if (levelBubble) {
    levelBubble.hidden = true;
    levelBubble.dataset.state = "pending";
    if (levelDot) levelDot.style.transform = "translate(-50%, -50%)";
  }
  setChip(distanceChip, "skipped", distanceLabel);
  if (shutterBtn) shutterBtn.disabled = false;
}

async function startGateLoop() {
  gateTelemetry = createTelemetry();
  gateTelemetry.started_at_ms = Date.now();
  gateTelemetry.threshold_used =
    (window.PreviewThresholds && window.PreviewThresholds.HAND_SPAN_RATIO_MIN) || null;
  gateTelemetry.orientation_status = orientationStatus;
  consecutiveDistanceGreen = 0;
  consecutiveLevelGreen = 0;
  latestOrientation = null;
  levelStartedAtMs = Date.now();
  levelMarkedSkipped = false;
  mediaPipeReady = false;
  if (shutterBtn) shutterBtn.disabled = true;
  setChip(distanceChip, "pending", "Distance: starting…");

  if (orientationStatus === "granted" && window.OrientationDetector) {
    if (levelChip) {
      levelChip.hidden = false;
      setChip(levelChip, "pending", "Level: starting…");
    }
    if (levelBubble) {
      levelBubble.hidden = false;
      levelBubble.dataset.state = "pending";
      if (levelDot) levelDot.style.transform = "translate(-50%, -50%)";
    }
    window.OrientationDetector.start((data) => {
      latestOrientation = data;
    });
  } else {
    if (levelChip) levelChip.hidden = true;
    if (levelBubble) {
      levelBubble.hidden = true;
      levelBubble.dataset.state = "pending";
      if (levelDot) levelDot.style.transform = "translate(-50%, -50%)";
    }
  }

  if (!window.HandsDetector) {
    abandonGate("Hands module didn't load");
    return;
  }
  try {
    await window.HandsDetector.init();
    mediaPipeReady = true;
  } catch (err) {
    console.warn("MediaPipe init failed; distance gate disabled", err);
    const detail = err && err.message ? String(err.message).slice(0, 60) : "init failed";
    abandonGate(`Distance check off: ${detail}`);
    return;
  }
  detectionTimer = setInterval(runDetectionTick, 100);
}

function stopGateLoop() {
  if (detectionTimer) {
    clearInterval(detectionTimer);
    detectionTimer = null;
  }
  if (window.OrientationDetector) window.OrientationDetector.stop();
  consecutiveDistanceGreen = 0;
  consecutiveLevelGreen = 0;
  latestOrientation = null;
}

// Same pattern as desktop: stage anchored to top:0/bottom:0 with the
// URL-bar height pushed into a CSS variable so the bottom controls
// stay above iOS Safari's URL bar without leaving a gap below.
function syncCaptureInsets(stageEl) {
  const layoutH = window.innerHeight;
  const vv = window.visualViewport;
  const visualH = vv ? vv.height : layoutH;
  const offsetTop = vv ? vv.offsetTop : 0;
  const urlBarH = Math.max(0, layoutH - visualH - offsetTop);
  stageEl.style.setProperty("--capture-url-bar-inset", `${urlBarH}px`);
}

async function refreshFlash() {
  if (!flashBtn || !window.CapturePreview) return;
  if (!window.CapturePreview.isTorchSupported()) {
    flashBtn.hidden = true;
    return;
  }
  flashBtn.hidden = false;
  flashBtn.setAttribute("aria-pressed", "true");
  flashBtn.setAttribute("aria-label", "Turn flash off");
  try {
    await window.CapturePreview.setTorch(true);
  } catch (err) {
    flashBtn.setAttribute("aria-pressed", "false");
    flashBtn.setAttribute("aria-label", "Turn flash on");
  }
}

async function toggleFlash() {
  if (!flashBtn || !window.CapturePreview) return;
  const wasOn = flashBtn.getAttribute("aria-pressed") === "true";
  const next = !wasOn;
  flashBtn.setAttribute("aria-pressed", next ? "true" : "false");
  flashBtn.setAttribute("aria-label", next ? "Turn flash off" : "Turn flash on");
  try {
    await window.CapturePreview.setTorch(next);
  } catch (err) {
    flashBtn.setAttribute("aria-pressed", wasOn ? "true" : "false");
    flashBtn.setAttribute("aria-label", wasOn ? "Turn flash off" : "Turn flash on");
    setStatus("Could not toggle flash on this device.", true);
  }
}

async function shoot(nav) {
  if (!shutterBtn || !window.CapturePreview) return;
  shutterBtn.disabled = true;
  setStatus("Capturing…");
  let blob;
  try {
    blob = await window.CapturePreview.captureFrame(videoEl);
  } catch (err) {
    setStatus(`Capture failed: ${err.message || err}`, true);
    shutterBtn.disabled = false;
    return;
  }
  // Hand the captured frame off to the confirm step. The /api/measure
  // POST happens there so the user can review the photo (and the
  // measuring timer has its own dedicated screen).
  if (session.imageUrl && session.imageUrl.startsWith("blob:")) {
    URL.revokeObjectURL(session.imageUrl);
  }
  session.imageBlob = blob;
  session.imageUrl = URL.createObjectURL(blob);
  session.imageSource = "camera";
  session.gateTelemetry = {
    ...gateTelemetry,
    captured_at_ms: gateTelemetry.started_at_ms ? Date.now() - gateTelemetry.started_at_ms : null,
    media_pipe_ready: mediaPipeReady,
    capture_width: videoEl.videoWidth || null,
    capture_height: videoEl.videoHeight || null,
    surface: "mobile",
  };

  stopGateLoop();
  window.CapturePreview.stop();
  nav.next();
}

export default {
  mount(container, nav) {
    container.innerHTML = `
      <section class="step step-capture">
        <video id="captureVideo" class="capture-video" autoplay playsinline muted></video>

        <button type="button" class="capture-back" aria-label="Back">←</button>
        <button type="button" class="capture-flash" hidden aria-label="Turn flash on" aria-pressed="false">
          <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
            <path d="M13 2 L4 14 L11 14 L9 22 L20 9 L13 9 Z" fill="currentColor" />
          </svg>
        </button>

        <div class="capture-level-bubble" id="captureLevelBubble" data-state="pending" hidden aria-hidden="true">
          <div class="bubble-tolerance"></div>
          <div class="bubble-crosshair-h"></div>
          <div class="bubble-crosshair-v"></div>
          <div class="bubble-indicator" id="captureLevelDot">
            <div class="bubble-indicator-h"></div>
            <div class="bubble-indicator-v"></div>
          </div>
        </div>

        <div class="capture-chips">
          <div class="status-chip pending" id="captureDistanceChip">
            <span class="chip-dot" aria-hidden="true"></span>
            <span class="chip-label">Distance: starting…</span>
          </div>
          <div class="status-chip pending" id="captureLevelChip" hidden>
            <span class="chip-dot" aria-hidden="true"></span>
            <span class="chip-label">Level: starting…</span>
          </div>
        </div>

        <p class="capture-status" id="captureStatus">Requesting camera…</p>

        <div class="capture-controls">
          <button id="captureShutterBtn" type="button" class="primary capture-shutter" disabled>
            Take Photo
          </button>
        </div>
      </section>
    `;

    const stage = container.querySelector(".step-capture");
    videoEl = container.querySelector("#captureVideo");
    distanceChip = container.querySelector("#captureDistanceChip");
    levelChip = container.querySelector("#captureLevelChip");
    levelBubble = container.querySelector("#captureLevelBubble");
    levelDot = container.querySelector("#captureLevelDot");
    shutterBtn = container.querySelector("#captureShutterBtn");
    flashBtn = container.querySelector(".capture-flash");
    statusEl = container.querySelector("#captureStatus");

    container.querySelector(".capture-back").addEventListener("click", () => {
      // Tear-down happens in unmount() when the step controller swaps
      // us out; just trigger the back transition.
      nav.back();
    });
    shutterBtn.addEventListener("click", () => shoot(nav));
    flashBtn.addEventListener("click", toggleFlash);

    // URL-bar inset sync. Same pattern as v5 capture stage.
    const sync = () => syncCaptureInsets(stage);
    sync();
    requestAnimationFrame(sync);
    if (window.visualViewport) {
      window.visualViewport.addEventListener("resize", sync);
      window.visualViewport.addEventListener("scroll", sync);
      viewportListener = sync;
    }

    const generation = ++mountGeneration;
    (async () => {
      // Orientation permission must be requested in response to the
      // user gesture that triggered this step (the prep step's "Open
      // camera" button click bubbles into this navigation, so we are
      // still inside the gesture's task).
      if (window.OrientationDetector) {
        try {
          orientationStatus = await window.OrientationDetector.requestPermission();
        } catch (err) {
          orientationStatus = "denied";
        }
      } else {
        orientationStatus = "unsupported";
      }
      // Bail if unmount fired while we were suspended — without this
      // we'd start the camera and gate-loop interval on a step that
      // has already torn down, leaking both.
      if (generation !== mountGeneration) return;

      try {
        await window.CapturePreview.start(videoEl);
      } catch (err) {
        setStatus(`Camera unavailable: ${err.message || err}`, true);
        return;
      }
      if (generation !== mountGeneration) {
        window.CapturePreview.stop();
        return;
      }
      setStatus("Get both green to unlock the shutter — hold level, at the right distance.");
      await refreshFlash();
      if (generation !== mountGeneration) {
        window.CapturePreview.stop();
        return;
      }
      await startGateLoop();
      if (generation !== mountGeneration) {
        stopGateLoop();
        window.CapturePreview.stop();
      }
    })();
  },

  unmount() {
    mountGeneration++;
    stopGateLoop();
    if (window.CapturePreview) window.CapturePreview.stop();
    if (viewportListener && window.visualViewport) {
      window.visualViewport.removeEventListener("resize", viewportListener);
      window.visualViewport.removeEventListener("scroll", viewportListener);
    }
    viewportListener = null;
    videoEl = null;
    distanceChip = null;
    levelChip = null;
    levelBubble = null;
    levelDot = null;
    shutterBtn = null;
    flashBtn = null;
    statusEl = null;
  },
};
