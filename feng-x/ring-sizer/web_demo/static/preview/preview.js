// v5 Phase 1 — camera lifecycle + frame capture.
// No gates yet; that's Phase 2-4. This module owns the MediaStream and
// exposes start/stop/captureFrame so app.js can wire UI events to it.
//
// Loaded as a non-module IIFE attached to window so it can coexist with
// the existing app.js (which is also non-module). Convert both to ES
// modules later if v5 adds a bundler.

window.CapturePreview = (function () {
  let activeStream = null;
  let activeVideo = null;

  function isSupported() {
    // getUserMedia requires a secure context (HTTPS or localhost). On HTTP
    // LAN IPs, Chrome leaves navigator.mediaDevices undefined; Safari
    // exposes the namespace but getUserMedia() rejects. Check secure
    // context up-front so the "Use Camera" button stays hidden in
    // insecure-test setups instead of opening a doomed flow.
    return !!(
      window.isSecureContext &&
      navigator.mediaDevices &&
      typeof navigator.mediaDevices.getUserMedia === "function"
    );
  }

  async function start(videoEl) {
    if (!window.isSecureContext) {
      throw new Error(
        "Camera requires HTTPS. Open the deployed (Hugging Face) URL, or set up HTTPS locally — http://<LAN-IP> won't work."
      );
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error("This browser does not expose getUserMedia.");
    }
    stop();
    // facingMode 'environment' = rear camera. 'ideal' (not 'exact') so
    // desktop laptops without a rear camera still open the front cam
    // rather than rejecting outright.
    //
    // Width/height are also `ideal` hints — the UA picks the closest
    // mode the camera actually supports. We ask for 4K because the
    // kol_success training set is ~3024×4032 native iPhone captures and
    // sub-1080 frames noticeably soften the finger boundary. Modern
    // iPhones and high-end Android phones honor 3840×2160; lesser
    // hardware quietly negotiates down (typically to 1920×1080), which
    // is still our previous baseline. No outright rejection.
    const stream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: { ideal: "environment" },
        width: { ideal: 3840 },
        height: { ideal: 2160 },
      },
      audio: false,
    });
    videoEl.srcObject = stream;
    // iOS Safari needs muted + playsinline (set as HTML attrs) to autoplay.
    await videoEl.play();
    activeStream = stream;
    activeVideo = videoEl;
    return stream;
  }

  function stop() {
    if (activeStream) {
      activeStream.getTracks().forEach((t) => t.stop());
      activeStream = null;
    }
    if (activeVideo) {
      activeVideo.srcObject = null;
      activeVideo = null;
    }
  }

  function getActiveVideoTrack() {
    if (!activeStream) return null;
    const tracks = activeStream.getVideoTracks();
    return tracks.length ? tracks[0] : null;
  }

  // Torch (camera flash) support is Chromium-on-Android only — iOS
  // Safari/WebKit does not expose `torch` in MediaTrackCapabilities, and
  // most front cameras lack an LED even on Android. Callers must hide
  // the flash UI when this returns false.
  function isTorchSupported() {
    const track = getActiveVideoTrack();
    if (!track || typeof track.getCapabilities !== "function") return false;
    let caps;
    try {
      caps = track.getCapabilities();
    } catch (err) {
      return false;
    }
    return !!(caps && caps.torch);
  }

  async function setTorch(on) {
    const track = getActiveVideoTrack();
    if (!track) throw new Error("No active video track");
    await track.applyConstraints({ advanced: [{ torch: !!on }] });
  }

  // Draw the current video frame to an offscreen canvas at native sensor
  // resolution and encode as a JPEG Blob suitable for FormData submission.
  // The server's existing /api/measure path accepts this with no changes.
  async function captureFrame(videoEl, mimeType, quality) {
    const w = videoEl.videoWidth;
    const h = videoEl.videoHeight;
    if (!w || !h) {
      throw new Error("Video stream has no dimensions yet");
    }
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(videoEl, 0, 0, w, h);
    return new Promise((resolve, reject) => {
      canvas.toBlob(
        (blob) =>
          blob ? resolve(blob) : reject(new Error("toBlob returned null")),
        mimeType || "image/jpeg",
        typeof quality === "number" ? quality : 0.92,
      );
    });
  }

  return { isSupported, start, stop, captureFrame, isTorchSupported, setTorch };
})();
