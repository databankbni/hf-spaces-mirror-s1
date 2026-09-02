"use strict";

const EVIDENCE_URL = "dataset/data/evidence.jsonl";
const CONTEXT_URL = "dataset/data/published-piqa-context.jsonl";
const RELEASE_LOCK_URL = "dataset/release-lock.json";
const EXPECTED_EVIDENCE_SHA256 = "05b40085981b4c31dc49b15817fffc2192b782cc8d82bc75f8f33bd0c4349b26";
const EXPECTED_CONTEXT_SHA256 = "f3bb8583e6983096d2b078ed567864bac4a539da627b953bd6370d9a081bd7fc";
const EXPECTED_RELEASE_LOCK_SHA256 = "1101f5c9f8e8f3559e84d69e5b2208c433a9abc2e80582f7b14108e22f434a02";
const EXPECTED_EVIDENCE_SCHEMA = "pythia-paths/trajectory-evidence/0.2";
const EXPECTED_CONTEXT_SCHEMA = "pythia-paths/published-piqa-context/0.1";
const EXPECTED_LOCK_SCHEMA = "pythia-paths/release-lock/0.2";
const EXPECTED_REPO = "EleutherAI/pythia-70m-deduped";
const PINNED_EVAL_COMMIT = "a19eecb807ec2c79a39ebf18108816e6ffffc1d5";
const TOKEN_SOURCE_COMMIT = "e93a9faa9c77e5d09219f6c868bfc7a1bd65593c";
const DETAILED_STEPS = [0, 1000, 73000, 143000];
const CONTEXT_STEPS = [
  0, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1000, 3000,
  13000, 23000, 33000, 43000, 53000, 63000, 73000, 83000,
  93000, 103000, 113000, 123000, 133000, 143000
];
const COMMIT_PATTERN = /^[0-9a-f]{40}$/;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const SOURCE_PATH_PATTERN = /^evals\/pythia-v1\/pythia-70m-deduped\/zero-shot\/70m-deduped_step[0-9]+\.json$/;
const SVG_NS = "http://www.w3.org/2000/svg";

const view = document.querySelector("#evidence-view");
const failure = document.querySelector("#load-failure");
const failureMessage = document.querySelector("#load-failure-message");
const chart = document.querySelector("#trajectory-chart");
const observationRow = document.querySelector("#observation-row");
const contextTableBody = document.querySelector("#context-table-body");
const snapshotStatus = document.querySelector("#snapshot-status");
const emptyInspection = document.querySelector("#inspection-empty");
const inspectionDetail = document.querySelector("#inspection-detail");

let evidence = [];
let reportContext = [];

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function assertSame(actual, expected, label) {
  assert(Object.is(actual, expected), `${label} does not match the reviewed release lock.`);
}

