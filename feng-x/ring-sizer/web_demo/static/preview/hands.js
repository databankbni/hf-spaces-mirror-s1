// v5 Phase 2 — in-browser MediaPipe Hands for the distance gate.
//
// Loaded as `<script type="module">` so we can `import` directly from the
// jsdelivr CDN. The module attaches the public API to window.HandsDetector
// so the classic-script app.js can call it.
//
// CDN choice: jsdelivr-mirrored npm package (default for Phase 2). Future
// productization on Shopify may require self-hosting under
// `web_demo/static/vendor/mediapipe/` to satisfy strict CSP — see doc/v5/PRD.md
// "Risks and open questions".

// Pinned to a real published version (0.10.22 from an earlier draft did not
// exist on jsdelivr; latest at the time of pinning was 0.10.35). Bump only
// after re-validating that the entrypoint and `/wasm/` subpath both 200.
import {
  HandLandmarker,
  FilesetResolver,
} from "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.35/vision_bundle.mjs";

// Same hand-landmarker model the Python pipeline uses (see
// src/finger_segmentation.py:55). Hosting it on Google's CDN keeps the
// frontend / backend symmetric and avoids us redistributing the weights.
const MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";
const WASM_URL =
  "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.35/wasm";

// MediaPipe landmark indices for the palm-MCP span — matches
// LM_INDEX_MCP / LM_PINKY_MCP in script/analyze_hand_span.py.
const LM_INDEX_MCP = 5;
const LM_PINKY_MCP = 17;

let landmarker = null;
let initPromise = null;

async function init() {
  if (landmarker) return landmarker;
  if (initPromise) return initPromise;
  initPromise = (async () => {
    const fileset = await FilesetResolver.forVisionTasks(WASM_URL);
    landmarker = await HandLandmarker.createFromOptions(fileset, {
      baseOptions: {
        modelAssetPath: MODEL_URL,
        delegate: "GPU",
      },
      runningMode: "VIDEO",
      numHands: 1,
      minHandDetectionConfidence: 0.3,
      minTrackingConfidence: 0.3,
    });
    return landmarker;
  })();
  try {
    return await initPromise;
  } catch (err) {
    initPromise = null;
    throw err;
  }
}

// Run a single detection on the current `<video>` frame. Returns
// `{ratio, span_px}` if a hand is detected, `null` otherwise. The ratio is
// computed against `min(videoWidth, videoHeight)` so it's invariant to
// portrait vs landscape framing.
function detect(videoEl) {
  if (!landmarker) return null;
  if (!videoEl || videoEl.readyState < 2) return null;
  const w = videoEl.videoWidth;
  const h = videoEl.videoHeight;
  if (!w || !h) return null;

  const result = landmarker.detectForVideo(videoEl, performance.now());
  if (!result || !result.landmarks || result.landmarks.length === 0) {
    return null;
  }
  const lm = result.landmarks[0];
  const p5 = lm[LM_INDEX_MCP];
  const p17 = lm[LM_PINKY_MCP];
  if (!p5 || !p17) return null;

  // Landmark coords from MediaPipe Tasks are normalized [0,1] over the
  // image dimensions, so multiplying by w/h gets pixel coords.
  const dx = (p5.x - p17.x) * w;
  const dy = (p5.y - p17.y) * h;
  const span_px = Math.sqrt(dx * dx + dy * dy);
  const ratio = span_px / Math.min(w, h);
  return { ratio, span_px };
}

window.HandsDetector = { init, detect };
