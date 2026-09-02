const assert = require("node:assert/strict");
const fs = require("node:fs");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(
  "web_demo/static/shared/admin-session.js",
  "utf8",
);

function loadHelper() {
  const window = {};
  vm.runInNewContext(source, { window, Array, Object, String });
  return window.AdminSession;
}

test("returns no summary for a legacy record", () => {
  assert.equal(loadHelper().summary({ session_recommendation: null }), null);
});

test("summarizes a complete session recommendation", () => {
  const summary = loadHelper().summary({
    session_id: "12345678-abcd-ef01-2345-6789abcdef01",
    session_attempt_index: 4,
    session_recommendation: {
      overall_best_size: 7,
      handedness: "Right",
      successful_shots: 3,
      per_finger: {
        index: { status: "ok", best_match: 7 },
        middle: { status: "ok", best_match: 8 },
        ring: { status: "ok", best_match: 6 },
      },
    },
  });

  assert.equal(summary.overallSize, 7);
  assert.equal(summary.handedness, "Right");
  assert.equal(summary.successfulShots, 3);
  assert.equal(summary.attemptIndex, 4);
  assert.equal(summary.shortSessionId, "12345678");
  assert.deepEqual({ ...summary.perFinger }, { index: 7, middle: 8, ring: 6 });
});

test("uses JSON fallbacks and omits unsuccessful fingers", () => {
  const summary = loadHelper().summary({
    session_recommendation: {
      session_id: "fallback-session",
      attempt_index: 2,
      overall_best_size: 8,
      per_finger: {
        index: { status: "ok", best_match: 8 },
        middle: { status: "failed", best_match: null },
      },
    },
  });

  assert.equal(summary.attemptIndex, 2);
  assert.equal(summary.shortSessionId, "fallback");
  assert.deepEqual({ ...summary.perFinger }, { index: 8 });
});