async function sha256Hex(buffer) {
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function parseJsonLines(buffer, label) {
  const decoded = new TextDecoder("utf-8", { fatal: true }).decode(buffer).trim();
  assert(decoded.length > 0, `${label} is empty.`);
  return decoded.split("\n").map((line) => JSON.parse(line));
}

async function fetchReviewedFile(url, expectedDigest, label) {
  const response = await fetch(url, { cache: "no-store", credentials: "omit" });
  assert(response.ok, `${label} request failed with status ${response.status}.`);
  const buffer = await response.arrayBuffer();
  const digest = await sha256Hex(buffer);
  assert(digest === expectedDigest, `${label} digest changed; manual review is required before display.`);
  return { buffer, digest };
}

function validateEvidenceRows(rows) {
  assert(Array.isArray(rows) && rows.length === 4, "Expected exactly four detailed observation receipts.");

  const ids = new Set();
  const steps = [];
  for (const row of rows) {
    assert(row && row.schema === EXPECTED_EVIDENCE_SCHEMA, "Unexpected evidence schema.");
    assert(typeof row.evidence_id === "string" && !ids.has(row.evidence_id), "Evidence IDs must be unique.");
    ids.add(row.evidence_id);

    const subject = row.subject;
    assert(subject.repo_id === EXPECTED_REPO, "Unexpected model repository.");
    assert(/^step[0-9]+$/.test(subject.declared_ref), "A checkpoint ref is malformed.");
    assert(subject.declared_ref === `step${subject.step}`, "Step and declared ref disagree.");
    assert(row.evidence_id === `pythia-70m-deduped:${subject.declared_ref}:piqa:acc_norm`, "Evidence ID and subject disagree.");
    assert(COMMIT_PATTERN.test(subject.observed_branch_target_commit), "An observed branch target is not pinned to a full commit.");
    assert(Number.isFinite(Date.parse(row.source_reviewed_at)), "Source review time is malformed.");
    assert(Number.isFinite(Date.parse(subject.branch_target_observed_at)), "Branch-target observation time is malformed.");
    assert(subject.tokens_seen.status === "derived", "Tokens seen must be labelled derived.");
    assert(subject.tokens_seen.method === "step * 2097152", "Unexpected token derivation.");
    assert(subject.tokens_seen.source_repo === EXPECTED_REPO, "Token derivation source repository changed.");
    assert(subject.tokens_seen.source_commit === TOKEN_SOURCE_COMMIT, "Token derivation source commit changed.");
    assert(subject.tokens_seen.source_path === "README.md", "Token derivation source path changed.");
    assert(subject.tokens_seen.value === subject.step * 2097152, "Derived token count does not match its rule.");
    steps.push(subject.step);

    const artifact = row.artifact;
    assert(artifact.path === "model.safetensors", "Unexpected artifact path.");
    assert(SHA256_PATTERN.test(artifact.reported_lfs_oid), "Reported artifact LFS object ID is malformed.");
    assert(artifact.retrieval_status === "metadata_only" && artifact.execution_status === "not_run", "Artifact handling exceeds the reviewed metadata-only scope.");
    assert(artifact.relationship_to_evaluation === "not_proven", "Observed artifact metadata cannot silently become the evaluated artifact.");

    const metric = row.metric_observation;
    assert(metric.task === "piqa" && metric.metric === "acc_norm", "Unexpected metric.");
    assert(Number.isFinite(metric.value) && Number.isFinite(metric.stderr), "Metric values must be finite.");
    assert(metric.value >= 0 && metric.value <= 1 && metric.stderr >= 0, "Metric value is out of range.");
    assert(metric.source_commit === PINNED_EVAL_COMMIT, "Evaluation source is not the reviewed commit.");
    assert(COMMIT_PATTERN.test(metric.source_blob_sha1), "Evaluation blob digest is malformed.");
    assert(SOURCE_PATH_PATTERN.test(metric.source_path), "Evaluation source path is outside the reviewed tree.");
    assert(metric.source_path.endsWith(`_${subject.declared_ref}.json`), "Evaluation path and declared ref disagree.");
    assert(metric.reported_run_config.model_args.split(",").includes(`revision=${subject.declared_ref}`), "Reported model arguments and declared ref disagree.");
    assert(metric.comparison_status === "not_proven", "Published reports cannot silently become a proven comparison.");
    assert(metric.evaluated_model_commit === null && metric.evaluated_artifact_digest === null, "The upstream evaluation did not report an evaluated artifact identity.");
    assert(metric.metric_to_observed_branch_artifact_binding === "not_proven", "Metric-to-observed-artifact binding is not proven.");

    const selection = row.selection;
    assert(selection.model_checkpoint_frame_count === 154, "Model checkpoint frame changed.");
    assert(selection.published_evaluation_report_frame_count === 27, "Published evaluation-report frame changed.");
    assert(selection.visualized_report_count === 27 && selection.visualization_scope === "all-reports-in-pinned-directory", "Visualization no longer covers all reports in the pinned directory.");
    assert(selection.detailed_receipt_steps.join(",") === DETAILED_STEPS.join(","), "Detailed receipt steps changed.");
    assert(selection.published_report_without_detailed_receipt_count === 23, "Detailed receipt omission count changed.");
    assert(selection.checkpoint_without_published_report_count === 127, "Unreported checkpoint count changed.");
    assert(selection.detail_selection_method === "illustrative-hand-selection", "Detail selection method must remain explicit.");
    assert(selection.detail_selected_before_outcomes_seen === false, "Detailed receipts were selected after outcomes were seen.");
    assert(selection.detail_representativeness === "not_claimed", "The detail subset cannot claim representativeness.");
    assert(selection.task_sampling_frame === "87-common-reported-tasks", "Task sampling frame changed.");
    assert(selection.included_task_metric === "piqa.acc_norm" && selection.omitted_task_count === 86, "Task selection receipt changed.");
    assert(selection.task_selected_before_outcomes_seen === false, "The task metric was selected after outcomes were available.");
    assert(row.authority.carried_by_this_record === false, "Evidence records cannot carry action authority.");
    assert(row.authority.established_by_this_view === false, "This view cannot establish action authority.");
    assert(row.authority.external_authority_status === "not_checked", "External authority is outside this view's evidence.");
    assert(row.unknowns.resume_replay_equivalence === undefined, "Replay status belongs in claims, not an open unknown list.");
    assert(row.claims.resume_replay_equivalence === "not_tested", "Exact replay equivalence must remain untested.");
  }

  assert(steps.join(",") === DETAILED_STEPS.join(","), "The detailed receipt grid changed.");
}

function validateContextRows(rows) {
  assert(Array.isArray(rows) && rows.length === 27, "Expected all 27 reports from the pinned directory.");
  assert(rows.map((row) => row.step).join(",") === CONTEXT_STEPS.join(","), "Published report context changed.");

  const ids = new Set();
  for (const row of rows) {
    assert(row && row.schema === EXPECTED_CONTEXT_SCHEMA, "Unexpected report-context schema.");
    assert(row.declared_ref === `step${row.step}`, "Context step and ref disagree.");
    assert(row.context_id === `pythia-70m-deduped:${row.declared_ref}:piqa:acc_norm:published-report-context`, "Context ID and ref disagree.");
    assert(!ids.has(row.context_id), "Context IDs must be unique.");
    ids.add(row.context_id);
    assert(Number.isFinite(Date.parse(row.source_reviewed_at)), "Context review time is malformed.");
    assert(row.tokens_seen_status === "derived" && row.tokens_seen_method === "step * 2097152", "Context tokens must remain explicitly derived.");
    assert(row.tokens_seen === row.step * 2097152, "Context token count does not match its rule.");
    assert(row.task === "piqa" && row.metric === "acc_norm", "Unexpected context metric.");
    assert(Number.isFinite(row.value) && row.value >= 0 && row.value <= 1, "Context metric is out of range.");
    assert(Number.isFinite(row.stderr) && row.stderr >= 0, "Context standard error is out of range.");
    assert(row.source_repo === "EleutherAI/pythia" && row.source_commit === PINNED_EVAL_COMMIT, "Context source changed.");
    assert(SOURCE_PATH_PATTERN.test(row.source_path) && row.source_path.endsWith(`_${row.declared_ref}.json`), "Context source path and ref disagree.");
    assert(COMMIT_PATTERN.test(row.source_blob_sha1), "Context Git blob digest is malformed.");
    assert(row.evaluated_model_commit === null && row.evaluated_artifact_digest === null, "Context cannot invent evaluated artifact identity.");
    assert(row.metric_to_model_artifact_binding === "not_proven" && row.comparison_status === "not_proven", "Context cannot promote binding or comparability.");
    assert(row.detailed_receipt_in_this_release === DETAILED_STEPS.includes(row.step), "Context detail flag changed.");
    assert(row.carried_action_authority === false, "Context records cannot carry action authority.");
  }
}

function validateReleaseLock(lock, files) {
  assert(lock && lock.schema === EXPECTED_LOCK_SCHEMA, "Unexpected release-lock schema.");
  assert(lock.evidence_bundle.path === "data/evidence.jsonl", "Release-lock evidence path changed.");
  assertSame(lock.evidence_bundle.sha256, files.evidenceDigest, "Evidence digest");
  assertSame(lock.evidence_bundle.bytes, files.evidenceBytes, "Evidence byte count");
  assertSame(lock.evidence_bundle.records, evidence.length, "Evidence record count");
  assert(lock.context_bundle.path === "data/published-piqa-context.jsonl", "Release-lock context path changed.");
  assertSame(lock.context_bundle.sha256, files.contextDigest, "Context digest");
  assertSame(lock.context_bundle.bytes, files.contextBytes, "Context byte count");
  assertSame(lock.context_bundle.records, reportContext.length, "Context record count");

  const lockById = new Map(lock.records.map((record) => [record.evidence_id, record]));
  assert(lockById.size === evidence.length, "Release-lock record set changed.");
  for (const row of evidence) {
    const expected = lockById.get(row.evidence_id);
    assert(expected, "A detailed evidence row is absent from the release lock.");
    assertSame(expected.declared_ref, row.subject.declared_ref, "Declared ref");
    assertSame(expected.step, row.subject.step, "Checkpoint step");
    assertSame(expected.observed_branch_target_commit, row.subject.observed_branch_target_commit, "Observed branch target");
    assertSame(expected.reported_artifact_bytes, row.artifact.bytes, "Reported artifact byte count");
    assertSame(expected.reported_lfs_oid, row.artifact.reported_lfs_oid, "Reported LFS object ID");
    assertSame(expected.evaluation_source_path, row.metric_observation.source_path, "Evaluation path");
    assertSame(expected.evaluation_blob_sha1, row.metric_observation.source_blob_sha1, "Evaluation Git blob");
    assertSame(expected.reported_model_args, row.metric_observation.reported_run_config.model_args, "Reported model arguments");
    assertSame(expected.reported_batch_size, row.metric_observation.reported_run_config.batch_size, "Reported batch size");
    assertSame(expected.reported_device, row.metric_observation.reported_run_config.device, "Reported device");
    assertSame(expected.reported_value, row.metric_observation.value, "Reported metric value");
    assertSame(expected.reported_stderr, row.metric_observation.stderr, "Reported standard error");
    assertSame(row.source_reviewed_at, lock.source_reviewed_at, "Source review time");
    assertSame(row.subject.branch_target_observed_at, lock.source_reviewed_at, "Branch-target observation time");
  }

  const shared = lock.shared;
  assert(shared.evaluation_source_repo === "EleutherAI/pythia" && shared.evaluation_source_commit === PINNED_EVAL_COMMIT, "Locked evaluation source changed.");
  assert(shared.training_source_repo === "EleutherAI/pythia" && shared.training_source_commit === PINNED_EVAL_COMMIT, "Locked training source changed.");
  assert(shared.training_config_path === "models/70M/pythia-70m-deduped.yml", "Locked training config path changed.");
  assert(shared.training_config_blob_sha1 === "1a447e6871469a39b66761b022e435d860b2cabe", "Locked training config blob changed.");
  assert(shared.token_derivation_source_repo === EXPECTED_REPO && shared.token_derivation_source_commit === TOKEN_SOURCE_COMMIT && shared.token_derivation_source_path === "README.md", "Locked token derivation source changed.");
  assert(shared.token_derivation_method === "step * 2097152", "Locked token derivation method changed.");
  assert(shared.evaluated_model_commit === null && shared.evaluated_artifact_digest === null, "Release lock cannot invent evaluated artifact identity.");
  assert(shared.metric_to_observed_branch_artifact_binding === "not_proven", "Release lock cannot promote artifact binding.");

  for (const row of evidence) {
    assertSame(row.training_source.repo, shared.training_source_repo, "Training source repository");
    assertSame(row.training_source.commit, shared.training_source_commit, "Training source commit");
    assertSame(row.training_source.config_path, shared.training_config_path, "Training config path");
    assertSame(row.training_source.config_blob_sha1, shared.training_config_blob_sha1, "Training config Git blob");
  }

  const selection = lock.selection;
  assert(selection.model_checkpoint_frame_count === 154 && selection.published_evaluation_report_frame_count === 27, "Locked report frame changed.");
  assert(selection.visualized_report_count === 27 && selection.visualization_scope === "all-reports-in-pinned-directory", "Locked visualization scope changed.");
  assert(selection.detailed_receipt_steps.join(",") === DETAILED_STEPS.join(","), "Locked detailed receipt steps changed.");
  assert(selection.published_report_without_detailed_receipt_count === 23 && selection.checkpoint_without_published_report_count === 127, "Locked missing-report counts changed.");
  assert(selection.task_sampling_frame === "87-common-reported-tasks" && selection.included_task_metric === "piqa.acc_norm" && selection.omitted_task_count === 86, "Locked task selection changed.");
  assert(selection.task_selected_before_outcomes_seen === false, "Locked task selection timing changed.");

  const contextByStep = new Map(reportContext.map((row) => [row.step, row]));
  for (const row of evidence) {
    const context = contextByStep.get(row.subject.step);
    assert(context && context.detailed_receipt_in_this_release, "A detailed receipt is missing from published-report context.");
    assertSame(context.tokens_seen, row.subject.tokens_seen.value, "Context token count");
    assertSame(context.value, row.metric_observation.value, "Context metric value");
    assertSame(context.stderr, row.metric_observation.stderr, "Context standard error");
    assertSame(context.source_path, row.metric_observation.source_path, "Context evaluation path");
    assertSame(context.source_blob_sha1, row.metric_observation.source_blob_sha1, "Context evaluation Git blob");
  }
  assert(reportContext.every((row) => row.source_reviewed_at === lock.source_reviewed_at), "Context review times and release lock disagree.");
  assert(lock.authentication.publisher_authenticated === false && lock.authentication.provenance_authenticated === false, "Release consistency cannot silently become publisher authentication.");
  assert(lock.authentication.purpose === "release consistency only", "Release-lock purpose changed.");
}

function svgElement(name, attributes = {}) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  return node;
}

