// Shared result-footer copy for multi-shot recommendations.
// Kept separate from the renderers so desktop and mobile always make the
// same claim about how many measurements support the recommendation.

(function attachSessionEvidence(global) {
  "use strict";

  function measurementCount(payload) {
    const successfulShots = Number(payload && payload.successful_shots);
    if (Number.isInteger(successfulShots) && successfulShots > 0) {
      return successfulShots;
    }

    const perFinger = payload && payload.per_finger;
    if (!perFinger || typeof perFinger !== "object") return 0;
    const counts = Object.values(perFinger)
      .map((finger) => Number(finger && finger.sample_count))
      .filter((count) => Number.isInteger(count) && count > 0);
    return counts.length ? Math.max(...counts) : 0;
  }

  function text(payload) {
    const count = measurementCount(payload);
    if (!count) return "";
    const noun = count === 1 ? "measurement" : "measurements";
    const handedness = String(payload && payload.handedness || "").toLowerCase();
    const hand = handedness === "left" || handedness === "right"
      ? ` of your ${handedness} hand`
      : "";
    return `Based on ${count} ${noun}${hand}. (For best reliability, take at least 3 measurements using the same hand.)`;
  }

  global.SessionEvidence = { measurementCount, text };
})(window);
