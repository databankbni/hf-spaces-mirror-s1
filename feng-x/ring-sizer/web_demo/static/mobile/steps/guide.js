// Step 3 — Photo guide.
//
// Shows the same five-bullet tips list the desktop displays, plus the
// pre-bundled sample photo as a concrete "like this" example so the
// user knows exactly what they're aiming for. Two actions at the
// bottom: a primary "Open Camera" (preferred path — feeds the live
// capture coach with level + distance gates) and a secondary ghost
// link "Upload from photos" for users with a usable shot already in
// the camera roll. Upload bypasses the capture step entirely and
// hands the file straight to the confirm step.

import { session, resetForRetake } from "../session.js";

export default {
  mount(container, nav) {
    container.innerHTML = `
      <section class="step step-guide">
        <header class="step-head">
          <button type="button" class="step-back" aria-label="Back">←</button>
        </header>
        <div class="step-body">
          <div class="panel">
            <p class="hero-eyebrow">Step 2 of 4</p>
            <h2 class="panel-title">Photo Guidance</h2>

            <ul class="capture-tips">
              <li>Place a card of <strong>standard credit card size</strong> beside your hand.</li>
              <li>Hold phone <strong>directly above hand</strong>, parallel to table.</li>
              <li>Use <strong>flat, plain background</strong>, a sheet of paper works great.</li>
            </ul>

            <figure class="guide-example">
              <figcaption>Like this — hand flat, card beside it.</figcaption>
              <img
                src="/static/examples/default_sample.jpg"
                alt="Example photo: hand flat with a credit card placed beside it"
              />
            </figure>
          </div>
        </div>
        <footer class="step-foot">
          <button type="button" class="primary step-next">Open Camera</button>
          <button type="button" class="step-link guide-upload">Upload from photos</button>
          <p class="guide-upload-error" id="guideUploadError" hidden role="alert"></p>
          <input
            type="file"
            id="guideFileInput"
            class="guide-file-input"
            accept="image/*"
            hidden
          />
        </footer>
      </section>
    `;

    container.querySelector(".step-back").addEventListener("click", nav.back);
    container.querySelector(".step-next").addEventListener("click", nav.next);

    const fileInput = container.querySelector("#guideFileInput");
    const errorEl = container.querySelector("#guideUploadError");
    const showUploadError = (msg) => {
      if (!errorEl) return;
      errorEl.textContent = msg;
      errorEl.hidden = false;
    };
    const clearUploadError = () => {
      if (!errorEl) return;
      errorEl.hidden = true;
      errorEl.textContent = "";
    };
    container.querySelector(".guide-upload").addEventListener("click", () => {
      clearUploadError();
      // Reset value so picking the same file twice still fires `change`.
      fileInput.value = "";
      fileInput.click();
    });
    fileInput.addEventListener("change", (ev) => {
      const file = ev.target.files && ev.target.files[0];
      if (!file) return;
      // `accept="image/*"` is a hint, not enforcement — Android's "Files"
      // picker lets users pick anything. Validate at source so the
      // downstream confirm/measure steps don't render a broken image
      // or POST garbage and surface a backend 4xx.
      if (!file.type.startsWith("image/") || file.size === 0) {
        showUploadError("Please pick an image file (JPG or PNG).");
        return;
      }
      // Drop any prior session image (camera capture or earlier upload)
      // so the confirm step sees a clean slate.
      resetForRetake();
      session.imageBlob = file;
      session.imageUrl = URL.createObjectURL(file);
      session.imageSource = "upload";
      // Skip the capture step — uploads bypass the live coach by design.
      nav.goTo("confirm");
    });
  },
};
