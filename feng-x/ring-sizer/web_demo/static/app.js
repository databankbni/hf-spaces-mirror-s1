const form = document.getElementById("measureForm");
const imageInput = document.getElementById("imageInput");
const statusText = document.getElementById("statusText");
const inputPreview = document.getElementById("inputPreview");
const debugPreview = document.getElementById("debugPreview");
const inputFrame = document.getElementById("inputFrame");
const debugFrame = document.getElementById("debugFrame");
const jsonOutput = document.getElementById("jsonOutput");
const jsonLink = document.getElementById("jsonLink");
const modeSelect = document.getElementById("modeSelect");
const fingerSelectGroup = document.getElementById("fingerSelectGroup");
const multiResultPanel = document.getElementById("multiResultPanel");
const overallSize = document.getElementById("overallSize");
const fingerBreakdown = document.getElementById("fingerBreakdown");
const feedbackSection = document.getElementById("feedbackSection");
const feedbackForm = document.getElementById("feedbackForm");
const feedbackMessage = document.getElementById("feedbackMessage");
const feedbackStatus = document.getElementById("feedbackStatus");
const feedbackSubmit = feedbackForm ? feedbackForm.querySelector(".feedback-submit") : null;
const feedbackStarButtons = feedbackForm ? Array.from(feedbackForm.querySelectorAll(".star-btn")) : [];
const defaultSampleUrl = window.DEFAULT_SAMPLE_URL || "";
let lastRunId = "";
let feedbackRating = 0;
const failReasonMessageMap = {
  card_not_detected:
    "Card not detected. A card of standard credit card dimensions (85.6 × 54 mm) is required as a scale reference to measure your finger diameter. Place the card beside your hand on a plain white background (e.g. a sheet of paper), and turn on your phone's flash.",
  card_not_parallel:
    "Card scale calibration failed. Keep your phone parallel to the card. Use a card of standard credit card dimensions (85.6 × 54 mm) as the reference.",
  card_near_edge:
    "Card appears cropped. Place the entire card within the photo frame.",
  card_too_small:
    "Card looks too small in the photo. Move your phone closer to the table so the card takes up a larger portion of the frame, then retake.",
  hand_not_detected:
    "Hand not detected. Place your hand flat on a plain white background (e.g. a sheet of paper), and spread your fingers naturally.",
  finger_isolation_failed:
    "Could not isolate the selected finger. Keep one target finger extended and separated.",
  finger_not_fully_visible:
    "Finger is partially out of frame. Move hand to center of photo.",
  finger_mask_too_small:
    "Finger region is too small. Move closer and use a higher-resolution photo.",
  fingers_too_close:
    "Fingers are too close together. Spread your fingers apart naturally.",
  contour_extraction_failed:
    "Finger contour extraction failed. Improve lighting and reduce background clutter.",
  axis_estimation_failed:
    "Finger axis estimation failed. Keep the finger straight and fully visible.",
  zone_localization_failed:
    "Ring zone localization failed. Keep more of the finger base visible.",
  width_measurement_failed:
    "Diameter measurement failed. Retake with phone parallel to the table and steady focus.",
  sobel_edge_refinement_failed:
    "Edge refinement failed. Turn on flash or use stronger, even lighting.",
  width_unreasonable:
    "Measured diameter is out of range. Retake with the phone parallel to the table.",
  disagreement_with_contour:
    "Edge methods disagree too much. Retake with cleaner edges and more even lighting.",
  all_fingers_failed:
    "Could not measure any fingers. Ensure hand is flat with fingers spread and well-lit.",
  image_too_blurry:
    "Photo is blurry. Hold your phone steady or use a tripod.",
  image_underexposed:
    "Photo is too dark. Turn on flash or improve lighting.",
  image_overexposed:
    "Photo is too bright. Avoid direct sunlight or strong overhead light.",
  image_low_contrast:
    "Photo has low contrast. Use a different background color.",
  image_resolution_too_low:
    "Photo resolution is too low. Use the rear camera at full resolution.",
  image_quality_low_lighting:
    "Lighting is uneven. Turn on flash and shoot from directly above.",
};

const formatFailReasonStatus = (failReason) => {
  if (!failReason) {
    return "Measurement failed.";
  }

  if (failReason.startsWith("quality_score_low_")) {
    return "Low edge quality detected. Turn on flash and retake.";
  }

  if (failReason.startsWith("consistency_low_")) {
    return "Edge detection was inconsistent. Keep phone parallel to table and retry.";
  }

  const friendlyMessage = failReasonMessageMap[failReason];
  if (friendlyMessage) {
    return friendlyMessage;
  }

  return "Measurement failed. Please retake the photo and try again.";
};

