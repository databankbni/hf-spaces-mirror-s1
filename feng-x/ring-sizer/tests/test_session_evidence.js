const assert = require("node:assert/strict");
const fs = require("node:fs");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(
  "web_demo/static/shared/session-evidence.js",
  "utf8",
);

function loadHelper() {
  const window = {};
  vm.runInNewContext(source, { window, Number, Object, String });
  return window.SessionEvidence;
}

test("formats singular left-hand evidence and guidance", () => {
  const helper = loadHelper();
  assert.equal(
    helper.text({ successful_shots: 1, handedness: "Left" }),
    "Based on 1 measurement of your left hand. (For best reliability, take at least 3 measurements using the same hand.)",
  );
});

test("uses the session shot count and identifies the right hand", () => {
  const helper = loadHelper();
  assert.equal(
    helper.text({ successful_shots: 3, handedness: "Right" }),
    "Based on 3 measurements of your right hand. (For best reliability, take at least 3 measurements using the same hand.)",
  );
});

test("falls back to per-finger counts without inventing a hand", () => {
  const helper = loadHelper();
  assert.equal(helper.text({ per_finger: { index: { sample_count: 2 } } }),
    "Based on 2 measurements. (For best reliability, take at least 3 measurements using the same hand.)");
  assert.equal(helper.text({ per_finger: {} }), "");
});
