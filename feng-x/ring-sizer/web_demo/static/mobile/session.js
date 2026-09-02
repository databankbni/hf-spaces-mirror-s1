// Shared state that persists across step transitions.
//
// `goTo(name, data)` would force every step to re-thread the full
// payload to the next; with six steps and a back-nav that needs to
// remember what was already entered, an implicit session module is
// simpler. Lifecycle is bounded by the page (cleared on `reset()`,
// invoked by the result step's "Measure again" button to ensure the
// next run starts fresh).

export const session = {
  kolEmail: "",
  ringModel: "gen",
  // Either an uploaded File or a Blob captured from the camera step.
  imageBlob: null,
  // Object URL pointing at imageBlob — created by whichever step
  // produced the blob, revoked by reset() to avoid leaks.
  imageUrl: "",
  // Source of the blob, used by confirm.js to label the preview.
  imageSource: "", // "upload" | "camera"
  // Capture-coach telemetry snapshot. Forwarded to /api/measure with
  // the camera path; null for the upload path.
  gateTelemetry: null,
  // /api/measure response payload, populated by confirm.js before
  // navigating to the result step.
  result: null,
};

// Wipe just the photo + result — used by "Measure again" so the user
// keeps their entered email + ring model on the next capture without
// re-typing. A full reset isn't a separate function: a page refresh
// reloads this module and reinitializes `session` to the defaults.
export function resetForRetake() {
  if (session.imageUrl && session.imageUrl.startsWith("blob:")) {
    URL.revokeObjectURL(session.imageUrl);
  }
  session.imageBlob = null;
  session.imageUrl = "";
  session.imageSource = "";
  session.gateTelemetry = null;
  session.result = null;
}