const setStatus = (text, { error = false } = {}) => {
  statusText.textContent = text;
  statusText.classList.toggle("error", error);
};

const showImage = (imgEl, frameEl, url) => {
  if (!url) return;
  imgEl.src = url;
  frameEl.classList.add("show");
  frameEl.querySelector(".placeholder").style.display = "none";
};

const ringModelSelect = document.getElementById("ringModelSelect");

const RING_SIZE_TABLES = {
  gen: {6: 16.9, 7: 17.7, 8: 18.6, 9: 19.4, 10: 20.3, 11: 21.1, 12: 21.9, 13: 22.7},
  air: {6: 16.6, 7: 17.4, 8: 18.2, 9: 19.0, 10: 19.9, 11: 20.7, 12: 21.5, 13: 22.3},
};
const RING_MODEL_LABELS = { gen: "Gen1/Gen2", air: "Air" };

const kolEmailInput = document.getElementById("kolEmailInput");
// Loose RFC-ish check — `something@something.tld`. Email is the
// cross-table join key (see doc/v8/PRD.md), so validate before submit.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const buildMeasureSettings = () => {
  const fingerSelect = form.querySelector('[name="finger_index"]');
  const aiToggle = document.getElementById("aiExplainToggle");
  const mode = modeSelect ? modeSelect.value : "multi";
  const ringModel = ringModelSelect ? ringModelSelect.value : "gen";
  // AI explanation is off by default. Dev mode shows a checkbox the user
  // can opt into; non-dev mode has no UI control and therefore stays off.
  const aiOn = aiToggle && aiToggle.type === "checkbox" ? aiToggle.checked : false;
  return {
    finger_index: fingerSelect ? fingerSelect.value : "index",
    edge_method: "mask",
    mode: mode,
    ring_model: ringModel,
    ai_explain: aiOn ? "1" : "0",
    kol_email: kolEmailInput ? kolEmailInput.value.trim().toLowerCase() : "",
  };
};

