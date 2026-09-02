// /feedback — post-shipment KOL fit-feedback form (v8).
//
// A single self-contained screen (no step framework — that's the /m
// capture coach's machinery and irrelevant here). Validates the
// required fields, POSTs multipart to /api/fit-feedback, and swaps the
// form for a thank-you + "measure now" CTA on success.
//
// Email is the cross-table join key (see doc/v8/PRD.md), so it is the
// one field validated for format; the rest are required-but-free.
//
// Validation errors render INLINE, directly under the offending field
// (not in one spot at the bottom): on mobile we focus the bad field, so
// the keyboard would hide a bottom-of-form message entirely.

// Loose RFC-ish check — `something@something.tld`. Mirrors the desktop /
// mobile measurement forms so a KOL who uses both sees the same rule.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const form = document.getElementById("feedbackForm");
const errorEl = document.getElementById("formError");
const submitBtn = document.getElementById("submitBtn");

const el = (id) => document.getElementById(id);
const val = (id) => (el(id).value || "").trim();

// Required selects/inputs and the human label used in the error message
// when one is left blank.
const REQUIRED = [
  ["receivedSize", "the ring size you received"],
  ["receivedModel", "the ring model"],
  ["bestFitFinger", "which finger fit best"],
  ["fitQuality", "how it fit"],
  ["hand", "which hand"],
];

// Every field that can produce a validation error, in DOM order.
const FIELD_IDS = ["kolName", "kolEmail", ...REQUIRED.map(([id]) => id)];

// Inject an inline error slot under each validatable field and clear it
// as soon as the user edits that field.
const errSlots = {};
for (const id of FIELD_IDS) {
  const input = el(id);
  const slot = document.createElement("small");
  slot.className = "field-error";
  slot.hidden = true;
  input.closest("label").appendChild(slot);
  errSlots[id] = slot;
  input.addEventListener(input.tagName === "SELECT" ? "change" : "input", () => {
    slot.hidden = true;
    input.removeAttribute("aria-invalid");
  });
}

function clearErrors() {
  errorEl.hidden = true;
  for (const id of FIELD_IDS) {
    errSlots[id].hidden = true;
    el(id).removeAttribute("aria-invalid");
  }
}

// Inline error on a specific field: show the message under it, focus it,
// and scroll it to mid-screen so the message clears the on-screen keyboard.
function showFieldError(id, msg) {
  const input = el(id);
  const slot = errSlots[id];
  slot.textContent = msg;
  slot.hidden = false;
  input.setAttribute("aria-invalid", "true");
  input.focus({ preventScroll: true });
  input.closest("label").scrollIntoView({ block: "center", behavior: "smooth" });
}

// Global error (network / server failures — not tied to one field).
function showFormError(msg) {
  errorEl.textContent = msg;
  errorEl.hidden = false;
}

// Returns [fieldId, message] for the first invalid field, or null.
function firstInvalid() {
  if (!val("kolName")) {
    return ["kolName", "Please enter your name."];
  }
  if (!EMAIL_RE.test(val("kolEmail").toLowerCase())) {
    return ["kolEmail", "Please enter a valid email."];
  }
  for (const [id, label] of REQUIRED) {
    if (!val(id)) return [id, `Please tell us ${label}.`];
  }
  return null;
}

function showSuccess() {
  document.getElementById("formView").hidden = true;
  document.getElementById("formFoot").hidden = true;
  document.getElementById("successView").hidden = false;
  window.scrollTo(0, 0);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearErrors();

  const invalid = firstInvalid();
  if (invalid) {
    showFieldError(invalid[0], invalid[1]);
    return;
  }

  const fd = new FormData();
  fd.append("kol_name", val("kolName"));
  fd.append("kol_email", val("kolEmail").toLowerCase());
  fd.append("received_size", val("receivedSize"));
  fd.append("received_model", val("receivedModel"));
  fd.append("best_fit_finger", val("bestFitFinger"));
  fd.append("fit_quality", val("fitQuality"));
  fd.append("hand", val("hand"));
  fd.append("notes", val("notes"));
  const photo = el("photo").files[0];
  if (photo) fd.append("photo", photo, photo.name);

  submitBtn.disabled = true;
  const originalLabel = submitBtn.textContent;
  submitBtn.textContent = "Submitting…";

  try {
    const resp = await fetch("/api/fit-feedback", { method: "POST", body: fd });
    const data = await resp.json().catch(() => ({}));
    if (resp.ok && data.success) {
      showSuccess();
      return;
    }
    showFormError(data.error || "Could not submit. Please try again.");
  } catch (err) {
    showFormError("Network error. Please check your connection and retry.");
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = originalLabel;
  }
});