function formatTokens(tokens) {
  if (tokens === 0) return "0";
  if (tokens < 1_000_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`;
  const billions = tokens / 1_000_000_000;
  return `${billions < 10 ? billions.toFixed(1) : billions.toFixed(0)}B`;
}

function formatPercent(value, digits = 2) {
  return `${(value * 100).toFixed(digits)}%`;
}

function formatReviewedAt(value) {
  const date = new Date(value);
  return `${new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(date)} ${new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC" }).format(date)} UTC`;
}

function shortHash(hash) {
  return `${hash.slice(0, 8)}…${hash.slice(-6)}`;
}

function addText(parent, text, x, y, className, anchor = "start") {
  const node = svgElement("text", { x, y, class: className, "text-anchor": anchor });
  node.textContent = text;
  parent.append(node);
  return node;
}

function appendErrorBar(parent, xPosition, value, stderr, yScale, className) {
  const errorTop = yScale(Math.min(1, value + stderr));
  const errorBottom = yScale(Math.max(0, value - stderr));
  parent.append(svgElement("line", { x1: xPosition, x2: xPosition, y1: errorTop, y2: errorBottom, class: className }));
  parent.append(svgElement("line", { x1: xPosition - 3, x2: xPosition + 3, y1: errorTop, y2: errorTop, class: className }));
  parent.append(svgElement("line", { x1: xPosition - 3, x2: xPosition + 3, y1: errorBottom, y2: errorBottom, class: className }));
}

function pointClass(row) {
  return row.detailed_receipt_in_this_release ? "chart-point detailed" : "chart-point context-only";
}

function evidenceIdForContext(row) {
  return row.detailed_receipt_in_this_release ? `pythia-70m-deduped:${row.declared_ref}:piqa:acc_norm` : "";
}

function renderChart() {
  chart.querySelectorAll(".generated").forEach((node) => node.remove());

  const width = 820;
  const height = 360;
  const margin = { top: 35, right: 34, bottom: 55, left: 62 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;
  const maxTokens = Math.max(...reportContext.map((row) => row.tokens_seen));
  const x = (tokens) => margin.left + (tokens / maxTokens) * innerWidth;
  const y = (value) => margin.top + (1 - value) * innerHeight;

  const group = svgElement("g", { class: "generated" });
  chart.append(group);

  for (let index = 0; index <= 4; index += 1) {
    const value = index / 4;
    const yPosition = y(value);
    group.append(svgElement("line", {
      x1: margin.left,
      x2: width - margin.right,
      y1: yPosition,
      y2: yPosition,
      class: "chart-grid"
    }));
    addText(group, formatPercent(value, 0), margin.left - 12, yPosition + 4, "chart-label", "end");
  }

  group.append(svgElement("line", {
    x1: margin.left,
    x2: width - margin.right,
    y1: height - margin.bottom,
    y2: height - margin.bottom,
    class: "chart-axis"
  }));

  const tokenTicks = [0, 100_000_000_000, 200_000_000_000, maxTokens];
  for (const tokens of tokenTicks) {
    const xPosition = x(tokens);
    group.append(svgElement("line", {
      x1: xPosition,
      x2: xPosition,
      y1: height - margin.bottom,
      y2: height - margin.bottom + 6,
      class: "chart-axis"
    }));
    addText(group, formatTokens(tokens), xPosition, height - margin.bottom + 24, "chart-label", "middle");
  }
  addText(group, "derived tokens seen", margin.left + innerWidth / 2, height - 12, "chart-label", "middle");

  for (const row of reportContext) {
    const xPosition = x(row.tokens_seen);
    const yPosition = y(row.value);
    appendErrorBar(group, xPosition, row.value, row.stderr, y, row.detailed_receipt_in_this_release ? "chart-error detailed" : "chart-error");
    const visiblePoint = svgElement("circle", {
      cx: xPosition,
      cy: yPosition,
      r: row.detailed_receipt_in_this_release ? 5 : 3,
      class: pointClass(row)
    });
    if (row.detailed_receipt_in_this_release) visiblePoint.dataset.evidenceId = evidenceIdForContext(row);
    group.append(visiblePoint);
  }

  const earlyRows = reportContext.filter((row) => row.step <= 1000);
  const inset = { x: 478, y: 43, width: 304, height: 92, left: 492, right: 768, top: 66, bottom: 119 };
  group.append(svgElement("rect", { x: inset.x, y: inset.y, width: inset.width, height: inset.height, rx: 10, class: "chart-inset" }));
  addText(group, "early inset · logarithmic step spacing", inset.x + 12, inset.y + 16, "chart-inset-label");
  group.append(svgElement("line", { x1: inset.left, x2: inset.right, y1: inset.bottom, y2: inset.bottom, class: "chart-inset-axis" }));
  const insetX = (step) => inset.left + (Math.log2(step + 1) / Math.log2(1001)) * (inset.right - inset.left);
  const insetY = (value) => inset.top + (1 - value) * (inset.bottom - inset.top);
  for (const row of earlyRows) {
    const xPosition = insetX(row.step);
    appendErrorBar(group, xPosition, row.value, row.stderr, insetY, "chart-error inset-error");
    const point = svgElement("circle", {
      cx: xPosition,
      cy: insetY(row.value),
      r: row.detailed_receipt_in_this_release ? 4 : 2.4,
      class: pointClass(row)
    });
    if (row.detailed_receipt_in_this_release) point.dataset.evidenceId = evidenceIdForContext(row);
    group.append(point);
  }
  addText(group, "step 0", inset.left, inset.bottom + 12, "chart-inset-tick");
  addText(group, "step 1,000", inset.right, inset.bottom + 12, "chart-inset-tick", "end");
}

function renderObservationButtons() {
  observationRow.replaceChildren();
  for (const row of evidence) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "observation-button";
    button.dataset.evidenceId = row.evidence_id;
    button.setAttribute("aria-pressed", "false");

    const step = document.createElement("small");
    step.textContent = `${row.subject.declared_ref} · ${formatTokens(row.subject.tokens_seen.value)} tokens`;
    const value = document.createElement("strong");
    value.textContent = `${formatPercent(row.metric_observation.value)} ± ${formatPercent(row.metric_observation.stderr)}`;
    button.append(step, value);
    button.addEventListener("click", () => selectEvidence(row.evidence_id));
    observationRow.append(button);
  }
}

function renderContextTable() {
  contextTableBody.replaceChildren();
  for (const row of reportContext) {
    const tableRow = document.createElement("tr");
    const stepCell = document.createElement("th");
    stepCell.scope = "row";
    stepCell.textContent = row.declared_ref;
    const tokensCell = document.createElement("td");
    tokensCell.textContent = formatTokens(row.tokens_seen);
    const valueCell = document.createElement("td");
    valueCell.textContent = `${formatPercent(row.value)} ± ${formatPercent(row.stderr)}`;
    const detailCell = document.createElement("td");
    detailCell.textContent = row.detailed_receipt_in_this_release ? "post-outcome detail receipt" : "source receipt only";
    const sourceCell = document.createElement("td");
    sourceCell.append(sourceLink("exact JSON ↗", `https://github.com/EleutherAI/pythia/blob/${PINNED_EVAL_COMMIT}/${row.source_path}`));
    tableRow.append(stepCell, tokensCell, valueCell, detailCell, sourceCell);
    contextTableBody.append(tableRow);
  }
}

function renderSnapshotStatus(lock) {
  snapshotStatus.textContent = `Source metadata observed ${formatReviewedAt(lock.source_reviewed_at)} · no automatic refresh · manually recheck before treating it as current`;
}

function receiptItem(label, value) {
  const wrapper = document.createElement("div");
  const term = document.createElement("dt");
  const description = document.createElement("dd");
  term.textContent = label;
  description.textContent = value;
  wrapper.append(term, description);
  return wrapper;
}

function sourceLink(label, href) {
  const link = document.createElement("a");
  link.href = href;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = label;
  return link;
}

function renderInspection(row) {
  inspectionDetail.replaceChildren();

  const head = document.createElement("div");
  head.className = "receipt-head";
  const headingWrap = document.createElement("div");
  const eyebrow = document.createElement("p");
  eyebrow.className = "eyebrow";
  eyebrow.textContent = "Post-outcome-selected detail receipt";
  const heading = document.createElement("h3");
  heading.textContent = row.subject.declared_ref;
  const subtitle = document.createElement("p");
  subtitle.textContent = `${formatTokens(row.subject.tokens_seen.value)} derived tokens seen`;
  subtitle.className = "scope-note";
  headingWrap.append(eyebrow, heading, subtitle);

  const value = document.createElement("span");
  value.className = "receipt-value";
  value.textContent = `${formatPercent(row.metric_observation.value)} ± ${formatPercent(row.metric_observation.stderr)}`;
  head.append(headingWrap, value);

  const grid = document.createElement("dl");
  grid.className = "receipt-grid";
  grid.append(
    receiptItem(`Branch target observed ${formatReviewedAt(row.subject.branch_target_observed_at)}`, shortHash(row.subject.observed_branch_target_commit)),
    receiptItem("Observed target's reported LFS object ID", shortHash(row.artifact.reported_lfs_oid)),
    receiptItem("Evaluation Git blob", shortHash(row.metric_observation.source_blob_sha1)),
    receiptItem("Evaluated model commit", "not reported upstream"),
    receiptItem("Metric ↔ observed artifact", row.metric_observation.metric_to_observed_branch_artifact_binding.replace(/_/g, " ")),
    receiptItem("Reported run", `batch ${row.metric_observation.reported_run_config.batch_size} · ${row.metric_observation.reported_run_config.device || "device not reported"}`),
    receiptItem("Comparability", row.metric_observation.comparison_status.replace(/_/g, " ")),
    receiptItem("External authority", row.authority.external_authority_status.replace(/_/g, " "))
  );

  const warning = document.createElement("p");
  warning.className = "receipt-warning";
  warning.textContent = "The evaluation named a mutable branch but no model commit or artifact digest. The historical metric is not proven to belong to the branch target observed in this frozen review snapshot.";

  const links = document.createElement("p");
  links.className = "receipt-links";
  const modelUrl = `https://huggingface.co/${EXPECTED_REPO}/tree/${row.subject.observed_branch_target_commit}`;
  const evaluationUrl = `https://github.com/EleutherAI/pythia/blob/${PINNED_EVAL_COMMIT}/${row.metric_observation.source_path}`;
  links.append(
    sourceLink("Observed branch target ↗", modelUrl),
    sourceLink("Exact evaluation file ↗", evaluationUrl)
  );

  inspectionDetail.append(head, grid, warning, links);
}

function selectEvidence(evidenceId) {
  const row = evidence.find((item) => item.evidence_id === evidenceId);
  if (!row) return;

  document.querySelectorAll(".observation-button").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.evidenceId === evidenceId));
  });
  document.querySelectorAll(".chart-point.detailed").forEach((point) => {
    point.classList.toggle("selected", point.dataset.evidenceId === evidenceId);
  });

  emptyInspection.hidden = true;
  inspectionDetail.hidden = false;
  renderInspection(row);
}

