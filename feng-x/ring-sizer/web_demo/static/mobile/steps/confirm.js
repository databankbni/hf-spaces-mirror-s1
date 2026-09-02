// Step 5 — Confirm the photo + run measurement.
//
// Receives `session.imageBlob` from either the upload step (step 3,
// file picked) or the capture step (step 4, camera shutter). Shows
// the photo so the user can decide whether to keep it, then on
// "Start Measurement" POSTs to /api/measure and shows a live
// elapsed-time counter — the algorithm can take 20-30 s and silence
// during that wait is the worst UX. When the response arrives, we
// store it on `session.result` and advance to the result step.

import { session } from "../session.js";
import { postMeasure } from "../../shared/measure-api.js";

let elapsedTimer = null;

function clearTimerFn() {
  if (elapsedTimer) {
    clearInterval(elapsedTimer);
    elapsedTimer = null;
  }
}

export default {
  mount(container, nav) {
    if (!session.imageBlob) {
      // Defensive: someone reached this step without an image.
      // Send them back to the photo guide rather than leaving them
      // staring at an empty preview.
      nav.goTo("guide");
      return;
    }

    const sourceLabel =
      session.imageSource === "camera" ? "Captured Photo" : "Uploaded Photo";

    container.innerHTML = `
      <section class="step step-confirm">
        <header class="step-head">
          <button type="button" class="step-back" aria-label="Back">←</button>
        </header>
        <div class="step-body">
          <div class="panel">
            <p class="hero-eyebrow">Step 3 of 4</p>
            <h2 class="panel-title">${sourceLabel}</h2>
            <div class="image-frame show">
              <img id="confirmPreview" alt="Photo to measure" />
            </div>
          </div>
        </div>
        <footer class="step-foot">
          <!-- Status sits in the footer (which never scrolls) so the
               live "Measuring…" feedback stays visible even when the
               photo is tall enough to push the rest of the panel
               content off-screen. Empty before the user taps Start
               Measurement — no pre-measurement placeholder. -->
          <p class="confirm-status" id="confirmStatus" hidden></p>
          <button id="confirmStartBtn" type="button" class="primary">
            Start Measurement
          </button>
        </footer>
      </section>
    `;

    const previewImg = container.querySelector("#confirmPreview");
    const statusEl = container.querySelector("#confirmStatus");
    const startBtn = container.querySelector("#confirmStartBtn");

    previewImg.src = session.imageUrl;

    container.querySelector(".step-back").addEventListener("click", () => {
      // Sending the user back to the photo-guide step is the sanest
      // default. The capture step would re-open the camera and
      // discard the photo we just captured, which is hardly ever
      // what the user wants.
      nav.goTo("guide");
    });

    startBtn.addEventListener("click", async () => {
      startBtn.disabled = true;
      statusEl.hidden = false;

      // Live elapsed-time counter — copy mirrors the desktop's
      // setStatus(`Measuring… Done in under a minute. (${secs}s)`)
      // so both surfaces show identical feedback during the wait.
      const startedAt = Date.now();
      const renderTimer = () => {
        const secs = Math.floor((Date.now() - startedAt) / 1000);
        statusEl.textContent = `Measuring… Done in under a minute. (${secs}s)`;
        statusEl.classList.remove("error");
      };
      renderTimer();
      elapsedTimer = setInterval(renderTimer, 1000);

      try {
        const sessionContext = {
          kol_email: session.kolEmail,
          ring_model: session.ringModel,
          mode: "multi",
          finger_index: "index",
          source: "photo",
        };
        const measurementSession = window.MeasurementSession.prepare(sessionContext);
        const result = await postMeasure({
          blob: session.imageBlob,
          kol_email: session.kolEmail,
          ring_model: session.ringModel,
          gate_telemetry: session.gateTelemetry,
          capture_method: session.imageSource === "camera" ? "camera" : "upload",
          session_id: measurementSession.session_id,
          session_state: measurementSession.session_state,
        });
        clearTimerFn();
        window.MeasurementSession.accept(sessionContext, result);
        session.result = result;
        nav.next();
      } catch (err) {
        clearTimerFn();
        statusEl.textContent = `Measurement failed: ${err.message || err}`;
        statusEl.classList.add("error");
        startBtn.disabled = false;
      }
    });
  },

  unmount() {
    clearTimerFn();
  },
};
