// Step 2 — Email + Ring Model.
// Mirrors the desktop hero-card's top "controls" block.
// Persists answers in session so back-nav preserves them.
// Email (not name) is the cross-table join key — see doc/v8/PRD.md.

import { session } from "../session.js";

export default {
  mount(container, nav) {
    container.innerHTML = `
      <section class="step step-form">
        <header class="step-head">
          <button type="button" class="step-back" aria-label="Back">←</button>
        </header>
        <div class="step-body">
          <div class="panel">
            <p class="hero-eyebrow">Step 1 of 4</p>
            <h2 class="panel-title">Select Ring Model</h2>
            <div class="controls">
              <label>
                <span>Ring Model</span>
                <select id="formRingModel">
                  <option value="gen">Gen1/Gen2</option>
                  <option value="air">Air</option>
                </select>
              </label>
              <label>
                <span>Email</span>
                <input
                  type="email"
                  id="formKolEmail"
                  placeholder="you@example.com"
                  autocomplete="email"
                  inputmode="email"
                />
              </label>
            </div>
            <p class="form-error" id="formError" hidden></p>
          </div>
        </div>
        <footer class="step-foot">
          <button type="button" class="primary step-next">Continue</button>
        </footer>
      </section>
    `;

    const emailInput = container.querySelector("#formKolEmail");
    const modelSelect = container.querySelector("#formRingModel");
    const errorEl = container.querySelector("#formError");

    // Pre-fill from session — back-nav from upload/camera should not
    // ask the user to retype.
    emailInput.value = session.kolEmail || "";
    modelSelect.value = session.ringModel || "gen";

    // Loose RFC-ish check — `something@something.tld`. The browser's
    // native type="email" validity is the first line of defense; this
    // guards against the field being left blank or obviously malformed
    // since email is the cross-table join key.
    const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

    container.querySelector(".step-back").addEventListener("click", nav.back);
    container.querySelector(".step-next").addEventListener("click", () => {
      const email = emailInput.value.trim().toLowerCase();
      if (!EMAIL_RE.test(email)) {
        errorEl.textContent = "Please enter a valid email before continuing.";
        errorEl.hidden = false;
        emailInput.focus();
        return;
      }
      session.kolEmail = email;
      session.ringModel = modelSelect.value;
      nav.next();
    });
  },
};