function showFailure(message) {
  view.hidden = true;
  failure.hidden = false;
  failureMessage.textContent = message;
}

async function loadEvidence() {
  try {
    assert(window.isSecureContext, "A secure context is required to verify release digests.");
    const [evidenceFile, contextFile, lockFile] = await Promise.all([
      fetchReviewedFile(EVIDENCE_URL, EXPECTED_EVIDENCE_SHA256, "Detailed evidence"),
      fetchReviewedFile(CONTEXT_URL, EXPECTED_CONTEXT_SHA256, "Published-report context"),
      fetchReviewedFile(RELEASE_LOCK_URL, EXPECTED_RELEASE_LOCK_SHA256, "Release lock")
    ]);

    evidence = parseJsonLines(evidenceFile.buffer, "Detailed evidence");
    reportContext = parseJsonLines(contextFile.buffer, "Published-report context");
    const lock = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(lockFile.buffer));
    validateEvidenceRows(evidence);
    validateContextRows(reportContext);
    validateReleaseLock(lock, {
      evidenceDigest: evidenceFile.digest,
      evidenceBytes: evidenceFile.buffer.byteLength,
      contextDigest: contextFile.digest,
      contextBytes: contextFile.buffer.byteLength
    });

    renderSnapshotStatus(lock);
    renderChart();
    renderObservationButtons();
    renderContextTable();
    failure.hidden = true;
    view.hidden = false;
  } catch (error) {
    showFailure(error instanceof Error ? error.message : "The reviewed release failed closed.");
  }
}

loadEvidence();
