// v5 Phase 3 — DeviceOrientationEvent for the level gate.
//
// Encapsulates the iOS 13+ requestPermission() dance, falls back gracefully
// where the API is missing, and exposes a callback-based stream of
// {beta, gamma} readings. Loaded as a non-module IIFE attached to window so
// the classic-script app.js can call it directly (matching preview.js).
//
// Permission semantics:
//   "granted"     — events should fire; caller can attach the listener
//   "denied"      — user explicitly declined; respect that and skip the gate
//   "unsupported" — browser doesn't expose DeviceOrientationEvent at all
//
// The desktop case (DeviceOrientationEvent exists but no sensor) is reported
// as "granted" — events will fire but with null beta/gamma. Caller is
// responsible for treating "no data after some time" as "skipped" and
// excluding the level signal from the gate.

window.OrientationDetector = (function () {
  let activeHandler = null;
  let receivedAny = false;

  async function requestPermission() {
    if (typeof DeviceOrientationEvent === "undefined") {
      return "unsupported";
    }
    // Non-iOS browsers do not require an explicit grant — they fire events
    // immediately when an attached listener is present (subject to policy).
    if (typeof DeviceOrientationEvent.requestPermission !== "function") {
      return "granted";
    }
    try {
      const result = await DeviceOrientationEvent.requestPermission();
      return result; // "granted" | "denied"
    } catch (err) {
      // Spec says the rejection is permanent for this origin within the
      // session — same observable behaviour as a denial, so map to that.
      return "denied";
    }
  }

  function start(callback) {
    stop();
    receivedAny = false;
    activeHandler = function (event) {
      // Desktop browsers fire `deviceorientation` with null beta/gamma
      // (the API exists, the sensor doesn't). Drop those silently — the
      // caller's no-data-after-timeout logic decides whether to skip.
      // Also drop non-finite (NaN/Infinity) readings — rare but observed
      // on misbehaving sensors; would otherwise propagate into the gate
      // and CSS `calc()` as NaN, which silently freezes the indicator.
      if (
        event.beta === null ||
        event.gamma === null ||
        !Number.isFinite(event.beta) ||
        !Number.isFinite(event.gamma)
      ) {
        return;
      }
      receivedAny = true;
      callback({ beta: event.beta, gamma: event.gamma });
    };
    window.addEventListener("deviceorientation", activeHandler);
  }

  function stop() {
    if (activeHandler) {
      window.removeEventListener("deviceorientation", activeHandler);
      activeHandler = null;
    }
  }

  function hasReceivedData() {
    return receivedAny;
  }

  return { requestPermission, start, stop, hasReceivedData };
})();
