// Step 6 — Result.
//
// Mirrors the desktop result section: a "Result Overlay" panel
// showing the algorithm's annotated image, then a "Ring Size
// Recommendation" panel with one card per measured finger and the
// ring-size reference table at the bottom. Reads
// `session.result` (the /api/measure response) and `session.ringModel`.

import { session, resetForRetake } from "../session.js";
import { formatFailReason } from "../../shared/fail-reasons.js";
import { submitFeedback } from "../../shared/feedback.js";

const FINGER_LABEL = {
  index: "Index Finger",
  middle: "Middle Finger",
  ring: "Ring Finger",
};
const FINGER_COLOR = {
  index: "#00dddd",
  middle: "#3b82f6",
  ring: "#dd44dd",
};
const RING_MODEL_LABELS = { gen: "Gen1/Gen2", air: "Air" };
const RING_SIZE_TABLES = {
  gen: { 6: 16.9, 7: 17.7, 8: 18.6, 9: 19.4, 10: 20.3, 11: 21.1, 12: 21.9, 13: 22.7 },
  air: { 6: 16.6, 7: 17.4, 8: 18.2, 9: 19.0, 10: 19.9, 11: 20.7, 12: 21.5, 13: 22.3 },
};

function escape(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function fingerCardHtml(fn, pf) {
  const label = FINGER_LABEL[fn] || fn;
  const color = FINGER_COLOR[fn] || "#888";
  const badge = fn === "index" ? `<span class="finger-badge">Recommended</span>` : "";
  if (pf.status !== "ok") {
    return `
      <div class="finger-card finger-card-failed" style="border-top: 3px solid ${color};">
        ${badge}
        <div class="finger-name">${escape(label)}</div>
        <div class="finger-failed">Failed</div>
        <div class="finger-fail-reason">${escape(pf.fail_reason || "unknown")}</div>
      </div>
    `;
  }
  const widthMm = pf.diameter_cm ? (pf.diameter_cm * 10).toFixed(1) : "—";
  const range = pf.range ? `${pf.range[0]} – ${pf.range[1]}` : "";
  return `
    <div class="finger-card" style="border-top: 3px solid ${color};">
      ${badge}
      <div class="finger-name">${escape(label)}</div>
      <div class="finger-size-label">Size</div>
      <div class="finger-size">${escape(pf.best_match)}</div>
      ${range ? `<div class="finger-range">Range: ${escape(range)}</div>` : ""}
      <div class="finger-width">Diameter: ${escape(widthMm)} mm</div>
    </div>
  `;
}

function buildSizeRefTable(ringModel) {
  const sizeTable = RING_SIZE_TABLES[ringModel] || RING_SIZE_TABLES.gen;
  const modelLabel = RING_MODEL_LABELS[ringModel] || ringModel;
  const rows = Object.entries(sizeTable)
    .map(([size, mm]) => `<tr><td>${size}</td><td>${mm.toFixed(1)}</td></tr>`)
    .join("");
  return `
    <div class="size-ref-table">
      <h3 class="size-ref-title">Size Reference (${escape(modelLabel)})</h3>
      <table>
        <thead><tr><th>Size</th><th>Inner Diameter (mm)</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function renderRecommendation(payload, ringModel) {
  // The status banner above this panel already explains the failure
  // case (using the friendly desktop copy via formatFailReason), so
  // we don't repeat a "Measurement Failed" hero here. Just render
  // whatever finger data made it back, the count, and the size
  // reference — useful even when nothing measured.
  const perFinger = (payload && payload.per_finger) || {};
  let cards = "";
  for (const fn of ["index", "middle", "ring"]) {
    const pf = perFinger[fn];
    if (!pf) continue;
    cards += fingerCardHtml(fn, pf);
  }
  const evidenceText = window.SessionEvidence.text(payload);
  // Session evidence replaces the old "N/N fingers measured" footer. Failed
  // fingers remain explicit in their own cards, while this line explains the
  // strength of the recommendation and the target number of repeat captures.
  return `
    ${cards ? `<div class="finger-cards">${cards}</div>` : ""}
    ${evidenceText ? `<div class="finger-count">${escape(evidenceText)}</div>` : ""}
    ${buildSizeRefTable(ringModel)}
  `;
}

export default {
  mount(container, nav) {
    const data = session.result;
    if (!data) {
      // Defensive — nothing to show, kick back to start.
      nav.goTo("intro");
      return;
    }
    const payload = data.result || data;
    const recommendation = data.session_recommendation || payload;
    const overlayUrl = data.result_image_url;
    const ringModel = session.ringModel || "gen";

    // Same success/error rule the desktop uses (web_demo/app.py
    // sets `data.success = result.fail_reason is None`). Status copy
    // is sourced from shared/fail-reasons.js so the mobile and
    // desktop surfaces stay in sync.
    const succeeded = !!data.success && payload && payload.per_finger;
    const statusBanner = succeeded
      ? `
        <div class="result-status result-status-success">
          <p>Measurement complete.</p>
        </div>
      `
      : `
        <div class="result-status result-status-error">
          <p>${escape(formatFailReason(payload && payload.fail_reason))}</p>
        </div>
      `;

    // The server always sends a result_image_url, but on hard failures
    // (e.g. hand_not_detected) no PNG is actually written and the URL
    // 404s. Soft failures (e.g. card_not_detected — hand was detected,
    // mask was rendered) DO produce a partial overlay PNG that's useful
    // for the user. So don't gate on `succeeded`; always try to load
    // the image, and rely on <img onerror> to remove a broken one. CSS
    // gives .image-frame a min-height and soft background, so an empty
    // frame reads as a clean placeholder.
    const overlayInner = overlayUrl
      ? `<img src="${escape(overlayUrl)}" alt="Measurement overlay"
              onerror="this.remove()" />`
      : "";
    // Only invite feedback after a successful run — asking "how did it
    // go?" on top of an error reads as tone-deaf, and ratings attached
    // to failed rows would skew dashboard stats.
    const feedbackPanel = succeeded && data.run_id
      ? `
        <div class="panel feedback-panel">
          <h2 class="panel-title">How did it go?</h2>
          <p class="feedback-hint">Rate this measurement and tell us anything you'd like to share or ask.</p>
          <form class="feedback-form" id="mobileFeedbackForm">
            <div class="feedback-rating" role="radiogroup" aria-label="Rating">
              ${[1, 2, 3, 4, 5].map((v) => `
                <button type="button" class="star-btn" data-value="${v}" role="radio" aria-checked="false" aria-label="${v} star${v > 1 ? "s" : ""}">★</button>
              `).join("")}
            </div>
            <textarea class="feedback-message" name="message" rows="4" maxlength="4000"
                      placeholder="Your comment or question (optional)"></textarea>
            <div class="feedback-row">
              <button type="submit" class="primary feedback-submit">Send</button>
              <span class="feedback-status" aria-live="polite"></span>
            </div>
          </form>
        </div>
      `
      : "";

    container.innerHTML = `
      <section class="step step-result">
        <div class="step-body">
          ${statusBanner}
          <div class="panel">
            <h2 class="panel-title">Current Photo Overlay</h2>
            <div class="image-frame show">${overlayInner}</div>
          </div>

          <div class="panel">
            <h2 class="panel-title">Ring Size Recommendation</h2>
            ${renderRecommendation(recommendation, ringModel)}
          </div>

          ${feedbackPanel}
        </div>
        <footer class="step-foot">
          <button type="button" class="primary step-retake">Measure Again to Confirm</button>
        </footer>
      </section>
    `;

    const feedbackForm = container.querySelector("#mobileFeedbackForm");
    if (feedbackForm) {
      const messageEl = feedbackForm.querySelector(".feedback-message");
      const statusEl = feedbackForm.querySelector(".feedback-status");
      const submitEl = feedbackForm.querySelector(".feedback-submit");
      const starButtons = Array.from(feedbackForm.querySelectorAll(".star-btn"));
      let rating = 0;
      const paintStars = () => {
        starButtons.forEach((btn) => {
          const v = Number(btn.dataset.value);
          const filled = v <= rating;
          btn.classList.toggle("star-filled", filled);
          btn.setAttribute("aria-checked", v === rating ? "true" : "false");
        });
      };
      const updateSubmitEnabled = () => {
        const hasMessage = (messageEl.value || "").trim().length > 0;
        submitEl.disabled = !(rating || hasMessage);
      };
      updateSubmitEnabled();
      messageEl.addEventListener("input", updateSubmitEnabled);
      starButtons.forEach((btn) => {
        btn.addEventListener("click", () => {
          // Set-only (no toggle-to-clear) — see desktop app.js for
          // the rationale; the previous behavior made it easy to wipe
          // a rating with an accidental double-tap.
          rating = Number(btn.dataset.value);
          paintStars();
          updateSubmitEnabled();
        });
      });

      feedbackForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const message = (messageEl.value || "").trim();
        if (!rating && !message) {
          statusEl.textContent = "Pick a rating or write a comment.";
          statusEl.className = "feedback-status feedback-status-error";
          return;
        }
        if (!data.run_id) {
          statusEl.textContent = "No measurement to attach this to.";
          statusEl.className = "feedback-status feedback-status-error";
          return;
        }
        submitEl.disabled = true;
        statusEl.textContent = "Sending…";
        statusEl.className = "feedback-status";
        const res = await submitFeedback({
          runId: data.run_id,
          rating: rating || undefined,
          message,
        });
        if (res.success) {
          statusEl.textContent = "Thanks — sent.";
          statusEl.className = "feedback-status feedback-status-ok";
          messageEl.value = "";
          rating = 0;
          paintStars();
        } else {
          statusEl.textContent = `Couldn't send: ${res.error || "try again"}`;
          statusEl.className = "feedback-status feedback-status-error";
        }
        updateSubmitEnabled();
      });
    }

    // "Measure again" returns to the photo-guide step so the user can
    // pick between Open Camera and Upload from photos — the upload
    // entry was added after this button originally jumped straight to
    // the camera. Form fields (Name / Ring Model) are preserved; only
    // the photo + result + telemetry are wiped. Users who want a full
    // reset (e.g. handing the phone to a different person) can
    // refresh the page.
    container.querySelector(".step-retake").addEventListener("click", () => {
      resetForRetake();
      nav.goTo("guide");
    });
  },
};
