const assert = require("node:assert/strict");
const fs = require("node:fs");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(
  "web_demo/static/shared/measurement-session.js",
  "utf8",
);

function loadHelper() {
  const data = new Map();
  let idCounter = 0;
  const window = {
    crypto: { randomUUID: () => `00000000-0000-4000-8000-${String(++idCounter).padStart(12, "0")}` },
    sessionStorage: {
      getItem: (key) => data.has(key) ? data.get(key) : null,
      setItem: (key, value) => data.set(key, value),
    },
  };
  vm.runInNewContext(source, { window, Date, JSON, Math, Number, String });
  return window.MeasurementSession;
}

test("preserves returned state for an unchanged context", () => {
  const helper = loadHelper();
  const context = {
    kol_email: "User@Example.com ", ring_model: "gen", mode: "multi",
    finger_index: "index", source: "photo",
  };
  const first = helper.prepare(context);
  const state = { session_id: first.session_id, attempt_count: 1, shots: [] };
  helper.accept(context, { session_state: state });
  assert.deepEqual(helper.prepare(context).session_state, state);
});

test("rotates the session when measurement context changes", () => {
  const helper = loadHelper();
  const base = {
    kol_email: "user@example.com", ring_model: "gen", mode: "multi",
    finger_index: "index", source: "photo",
  };
  const first = helper.prepare(base);
  const second = helper.prepare({ ...base, ring_model: "air" });
  assert.notEqual(second.session_id, first.session_id);
  assert.equal(second.session_state, null);
});