const buildSizeRefTable = () => {
  const ringModel = ringModelSelect ? ringModelSelect.value : "gen";
  const sizeTable = RING_SIZE_TABLES[ringModel] || RING_SIZE_TABLES.gen;
  const modelLabel = RING_MODEL_LABELS[ringModel] || ringModel;
  const rows = Object.entries(sizeTable)
    .map(([size, mm]) => `<tr><td>${size}</td><td>${mm.toFixed(1)}</td></tr>`)
    .join("");
  return `
    <div class="size-ref-table">
      <h3 class="size-ref-title">Size Reference (${modelLabel})</h3>
      <table>
        <thead><tr><th>Size</th><th>Inner Diameter (mm)</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
};

const renderMultiResult = (result) => {
  if (!result || !result.per_finger) {
    overallSize.innerHTML = `<div class="size-hero"><span class="size-label">Measurement Failed</span></div>`;
    fingerBreakdown.innerHTML = "";
    return;
  }

  overallSize.innerHTML = "";

  // Per-finger cards: size + range + width
  const fingerNames = { index: "Index Finger", middle: "Middle Finger", ring: "Ring Finger" };
  const fingerColors = { index: "#00dddd", middle: "#3b82f6", ring: "#dd44dd" };
  let html = '<div class="finger-cards">';
  for (const [fn, label] of Object.entries(fingerNames)) {
    const pf = result.per_finger[fn];
    if (!pf) continue;
    const color = fingerColors[fn] || "#888";
    const ok = pf.status === "ok";
    const badge = fn === "index" ? `<span class="finger-badge">Recommended</span>` : "";
    html += `<div class="finger-card" style="border-top: 3px solid ${color};">
      ${badge}
      <div class="finger-name">${label}</div>`;
    if (ok) {
      const size = pf.best_match;
      const range = pf.range;
      html += `<div class="finger-size-label">Size</div>`;
      html += `<div class="finger-size">${size}</div>`;
      if (range) {
        html += `<div class="finger-range">Range: ${range[0]} – ${range[1]}</div>`;
      }
      html += `<div class="finger-width">Diameter: ${(pf.diameter_cm * 10).toFixed(1)} mm</div>`;
    } else {
      html += `<div class="finger-failed">Failed</div>
        <div class="finger-fail-reason">${pf.fail_reason || "unknown"}</div>`;
    }
    html += `</div>`;
  }
  html += "</div>";
  const evidenceText = window.SessionEvidence.text(result);
  if (evidenceText) {
    html += `<div class="finger-count">${evidenceText}</div>`;
  }
  html += buildSizeRefTable();

  fingerBreakdown.innerHTML = html;
};

const renderSingleResult = (result) => {
  const rs = result && result.ring_size;
  if (!rs) {
    overallSize.innerHTML = `<div class="size-hero"><span class="size-label">No ring size available</span></div>`;
    fingerBreakdown.innerHTML = "";
    return;
  }

  const modelLabel = RING_MODEL_LABELS[rs.ring_model] || rs.ring_model || "";
  overallSize.innerHTML = `
    <div class="size-hero">
      <span class="size-label">Recommended Size${modelLabel ? ` (${modelLabel})` : ""}</span>
      <span class="size-number">${rs.best_match}</span>
      <span class="size-range">Range: ${rs.range_min} – ${rs.range_max}</span>
    </div>`;

  const diamMm = result.finger_outer_diameter_cm ? (result.finger_outer_diameter_cm * 10).toFixed(1) : "—";
  const fingerSelect = form.querySelector('[name="finger_index"]');
  const fingerName = fingerSelect ? fingerSelect.value : "finger";
  const capitalName = fingerName.charAt(0).toUpperCase() + fingerName.slice(1);
  const evidenceText = window.SessionEvidence.text(result);
  const evidence = evidenceText
    ? `<div class="finger-count">${evidenceText}</div>`
    : "";
  fingerBreakdown.innerHTML = `<div class="finger-cards">
    <div class="finger-card" style="border-top: 3px solid #00dddd;">
      <div class="finger-name">${capitalName}</div>
      <div class="finger-size-label">Size</div>
      <div class="finger-size">${rs.best_match}</div>
      <div class="finger-range">${rs.range_min} – ${rs.range_max}</div>
      <div class="finger-width">${diamMm} mm</div>
    </div>
  </div>${evidence}` + buildSizeRefTable();
};

const runMeasurement = async (endpoint, formData, inputUrlFallback = "", sessionContext = null) => {
  const startedAt = Date.now();
  const renderElapsed = () => {
    const secs = Math.floor((Date.now() - startedAt) / 1000);
    setStatus(`Measuring… Done in under a minute. (${secs}s)`);
    overallSize.innerHTML = `<div class="size-hero"><span class="size-label">Measuring… ${secs}s</span></div>`;
  };
  renderElapsed();
  jsonOutput.textContent = '{\n  "status": "processing"\n}';
  fingerBreakdown.innerHTML = "";
  // Clear feedback state at the top so every code path — HTTP error,
  // network error, fail_reason result — starts from a hidden panel and
  // an empty run_id. Otherwise a successful run that's followed by an
  // HTTP / network error would leave the panel visible with the prior
  // run_id, and any feedback would attach to the wrong row.
  lastRunId = "";
  if (feedbackSection) feedbackSection.hidden = true;
  const timerId = setInterval(renderElapsed, 1000);

  try {
    const response = await fetch(endpoint, {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      setStatus(error.error || "Measurement failed", { error: true });
      return;
    }

    const data = await response.json();
    if (sessionContext && window.MeasurementSession) {
      window.MeasurementSession.accept(sessionContext, data);
    }
    lastRunId = data.run_id || "";
    if (feedbackSection) {
      if (data.success && lastRunId) {
        feedbackSection.hidden = false;
        resetFeedbackForm();
      } else {
        feedbackSection.hidden = true;
      }
    }
    jsonOutput.textContent = JSON.stringify(data.result, null, 2);
    jsonLink.href = data.result_json_url || "#";

    showImage(inputPreview, inputFrame, data.input_image_url || inputUrlFallback);
    showImage(debugPreview, debugFrame, data.result_image_url);

    const recommendation = data.session_recommendation || data.result;
    if (data.mode === "multi") {
      renderMultiResult(recommendation);
    } else {
      renderSingleResult(recommendation);
    }

    if (data.success) {
      setStatus("Measurement complete. (Tip: Turning on the camera flash improves accuracy.)");
    } else {
      const failReason = data?.result?.fail_reason;
      setStatus(formatFailReasonStatus(failReason), { error: true });
    }
  } catch (error) {
    setStatus("Network error. Please retry.", { error: true });
  } finally {
    clearInterval(timerId);
  }
};

imageInput.addEventListener("change", () => {
  const file = imageInput.files[0];
  if (!file) {
    setStatus("Sample image loaded. Click Start Measurement or upload your own photo.");
    if (defaultSampleUrl) {
      showImage(inputPreview, inputFrame, defaultSampleUrl);
    }
    return;
  }
  const url = URL.createObjectURL(file);
  showImage(inputPreview, inputFrame, url);
  setStatus("Image ready. Click to start measurement.");
});

// Mode toggle: show/hide finger selector
if (modeSelect) {
  const updateFingerVisibility = () => {
    if (fingerSelectGroup) {
      fingerSelectGroup.style.display = modeSelect.value === "multi" ? "none" : "";
    }
  };
  modeSelect.addEventListener("change", updateFingerVisibility);
  updateFingerVisibility();
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const settings = buildMeasureSettings();
  if (!EMAIL_RE.test(settings.kol_email)) {
    setStatus("Please enter a valid email before measuring.", { error: true });
    kolEmailInput.focus();
    return;
  }
  const formData = new FormData();
  formData.append("finger_index", settings.finger_index);
  formData.append("edge_method", settings.edge_method);
  formData.append("mode", settings.mode);
  formData.append("ring_model", settings.ring_model);
  formData.append("ai_explain", settings.ai_explain);
  formData.append("kol_email", settings.kol_email);

  const file = imageInput.files[0];
  const sessionContext = {
    kol_email: settings.kol_email,
    ring_model: settings.ring_model,
    mode: settings.mode,
    finger_index: settings.finger_index,
    source: file ? "photo" : "sample",
  };
  const measurementSession = window.MeasurementSession.prepare(sessionContext);
  formData.append("session_id", measurementSession.session_id);
  if (measurementSession.session_state) {
    formData.append("session_state", JSON.stringify(measurementSession.session_state));
  }

  if (file) {
    formData.append("image", file);
    await runMeasurement("/api/measure", formData, "", sessionContext);
    return;
  }

  await runMeasurement("/api/measure-default", formData, defaultSampleUrl, sessionContext);
});

if (defaultSampleUrl) {
  showImage(inputPreview, inputFrame, defaultSampleUrl);
  setStatus("Sample image loaded. Click Start Measurement or upload your own photo.");
}

function paintStars() {
  feedbackStarButtons.forEach((btn) => {
    const v = Number(btn.dataset.value);
    const filled = v <= feedbackRating;
    btn.classList.toggle("star-filled", filled);
    btn.setAttribute("aria-checked", v === feedbackRating ? "true" : "false");
  });
}

function updateFeedbackSubmitEnabled() {
  if (!feedbackSubmit) return;
  const hasMessage = (feedbackMessage.value || "").trim().length > 0;
  feedbackSubmit.disabled = !(feedbackRating || hasMessage);
}

function resetFeedbackForm() {
  feedbackRating = 0;
  feedbackMessage.value = "";
  feedbackStatus.textContent = "";
  feedbackStatus.className = "feedback-status";
  paintStars();
  updateFeedbackSubmitEnabled();
}

if (feedbackForm) {
  updateFeedbackSubmitEnabled();
  feedbackMessage.addEventListener("input", updateFeedbackSubmitEnabled);
  feedbackStarButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      // Set-only (no toggle-to-clear) — the previous "click same star
      // to clear" behavior was undiscoverable and made it easy to wipe
      // a rating with a stray double-tap. Users can change the rating
      // by clicking a different star.
      feedbackRating = Number(btn.dataset.value);
      paintStars();
      updateFeedbackSubmitEnabled();
    });
  });

  feedbackForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = (feedbackMessage.value || "").trim();
    if (!feedbackRating && !message) {
      feedbackStatus.textContent = "Pick a rating or write a comment.";
      feedbackStatus.className = "feedback-status feedback-status-error";
      return;
    }
    if (!lastRunId) {
      feedbackStatus.textContent = "No measurement to attach this to yet.";
      feedbackStatus.className = "feedback-status feedback-status-error";
      return;
    }
    feedbackSubmit.disabled = true;
    feedbackStatus.textContent = "Sending…";
    feedbackStatus.className = "feedback-status";
    try {
      const resp = await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          run_id: lastRunId,
          rating: feedbackRating || undefined,
          message,
        }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${resp.status}`);
      }
      feedbackStatus.textContent = "Thanks — sent.";
      feedbackStatus.className = "feedback-status feedback-status-ok";
      feedbackMessage.value = "";
      feedbackRating = 0;
      paintStars();
    } catch (err) {
      feedbackStatus.textContent = `Couldn't send: ${err.message}`;
      feedbackStatus.className = "feedback-status feedback-status-error";
    } finally {
      updateFeedbackSubmitEnabled();
    }
  });
}
