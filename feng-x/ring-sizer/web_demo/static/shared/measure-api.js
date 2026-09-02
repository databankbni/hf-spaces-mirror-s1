// POST a captured frame to /api/measure. Returns the parsed response
// JSON unchanged so callers can render the same shape the desktop UI
// already understands.
//
// Currently consumed only by the mobile capture step. Phase 4 of the
// v6 plan migrates the desktop submit handler to this helper too;
// until then `web_demo/static/app.js` keeps its inline fetch call.

const DEFAULTS = {
  finger_index: "index",
  mode: "multi",
  edge_method: "mask",
  ring_model: "gen",
  // Server reads "1" as truthy; anything else (including "on", "0",
  // "") is treated as off. Mobile flow does not surface the AI toggle,
  // so default off — opt-in lives on the desktop dev page.
  ai_explain: "0",
  capture_method: "camera",
};

export async function postMeasure({
  blob,
  kol_email,
  gate_telemetry = null,
  session_id = null,
  session_state = null,
  ...overrides
} = {}) {
  if (!blob) throw new Error("postMeasure: blob is required");
  if (!kol_email) throw new Error("postMeasure: kol_email is required");

  const settings = { ...DEFAULTS, ...overrides };
  const formData = new FormData();
  formData.append("image", blob, "capture.jpg");
  formData.append("kol_email", kol_email);
  formData.append("finger_index", settings.finger_index);
  formData.append("mode", settings.mode);
  formData.append("edge_method", settings.edge_method);
  formData.append("ring_model", settings.ring_model);
  formData.append("ai_explain", settings.ai_explain);
  formData.append("capture_method", settings.capture_method);
  if (session_id) {
    formData.append("session_id", session_id);
  }
  if (session_state) {
    formData.append("session_state", JSON.stringify(session_state));
  }
  if (gate_telemetry) {
    formData.append("gate_telemetry", JSON.stringify(gate_telemetry));
  }

  const response = await fetch("/api/measure", {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(`Measurement request failed (${response.status}): ${text.slice(0, 120)}`);
  }
  return response.json();
}
