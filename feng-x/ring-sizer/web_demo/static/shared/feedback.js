// POST feedback (rating + comment) attached to a specific measurement
// run. The endpoint requires a run_id and either a rating or a message
// (or both). Returns { success, error? } — the server returns 200 even
// when persistence is offline so callers only need to handle network
// errors and 4xx validation failures.
export async function submitFeedback({ runId, rating, message }) {
  if (!runId) {
    return { success: false, error: "Missing run_id" };
  }
  const body = { run_id: runId };
  if (rating) body.rating = rating;
  if (message) body.message = message;
  const resp = await fetch("/api/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let data = null;
  try {
    data = await resp.json();
  } catch {
    /* ignore parse errors — fall back to status code */
  }
  if (!resp.ok) {
    return { success: false, error: (data && data.error) || `HTTP ${resp.status}` };
  }
  return { success: true };
}
