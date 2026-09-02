// v5 capture-coach gate thresholds.
// Source of truth: doc/v5/PRD.md and script/analyze_hand_span.py results
// (72-image kol corpus, 2026-05-06 fit).
//
// Loaded as a non-module IIFE attached to window so both hands.js (module)
// and app.js (classic) can read the same constants. Convert to ES module
// when v5 introduces a bundler.

window.PreviewThresholds = (function () {
  // Distance: ‖landmark[5] - landmark[17]‖ / min(videoWidth, videoHeight).
  // Tightened to the calibration-corpus distribution on 2026-05-09 after a
  // KOL repro (Saun Jayy, n=5) showed monotonic diameter inflation when
  // hand_span_ratio drifted above the calibration P90 — every +0.01 in
  // ratio added ~0.04 cm to the index diameter, producing a 3-size spread
  // across one user. New bounds bracket the calibration corpus
  // (input/calibration_dataset/jpg, n=22): min 0.308, P10 0.318, P50 0.340,
  // P90 0.372, max 0.389. Outside this band the calibration coefficient
  // extrapolates and the per-user variance balloons.
  const HAND_SPAN_RATIO_MIN = 0.3; // a touch below calibration min (0.308); generous floor
  const HAND_SPAN_RATIO_AMBER = HAND_SPAN_RATIO_MIN * 0.95;

  // Upper distance bound. MediaPipe still returns landmarks when the hand
  // partially clips the frame, so without an upper threshold the gate
  // reads "Distance OK" even when the camera is too close — at which
  // point there is no room left for the credit card and lens distortion
  // biases the edge measurement.
  const HAND_SPAN_RATIO_MAX = 0.45; // ≈ calibration max (0.389) + ~0.06 headroom
  const HAND_SPAN_RATIO_MAX_AMBER = HAND_SPAN_RATIO_MAX * 0.95;

  // Level: DeviceOrientationEvent beta (front-back) and gamma (left-right) in
  // degrees. Tightened from 10° to 5° on 2026-05-07 — the previous
  // bound matched the card_not_parallel hard gate but felt too lax in
  // practice; ±5° gets the user closer to a clean top-down shot.
  const LEVEL_BETA_MAX_DEG = 5;
  const LEVEL_GAMMA_MAX_DEG = 5;

  // Brightness: mean luminance (0–255) of a 64×64 downsample of the preview
  // frame, computed as 0.299R + 0.587G + 0.114B. Below 60 is visibly
  // underexposed and likely to fail edge detection.
  const BRIGHTNESS_MIN_MEAN_LUM = 60;

  // Anti-jitter: number of consecutive frames a signal must hold green
  // before the gate counts it as passing. Prevents the shutter from flashing
  // on/off as the user wobbles between threshold and threshold-epsilon.
  const GATE_CONSECUTIVE_FRAMES = 3;

  return {
    HAND_SPAN_RATIO_MIN,
    HAND_SPAN_RATIO_AMBER,
    HAND_SPAN_RATIO_MAX,
    HAND_SPAN_RATIO_MAX_AMBER,
    LEVEL_BETA_MAX_DEG,
    LEVEL_GAMMA_MAX_DEG,
    BRIGHTNESS_MIN_MEAN_LUM,
    GATE_CONSECUTIVE_FRAMES,
  };
})();
