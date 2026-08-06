/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Copyright (C) 2026 Pavel Ondračka */

const state = {
  meta: null,
  data: null,
  shaderRoot: null,
  shaderNodes: [],
  shaderPaths: [],
  selectedShaders: new Set(),
  expandedShaderDirs: new Set(["shaders"]),
  hidden: new Set(),
  changeReports: new Map(),
  expandedChanges: new Set(),
  drag: null,
  tooltipHideTimer: null,
  loadSerial: 0,
  colors: [
    "#166b8f", "#9a5b00", "#3f7f3f", "#a63d40", "#594a9c",
    "#00706b", "#7c5a2b", "#536878", "#b35c7e", "#4d6f21",
  ],
};

const MIN_POINT_X_SPACING = 4;
const EDGE_MARKER_INSET = 5;
const MIN_ZOOM_PIXELS = 10;
const CLUSTER_X_SPACING = 9;
const CLUSTER_Y_SPACING = 10;
const MARKER_RADIUS = 3.5;
const CLUSTER_MARKER_MAX_RADIUS = 12;
const MARKER_FILL = "#62b7d9";
const CLUSTER_MARKER_FILL = "#166b8f";
const MAX_TOOLTIP_CLUSTER_COMMITS = 5;
const Y_AXIS_PIXEL_PADDING = 10;
const COMMIT_TICK_STEP = 5;
const MIN_COMMIT_LABEL_SPACING = 72;

const el = {
  statusLine: document.getElementById("statusLine"),
  targetControls: document.getElementById("targetControls"),
  statControls: document.getElementById("statControls"),
  stageControls: document.getElementById("stageControls"),
  granularityControl: document.getElementById("granularityControl"),
  fullRangeBtn: document.getElementById("fullRangeBtn"),
  fromInput: document.getElementById("fromInput"),
  toInput: document.getElementById("toInput"),
  shaderFilterInput: document.getElementById("shaderFilterInput"),
  shaderSelectionStatus: document.getElementById("shaderSelectionStatus"),
  shaderTree: document.getElementById("shaderTree"),
  chart: document.getElementById("chart"),
  tooltip: document.getElementById("tooltip"),
  loadingOverlay: document.getElementById("loadingOverlay"),
  rangeWarning: document.getElementById("rangeWarning"),
  legend: document.getElementById("legend"),
  changeList: document.getElementById("changeList"),
  changeCount: document.getElementById("changeCount"),
  reloadBtn: document.getElementById("reloadBtn"),
  resetBtn: document.getElementById("resetBtn"),
};

const chart = {
  ctx: el.chart.getContext("2d"),
  plot: null,
  points: [],
  width: 1,
  height: 1,
  xMin: 0,
  xMax: 1,
  yMin: 0,
  yMax: 1,
  percentBase: 1,
  displayXByCommit: new Map(),
  xMode: "time",
  commitItems: [],
  yLabel: "",
};

function api(path, params = {}) {
  const url = new URL(path, window.location.origin);
  for (const [key, value] of Object.entries(params)) {
    if (Array.isArray(value)) {
      if (value.length) url.searchParams.set(key, value.join(","));
    } else if (value !== "" && value != null) {
      url.searchParams.set(key, value);
    }
  }
  return fetch(url).then(async response => {
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || response.statusText);
    return data;
  });
}

function apiPost(path, payload = {}) {
  return fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }).then(async response => {
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || response.statusText);
    return data;
  });
}

function selectedChecks(container) {
  return [...container.querySelectorAll("input:checked")].map(input => input.value);
}

function selectedGranularity() {
  return el.granularityControl.querySelector("button.active").dataset.value;
}

function dateOnly(value) {
  return value ? value.slice(0, 10) : "";
}

function parseDate(value) {
  return new Date(value).getTime();
}

function parseDateEnd(value) {
  return parseDate(value) + 86400000 - 1;
}

function fmtDate(value) {
  return dateOnly(value);
}

function fmtNumber(value) {
  if (value == null || Number.isNaN(value)) return "";
  return Number(value).toLocaleString();
}

function fmtTarget(value) {
  return String(value || "").replace(/^r([345])xx$/, "R$1xx");
}

function fmtSeriesLabel(series) {
  if (!series) return "";
  return `${fmtTarget(series.target)} ${series.stat || ""}`.trim();
}

function defaultTarget(meta) {
  if (meta.targets.some(target => target.id === "r5xx")) return "r5xx";
  return meta.targets[meta.targets.length - 1]?.id || "";
}

function defaultStat(meta) {
  if (meta.stats.includes("instructions")) return "instructions";
  return meta.default_stats[0] || meta.stats[0] || "";
}

function setSingleSelection(container, value) {
  const inputs = [...container.querySelectorAll("input")];
  let found = false;
  for (const input of inputs) {
    input.checked = input.value === value;
    found ||= input.checked;
  }
  if (!found && inputs.length) inputs[0].checked = true;
}

function resetPrimarySelections() {
  setSingleSelection(el.targetControls, defaultTarget(state.meta));
  setSingleSelection(el.statControls, defaultStat(state.meta));
}

function setupControls(meta) {
  el.targetControls.innerHTML = "";
  const selectedTarget = defaultTarget(meta);
  for (const target of meta.targets) {
    const label = document.createElement("label");
    const checked = target.id === selectedTarget ? "checked" : "";
    label.innerHTML = `<input type="radio" name="target" value="${target.id}" ${checked}> ${fmtTarget(target.id)}`;
    label.title = target.gpu_id;
    el.targetControls.append(label);
  }

  el.statControls.innerHTML = "";
  const selectedStat = defaultStat(meta);
  for (const stat of meta.stats) {
    const label = document.createElement("label");
    const checked = stat === selectedStat ? "checked" : "";
    label.innerHTML = `<input type="radio" name="stat" value="${stat}" ${checked}> ${stat}`;
    el.statControls.append(label);
  }

  el.stageControls.innerHTML = "";
  for (const stage of meta.stages) {
    const label = document.createElement("label");
    label.innerHTML = `<input type="checkbox" value="${stage}" checked> ${stage}`;
    el.stageControls.append(label);
  }

  el.fromInput.value = dateOnly(meta.range.start_date);
  el.toInput.value = dateOnly(meta.range.end_date);

  const loadSeriesDebounced = debounce(loadSeries, 120);
  for (const input of [
    ...el.targetControls.querySelectorAll("input"),
    ...el.statControls.querySelectorAll("input"),
    ...el.stageControls.querySelectorAll("input"),
    el.fromInput,
    el.toInput,
  ]) {
    input.addEventListener("change", loadSeriesDebounced);
  }
  el.shaderFilterInput.addEventListener("input", debounce(renderShaderTree, 100));

  el.granularityControl.addEventListener("click", event => {
    const button = event.target.closest("button");
    if (!button) return;
    for (const b of el.granularityControl.querySelectorAll("button")) b.classList.remove("active");
    button.classList.add("active");
    loadSeries();
  });

  el.reloadBtn.addEventListener("click", loadSeries);
  el.resetBtn.addEventListener("click", () => {
    resetPrimarySelections();
    setFullRange();
    selectAllShaders();
    renderShaderTree();
    setGranularity("commit");
    loadSeries();
  });
  el.fullRangeBtn.addEventListener("click", () => {
    setFullRange();
    loadSeries();
  });
}

function setGranularity(value) {
  for (const b of el.granularityControl.querySelectorAll("button")) {
    b.classList.toggle("active", b.dataset.value === value);
  }
}

function setFullRange() {
  el.fromInput.value = dateOnly(state.meta.range.start_date);
  el.toInput.value = dateOnly(state.meta.range.end_date);
}

function queryParams() {
  const params = {
    targets: selectedChecks(el.targetControls),
    stats: selectedChecks(el.statControls),
    stages: selectedChecks(el.stageControls),
    aggregate: "sum",
    granularity: selectedGranularity(),
    from: el.fromInput.value,
    to: el.toInput.value,
  };
  if (state.shaderPaths.length && state.selectedShaders.size < state.shaderPaths.length) {
    params.shader_paths = [...state.selectedShaders].sort();
  }
  return params;
}

function makeDirNode(name, path) {
  return {
    type: "dir",
    name,
    path,
    childrenMap: new Map(),
    children: [],
    shaderCount: 0,
  };
}

function makeFileNode(name, path, app) {
  return {
    type: "file",
    name,
    path,
    app,
    shaderCount: 1,
  };
}

function buildShaderTree(shaders) {
  const root = makeDirNode("shaders", "shaders");
  const nodes = [root];
  const paths = [];
  for (const shader of shaders) {
    const fullPath = shader.path;
    paths.push(fullPath);
    let parts = fullPath.split("/").filter(Boolean);
    if (parts[0] === "shaders") parts = parts.slice(1);
    let dir = root;
    dir.shaderCount++;
    for (let i = 0; i < parts.length - 1; i++) {
      const name = parts[i];
      const path = `${dir.path}/${name}`;
      if (!dir.childrenMap.has(name)) {
        const child = makeDirNode(name, path);
        dir.childrenMap.set(name, child);
        nodes.push(child);
      }
      dir = dir.childrenMap.get(name);
      dir.shaderCount++;
    }
    const file = makeFileNode(parts[parts.length - 1] || fullPath, fullPath, shader.app);
    dir.children.push(file);
    nodes.push(file);
  }

  function finalize(node) {
    if (node.type !== "dir") return;
    const dirs = [...node.childrenMap.values()].sort((a, b) => a.name.localeCompare(b.name));
    const files = node.children.filter(child => child.type === "file").sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
    node.children = [...dirs, ...files];
    delete node.childrenMap;
    for (const child of node.children) finalize(child);
  }
  finalize(root);
  return { root, nodes, paths };
}

async function loadShaderTree() {
  const data = await api("/api/shader-tree");
  const tree = buildShaderTree(data.shaders);
  state.shaderRoot = tree.root;
  state.shaderNodes = tree.nodes;
  state.shaderPaths = tree.paths;
  selectAllShaders();
  renderShaderTree();
}

function selectAllShaders() {
  state.selectedShaders = new Set(state.shaderPaths);
}

function shaderNodeSelection(node) {
  if (node.type === "file") {
    return state.selectedShaders.has(node.path) ? "checked" : "empty";
  }
  let checked = 0;
  let total = 0;
  forEachShader(node, file => {
    total++;
    if (state.selectedShaders.has(file.path)) checked++;
  });
  if (checked === 0) return "empty";
  if (checked === total) return "checked";
  return "mixed";
}

function setShaderNodeSelected(node, selected) {
  forEachShader(node, file => {
    if (selected) state.selectedShaders.add(file.path);
    else state.selectedShaders.delete(file.path);
  });
}

function forEachShader(node, fn) {
  if (node.type === "file") {
    fn(node);
    return;
  }
  for (const child of node.children) forEachShader(child, fn);
}

function shaderNodeMatches(node, filter) {
  if (!filter) return true;
  if (node.path.toLowerCase().includes(filter)) return true;
  if (node.type === "dir") return node.children.some(child => shaderNodeMatches(child, filter));
  return false;
}

function renderShaderTree() {
  if (!state.shaderRoot) return;
  updateShaderSelectionStatus();
  const filter = el.shaderFilterInput.value.trim().toLowerCase();
  el.shaderTree.innerHTML = "";
  el.shaderTree.append(renderShaderNode(state.shaderRoot, 0, filter));
}

function renderShaderNode(node, depth, filter) {
  const wrapper = document.createElement("div");
  wrapper.className = "shader-node-wrap";
  if (!shaderNodeMatches(node, filter)) {
    wrapper.hidden = true;
    return wrapper;
  }

  const row = document.createElement("div");
  row.className = `shader-node shader-${node.type}`;
  row.style.setProperty("--depth", String(depth));

  if (node.type === "dir") {
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "tree-toggle";
    const expanded = filter || state.expandedShaderDirs.has(node.path);
    toggle.textContent = expanded ? "-" : "+";
    toggle.addEventListener("click", () => {
      if (state.expandedShaderDirs.has(node.path)) state.expandedShaderDirs.delete(node.path);
      else state.expandedShaderDirs.add(node.path);
      renderShaderTree();
    });
    row.append(toggle);
  } else {
    const spacer = document.createElement("span");
    spacer.className = "tree-toggle-placeholder";
    row.append(spacer);
  }

  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  const selection = shaderNodeSelection(node);
  checkbox.checked = selection === "checked";
  checkbox.indeterminate = selection === "mixed";
  checkbox.addEventListener("change", () => {
    setShaderNodeSelected(node, checkbox.checked);
    renderShaderTree();
    loadSeries();
  });
  row.append(checkbox);

  const label = document.createElement("span");
  label.className = "shader-label";
  label.textContent = node.name;
  label.title = node.path;
  row.append(label);

  const count = document.createElement("span");
  count.className = "shader-count";
  count.textContent = node.type === "dir" ? String(node.shaderCount) : node.app;
  row.append(count);

  wrapper.append(row);
  if (node.type === "dir" && (filter || state.expandedShaderDirs.has(node.path))) {
    const children = document.createElement("div");
    children.className = "shader-children";
    for (const child of node.children) {
      children.append(renderShaderNode(child, depth + 1, filter));
    }
    wrapper.append(children);
  }
  return wrapper;
}

function updateShaderSelectionStatus() {
  const selected = state.selectedShaders.size;
  const total = state.shaderPaths.length;
  el.shaderSelectionStatus.textContent = `${selected.toLocaleString()} / ${total.toLocaleString()} shaders selected`;
}

async function loadSeries() {
  const params = queryParams();
  if (!params.targets.length || !params.stats.length) return;
  const serial = ++state.loadSerial;
  el.statusLine.textContent = "Loading chart...";
  el.rangeWarning.classList.add("hidden");
  setChartLoading(true);
  try {
    const data = await apiPost("/api/series", params);
    if (serial !== state.loadSerial) return;
    state.data = data;
    state.changeReports.clear();
    state.expandedChanges.clear();
    const visibleIds = new Set(state.data.series.map(series => series.id));
    state.hidden = new Set([...state.hidden].filter(id => visibleIds.has(id)));
    renderLegend();
    renderRangeWarning();
    renderChanges();
    drawChart();
    const points = state.data.series.reduce((n, s) => n + s.points.length, 0);
    el.statusLine.textContent = `${points.toLocaleString()} points, ${state.data.changes.length} change commits`;
  } catch (err) {
    if (serial !== state.loadSerial) return;
    el.statusLine.textContent = err.message;
  } finally {
    if (serial === state.loadSerial) setChartLoading(false);
  }
}

function setChartLoading(loading) {
  el.loadingOverlay.classList.toggle("hidden", !loading);
  el.chart.classList.toggle("loading", loading);
}

function renderRangeWarning() {
  const warning = stableRangeWarning(state.data?.query?.stable_counts);
  el.rangeWarning.classList.toggle("hidden", !warning);
  el.rangeWarning.textContent = warning;
}

function stableRangeWarning(stableCounts) {
  if (!stableCounts) return "";
  const items = Object.entries(stableCounts)
    .map(([target, counts]) => ({
      target,
      pathCount: Number(counts.excluded_shader_count) || 0,
      shaderCount: Number(counts.excluded_key_count) || 0,
    }))
    .filter(item => item.shaderCount > 0 || item.pathCount > 0);
  if (!items.length) return "";

  if (items.length === 1) {
    const item = items[0];
    const paths = item.pathCount ? ` across ${fmtNumber(item.pathCount)} shader paths` : "";
    return `Stable shader set: not including ${fmtNumber(item.shaderCount)} shader-stage entries${paths} lost/gained over this range.`;
  }

  const details = items
    .map(item => `${fmtTarget(item.target)}: ${fmtNumber(item.shaderCount)} shader-stage entries`)
    .join(", ");
  const totalShaders = items.reduce((sum, item) => sum + item.shaderCount, 0);
  const totalPaths = items.reduce((sum, item) => sum + item.pathCount, 0);
  const paths = totalPaths ? ` across ${fmtNumber(totalPaths)} shader paths` : "";
  return `Stable shader set: not including ${fmtNumber(totalShaders)} shader-stage entries${paths} lost/gained over this range (${details}).`;
}

function renderLegend() {
  el.legend.innerHTML = "";
  el.legend.classList.add("hidden");
}

function renderChanges() {
  el.changeCount.textContent = `${state.data.changes.length}`;
  el.changeList.innerHTML = "";
  if (!state.data.changes.length) {
    const row = document.createElement("div");
    row.className = "change-empty muted";
    row.textContent = "none";
    el.changeList.append(row);
    return;
  }
  for (const change of state.data.changes) {
    const item = document.createElement("div");
    item.className = "change-item";

    const row = document.createElement("button");
    row.type = "button";
    row.className = "change-row";
    row.innerHTML = `
      <span>${fmtDate(change.to_date || change.from_date)}</span>
      <code>${escapeHtml(change.to_short || "")}</code>
      <span>${escapeHtml(change.to_subject || "")}</span>
    `;

    const report = document.createElement("div");
    report.className = "change-report hidden";

    row.addEventListener("click", () => toggleChangeReport(change, row, report));
    item.append(row, report);
    el.changeList.append(item);
  }
}

async function toggleChangeReport(change, row, container) {
  const sha = change.to_sha;
  if (state.expandedChanges.has(sha)) {
    state.expandedChanges.delete(sha);
    row.classList.remove("expanded");
    container.classList.add("hidden");
    return;
  }

  state.expandedChanges.add(sha);
  row.classList.add("expanded");
  container.classList.remove("hidden");

  const cached = state.changeReports.get(sha);
  if (cached) {
    renderChangeReport(container, cached);
    return;
  }

  container.innerHTML = `<div class="report-loading">Loading report...</div>`;
  try {
    const params = queryParams();
    params.commit = sha;
    const data = await apiPost("/api/change-report", params);
    state.changeReports.set(sha, data);
    if (state.expandedChanges.has(sha)) renderChangeReport(container, data);
  } catch (err) {
    container.innerHTML = `<div class="report-error">${escapeHtml(err.message)}</div>`;
  }
}

function renderChangeReport(container, data) {
  container.innerHTML = `<pre>${escapeHtml(data.report || "No report.")}</pre>`;
}

function drawChart() {
  resizeCanvas();
  const ctx = chart.ctx;
  const w = chart.width;
  const h = chart.height;
  ctx.clearRect(0, 0, w, h);

  const visible = state.data.series.filter(s => !state.hidden.has(s.id) && s.points.length);
  chart.yLabel = visible.length === 1 ? fmtSeriesLabel(visible[0]) : "";
  chart.points = [];
  if (!visible.length) {
    drawEmpty("No visible series");
    return;
  }

  chart.xMode = state.data?.query?.granularity === "commit" ? "commit" : "time";
  chart.plot = {
    left: 82,
    top: 24,
    right: w - 64,
    bottom: h - (chart.xMode === "commit" ? 70 : 54),
  };

  const xs = [];
  const visibleYs = [];
  const boundaryYs = [];
  for (const series of visible) {
    for (const point of series.points) {
      if (chart.xMode === "time") xs.push(parseDate(point.date));
      if (point.boundary) boundaryYs.push(Number(point.value));
      else visibleYs.push(Number(point.value));
    }
  }
  const ys = visibleYs.length ? visibleYs : boundaryYs;
  if (!ys.length) {
    drawEmpty("No visible series");
    return;
  }

  if (chart.xMode === "commit") {
    buildCommitXMap(visible);
  } else {
    const xDomain = chartXDomain(xs);
    chart.xMin = xDomain.min;
    chart.xMax = xDomain.max;
    if (chart.xMin === chart.xMax) chart.xMax += 86400000;
    chart.displayXByCommit = buildDisplayXMap(visible);
    chart.commitItems = [];
  }

  const rawYMin = Math.min(...ys);
  const rawYMax = Math.max(...ys);
  chart.percentBase = rawYMax || 1;
  const yDomain = paddedYDomain(rawYMin, rawYMax, chart.plot.bottom - chart.plot.top);
  chart.yMin = yDomain.min;
  chart.yMax = yDomain.max;
  drawAxes();

  ctx.save();
  ctx.beginPath();
  ctx.rect(chart.plot.left, chart.plot.top, chart.plot.right - chart.plot.left, chart.plot.bottom - chart.plot.top);
  ctx.clip();
  visible.forEach((series, index) => {
    drawSeries(series, colorFor(index));
  });
  ctx.restore();

  if (state.drag) {
    drawDragSelection(ctx);
  }
}

function chartXDomain(xs) {
  const from = state.data?.query?.from;
  const to = state.data?.query?.to;
  let min = from ? parseDate(from) : Math.min(...xs);
  let max = to ? parseDateEnd(to) : Math.max(...xs);
  if (!Number.isFinite(min)) min = Math.min(...xs);
  if (!Number.isFinite(max)) max = Math.max(...xs);
  if (min > max) [min, max] = [max, min];
  return { min, max };
}

function paddedYDomain(rawMin, rawMax, plotHeight) {
  if (rawMin === rawMax) {
    const span = Math.max(1, Math.abs(rawMax) * 0.1);
    return { min: rawMin - span, max: rawMax + span };
  }

  const height = Math.max(1, plotHeight);
  const pixelPad = Math.min(Y_AXIS_PIXEL_PADDING, Math.max(0, height / 2 - 1));
  if (!pixelPad || height <= pixelPad * 2) {
    const valuePad = (rawMax - rawMin) * 0.08;
    return { min: rawMin - valuePad, max: rawMax + valuePad };
  }

  const valuePad = (rawMax - rawMin) * pixelPad / (height - pixelPad * 2);
  return { min: rawMin - valuePad, max: rawMax + valuePad };
}

function drawAxes() {
  const ctx = chart.ctx;
  const p = chart.plot;
  ctx.strokeStyle = "#d7dee3";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(p.left, p.top);
  ctx.lineTo(p.left, p.bottom);
  ctx.lineTo(p.right, p.bottom);
  ctx.moveTo(p.right, p.top);
  ctx.lineTo(p.right, p.bottom);
  ctx.stroke();

  ctx.fillStyle = "#65727c";
  ctx.font = "12px system-ui, sans-serif";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (let i = 0; i <= 5; i++) {
    const t = i / 5;
    const y = p.bottom - t * (p.bottom - p.top);
    const value = chart.yMin + t * (chart.yMax - chart.yMin);
    ctx.strokeStyle = "#edf1f3";
    ctx.beginPath();
    ctx.moveTo(p.left, y);
    ctx.lineTo(p.right, y);
    ctx.stroke();
    ctx.fillText(fmtNumber(Math.round(value)), p.left - 8, y);
  }

  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  const pctStep = Math.abs((chart.yMax - chart.yMin) / chart.percentBase * 100 / 5);
  const pctDecimals = pctStep >= 10 ? 0 : pctStep >= 1 ? 1 : pctStep >= 0.1 ? 2 : 3;
  for (let i = 0; i <= 5; i++) {
    const t = i / 5;
    const y = p.bottom - t * (p.bottom - p.top);
    const value = chart.yMin + t * (chart.yMax - chart.yMin);
    const pct = value / chart.percentBase * 100;
    ctx.fillText(`${pct.toFixed(pctDecimals)}%`, p.right + 8, y);
  }

  if (chart.xMode === "commit") drawCommitXTicks(ctx, p);
  else drawTimeXTicks(ctx, p);

  if (chart.yLabel) {
    ctx.save();
    ctx.translate(16, (p.top + p.bottom) / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillStyle = "#25323a";
    ctx.font = "13px system-ui, sans-serif";
    ctx.fillText(chart.yLabel, 0, 0);
    ctx.restore();
  }
}

function drawTimeXTicks(ctx, p) {
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.fillStyle = "#65727c";
  for (let i = 0; i <= 6; i++) {
    const t = i / 6;
    const x = p.left + t * (p.right - p.left);
    const time = chart.xMin + t * (chart.xMax - chart.xMin);
    ctx.fillText(new Date(time).toISOString().slice(0, 10), x, p.bottom + 10);
  }
}

function drawCommitXTicks(ctx, p) {
  const items = chart.commitItems;
  if (!items.length) return;

  const commitSpacing = items.length > 1 ? Math.abs(items[1].x - items[0].x) : p.right - p.left;
  let labelStep = COMMIT_TICK_STEP;
  while (commitSpacing * labelStep < MIN_COMMIT_LABEL_SPACING) {
    labelStep += COMMIT_TICK_STEP;
  }

  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.fillStyle = "#65727c";
  ctx.strokeStyle = "#d7dee3";
  for (let i = 0; i < items.length; i += COMMIT_TICK_STEP) {
    const item = items[i];
    ctx.beginPath();
    ctx.moveTo(item.x, p.bottom);
    ctx.lineTo(item.x, p.bottom + 5);
    ctx.stroke();
    if (i % labelStep === 0) {
      ctx.fillText(fmtDate(item.date), item.x, p.bottom + 10);
    }
  }
}

function drawSeries(series, color) {
  const ctx = chart.ctx;
  const points = series.points.map(point => ({
    ...point,
    x: displayX(point),
    y: scaleY(Number(point.value)),
  }));
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();
  points.forEach((point, idx) => {
    if (idx === 0) ctx.moveTo(point.x, point.y);
    else ctx.lineTo(point.x, point.y);
  });
  ctx.stroke();

  for (const cluster of markerClusters(points)) {
    const clustered = cluster.points.length > 1;
    const radius = cluster.radius;
    ctx.fillStyle = clustered ? CLUSTER_MARKER_FILL : MARKER_FILL;
    ctx.strokeStyle = color;
    ctx.lineWidth = clustered ? 2 : 1.5;
    ctx.beginPath();
    ctx.arc(cluster.x, cluster.y, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    chart.points.push({
      type: clustered ? "cluster" : "point",
      x: cluster.x,
      y: cluster.y,
      radius,
      series: fmtSeriesLabel(series),
      color: ctx.fillStyle,
      lineColor: color,
      points: cluster.points,
    });
  }
}

function dragBounds() {
  const p = chart.plot;
  const dx = Math.abs(state.drag.currentX - state.drag.startX);
  const zoomX = dx >= MIN_ZOOM_PIXELS;
  const x1 = zoomX ? Math.min(state.drag.startX, state.drag.currentX) : p.left;
  const x2 = zoomX ? Math.max(state.drag.startX, state.drag.currentX) : p.right;
  return { zoomX, x1, x2, y1: p.top, y2: p.bottom };
}

function drawDragSelection(ctx) {
  const bounds = dragBounds();
  if (!bounds.zoomX) return;
  ctx.fillStyle = "rgba(22, 107, 143, 0.14)";
  ctx.fillRect(bounds.x1, bounds.y1, bounds.x2 - bounds.x1, bounds.y2 - bounds.y1);
  ctx.strokeStyle = "rgba(22, 107, 143, 0.6)";
  ctx.strokeRect(bounds.x1, bounds.y1, bounds.x2 - bounds.x1, bounds.y2 - bounds.y1);
}

function buildCommitXMap(seriesList) {
  const byCommit = new Map();
  for (const change of state.data?.changes || []) {
    addCommitAxisItem(byCommit, {
      commit: change.to_sha,
      run_id: change.id,
      order: change.order,
      date: change.to_date,
      short_commit: change.to_short,
      author: change.to_author,
      subject: change.to_subject,
      boundary: false,
    });
  }

  for (const series of seriesList) {
    for (const point of series.points) {
      addCommitAxisItem(byCommit, point);
    }
  }

  const items = [...byCommit.values()].sort(compareCommitItems);
  const visibleItems = items.filter(item => !item.boundary);
  const slotItems = visibleItems.length ? visibleItems : items;
  const positions = new Map();
  chart.commitItems = slotItems;
  chart.displayXByCommit = positions;
  chart.xMin = 0;
  chart.xMax = Math.max(1, slotItems.length - 1);
  if (!slotItems.length) return;

  const minX = chart.plot.left + EDGE_MARKER_INSET;
  const maxX = chart.plot.right - EDGE_MARKER_INSET;
  const width = Math.max(0, maxX - minX);
  const spacing = slotItems.length > 1 ? width / (slotItems.length - 1) : 0;
  const boundarySpacing = spacing || Math.min(80, Math.max(24, width / 4));

  slotItems.forEach((item, index) => {
    item.index = index;
    item.x = slotItems.length === 1 ? (minX + maxX) / 2 : minX + index * spacing;
    positions.set(item.key, item.x);
  });

  const first = slotItems[0];
  const last = slotItems[slotItems.length - 1];
  for (const item of items) {
    if (positions.has(item.key)) continue;
    item.x = compareCommitItems(item, first) <= 0
      ? first.x - boundarySpacing
      : last.x + boundarySpacing;
    positions.set(item.key, item.x);
  }
}

function addCommitAxisItem(byCommit, point) {
  const key = pointKey(point);
  const boundary = Boolean(point.boundary);
  const existing = byCommit.get(key);
  if (existing) {
    existing.boundary = existing.boundary && boundary;
    return;
  }
  byCommit.set(key, {
    key,
    order: pointOrder(point),
    date: point.date,
    dateMs: parseDate(point.date),
    runId: Number(point.run_id) || 0,
    shortCommit: point.short_commit || "",
    author: point.author || "",
    subject: point.subject || "",
    boundary,
    x: 0,
    index: -1,
  });
}

function compareCommitItems(a, b) {
  return (
    a.order - b.order
    || a.dateMs - b.dateMs
    || a.runId - b.runId
    || a.key.localeCompare(b.key)
  );
}

function buildDisplayXMap(seriesList) {
  const byCommit = new Map();
  for (const series of seriesList) {
    for (const point of series.points) {
      const key = pointKey(point);
      if (byCommit.has(key)) continue;
      byCommit.set(key, {
        key,
        desiredX: scaleX(parseDate(point.date)),
        order: pointOrder(point),
        date: parseDate(point.date),
        runId: Number(point.run_id) || 0,
      });
    }
  }

  const items = [...byCommit.values()].sort((a, b) => (
    a.order - b.order || a.date - b.date || a.runId - b.runId || a.key.localeCompare(b.key)
  ));
  const positions = new Map();
  if (!items.length) return positions;

  const minX = chart.plot.left + EDGE_MARKER_INSET;
  const maxX = chart.plot.right - EDGE_MARKER_INSET;
  if (items.length === 1) {
    positions.set(items[0].key, clamp(items[0].desiredX, minX, maxX));
    return positions;
  }

  const spacing = Math.min(MIN_POINT_X_SPACING, Math.max(0, (maxX - minX) / (items.length - 1)));
  const xs = [];
  for (const item of items) {
    const desired = clamp(item.desiredX, minX, maxX);
    const previous = xs.length ? xs[xs.length - 1] + spacing : minX;
    xs.push(Math.max(desired, previous));
  }

  if (xs[xs.length - 1] > maxX) {
    xs[xs.length - 1] = maxX;
    for (let i = xs.length - 2; i >= 0; i--) {
      xs[i] = Math.min(xs[i], xs[i + 1] - spacing);
    }
  }

  items.forEach((item, index) => {
    positions.set(item.key, xs[index]);
  });
  return positions;
}

function displayX(point) {
  const mapped = chart.displayXByCommit.get(pointKey(point));
  if (mapped != null) return mapped;
  if (chart.xMode === "commit") return chart.plot.left;
  return scaleX(parseDate(point.date));
}

function pointKey(point) {
  return point.commit || `${point.date}:${point.run_id}`;
}

function pointOrder(point) {
  const order = Number(point.order);
  return Number.isFinite(order) ? order : parseDate(point.date);
}

function markerClusters(points) {
  const markers = markerPoints(points).filter(point => (
    !point.boundary
    && point.markerX >= chart.plot.left
    && point.markerX <= chart.plot.right
    && point.markerY >= chart.plot.top
    && point.markerY <= chart.plot.bottom
  ));
  if (chart.xMode === "commit") return markers.map(point => makeMarkerCluster([point]));

  const clusters = [];
  let current = [];
  for (const marker of markers) {
    if (current.length && !markerFitsCluster(marker, current)) {
      clusters.push(makeMarkerCluster(current));
      current = [];
    }
    current.push(marker);
  }
  if (current.length) clusters.push(makeMarkerCluster(current));
  return clusters;
}

function markerFitsCluster(marker, clusterPoints) {
  const previous = clusterPoints[clusterPoints.length - 1];
  const centerY = clusterPoints.reduce((sum, point) => sum + point.markerY, 0) / clusterPoints.length;
  return (
    marker.markerX - previous.markerX <= CLUSTER_X_SPACING
    && Math.abs(marker.markerY - centerY) <= CLUSTER_Y_SPACING
  );
}

function makeMarkerCluster(points) {
  const x = points.reduce((sum, point) => sum + point.markerX, 0) / points.length;
  const y = points.reduce((sum, point) => sum + point.markerY, 0) / points.length;
  const radius = points.length === 1
    ? MARKER_RADIUS
    : Math.min(CLUSTER_MARKER_MAX_RADIUS, MARKER_RADIUS + 1.8 + Math.log2(points.length) * 1.7);
  return { x, y, radius, points };
}

function markerPoints(points) {
  return points.map((point, index) => {
    const marker = {
      ...point,
      markerX: clamp(point.x, chart.plot.left + EDGE_MARKER_INSET, chart.plot.right - EDGE_MARKER_INSET),
      markerY: point.y,
    };
    if (marker.markerX === point.x) return marker;

    const neighbor = marker.markerX > point.x ? points[index + 1] : points[index - 1];
    if (neighbor && neighbor.x !== point.x) {
      const t = (marker.markerX - point.x) / (neighbor.x - point.x);
      if (t >= 0 && t <= 1) {
        marker.markerY = point.y + (neighbor.y - point.y) * t;
      }
    }
    return marker;
  });
}

function drawEmpty(message) {
  const ctx = chart.ctx;
  ctx.fillStyle = "#65727c";
  ctx.font = "14px system-ui, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(message, el.chart.width / 2, el.chart.height / 2);
}

function scaleX(value) {
  const p = chart.plot;
  return p.left + (value - chart.xMin) / (chart.xMax - chart.xMin) * (p.right - p.left);
}

function scaleY(value) {
  const p = chart.plot;
  return p.bottom - (value - chart.yMin) / (chart.yMax - chart.yMin) * (p.bottom - p.top);
}

function unscaleX(x) {
  const p = chart.plot;
  return chart.xMin + (x - p.left) / (p.right - p.left) * (chart.xMax - chart.xMin);
}

function commitDateRangeFromPixels(x1, x2) {
  const items = chart.commitItems;
  if (!items.length) return null;
  const left = Math.min(x1, x2);
  const right = Math.max(x1, x2);
  let startIndex = items.findIndex(item => item.x >= left);
  if (startIndex === -1) startIndex = items.length - 1;

  let endIndex = -1;
  for (let i = items.length - 1; i >= 0; i--) {
    if (items[i].x <= right) {
      endIndex = i;
      break;
    }
  }
  if (endIndex === -1) endIndex = 0;

  if (startIndex > endIndex) {
    const midpoint = (left + right) / 2;
    let nearestIndex = 0;
    let nearestDistance = Infinity;
    items.forEach((item, index) => {
      const distance = Math.abs(item.x - midpoint);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearestIndex = index;
      }
    });
    startIndex = nearestIndex;
    endIndex = nearestIndex;
  }

  return {
    from: fmtDate(items[startIndex].date),
    to: fmtDate(items[endIndex].date),
  };
}

function resizeCanvas() {
  const rect = el.chart.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  chart.width = Math.max(1, Math.round(rect.width));
  chart.height = Math.max(1, Math.round(rect.height));
  el.chart.width = Math.max(1, Math.round(chart.width * dpr));
  el.chart.height = Math.max(1, Math.round(chart.height * dpr));
  chart.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function colorFor(index) {
  return state.colors[index % state.colors.length];
}

function canvasPos(event) {
  const rect = el.chart.getBoundingClientRect();
  return {
    x: event.clientX - rect.left,
    y: event.clientY - rect.top,
  };
}

function showTooltip(hit, pos) {
  clearTimeout(state.tooltipHideTimer);
  el.tooltip.classList.remove("hidden");
  el.tooltip.innerHTML = tooltipHtml(hit);

  const margin = 10;
  const chartRect = el.chart.getBoundingClientRect();
  const tipRect = el.tooltip.getBoundingClientRect();
  let left = chartRect.left + pos.x + 14;
  if (left + tipRect.width > window.innerWidth - margin) {
    left = chartRect.left + pos.x - tipRect.width - 14;
  }
  left = clamp(left, margin, Math.max(margin, window.innerWidth - tipRect.width - margin));

  let top = chartRect.top + pos.y + 14;
  if (top + tipRect.height > window.innerHeight - margin) {
    top = chartRect.top + pos.y - tipRect.height - 14;
  }
  top = clamp(top, margin, Math.max(margin, window.innerHeight - tipRect.height - margin));

  el.tooltip.style.left = `${left - chartRect.left}px`;
  el.tooltip.style.top = `${top - chartRect.top}px`;
}

function tooltipHtml(hit) {
  if (hit.points.length > 1) {
    const items = hit.points.slice(0, MAX_TOOLTIP_CLUSTER_COMMITS).map(point => {
      const author = point.author ? `, ${escapeHtml(point.author)}` : "";
      return `
        <li>
          <code>${escapeHtml(point.short_commit || "")}</code>
          <span>${escapeHtml(point.subject || "")}</span>
          <span class="commit-meta muted">${fmtDate(point.date)}${author}</span>
        </li>
      `;
    }).join("");
    const remaining = hit.points.length - MAX_TOOLTIP_CLUSTER_COMMITS;
    const more = remaining > 0 ? `<li class="muted">... ${remaining} more</li>` : "";
    return `
      <div><strong>${escapeHtml(hit.series)}</strong> ${hit.points.length} commits</div>
      <ul class="tooltip-commits">${items}${more}</ul>
    `;
  }

  const point = hit.points[0];
  const author = point.author ? `<span class="muted"> by ${escapeHtml(point.author)}</span>` : "";
  return `
    <div><strong>${escapeHtml(hit.series)}</strong> ${fmtNumber(point.value)}</div>
    <div><code>${escapeHtml(point.short_commit || "")}</code> <span class="muted">${fmtDate(point.date)}</span>${author}</div>
    <pre>${escapeHtml(point.message || point.subject || "")}</pre>
  `;
}

function hideTooltipDelayed() {
  clearTimeout(state.tooltipHideTimer);
  state.tooltipHideTimer = setTimeout(() => {
    el.tooltip.classList.add("hidden");
  }, 180);
}

el.chart.addEventListener("mousemove", event => {
  if (!chart.plot) return;
  const pos = canvasPos(event);
  if (state.drag) {
    state.drag.currentX = clamp(pos.x, chart.plot.left, chart.plot.right);
    drawChart();
    return;
  }
  const hit = nearestPoint(pos.x, pos.y);
  if (!hit) {
    hideTooltipDelayed();
    return;
  }
  showTooltip(hit, pos);
});

el.chart.addEventListener("mouseleave", () => {
  hideTooltipDelayed();
  state.drag = null;
  drawChart();
});

el.tooltip.addEventListener("mouseenter", () => {
  clearTimeout(state.tooltipHideTimer);
});

el.tooltip.addEventListener("mouseleave", hideTooltipDelayed);

el.chart.addEventListener("mousedown", event => {
  if (!chart.plot) return;
  const pos = canvasPos(event);
  if (pos.x < chart.plot.left || pos.x > chart.plot.right) return;
  if (pos.y < chart.plot.top || pos.y > chart.plot.bottom) return;
  state.drag = { startX: pos.x, currentX: pos.x };
});

el.chart.addEventListener("dblclick", () => {
  state.drag = null;
  setFullRange();
  setGranularity("commit");
  loadSeries();
});

window.addEventListener("mouseup", () => {
  if (!state.drag || !chart.plot) return;
  const bounds = dragBounds();
  state.drag = null;
  if (!bounds.zoomX) {
    drawChart();
    return;
  }
  const range = chart.xMode === "commit"
    ? commitDateRangeFromPixels(bounds.x1, bounds.x2)
    : {
        from: new Date(unscaleX(bounds.x1)).toISOString().slice(0, 10),
        to: new Date(unscaleX(bounds.x2)).toISOString().slice(0, 10),
      };
  if (!range) {
    drawChart();
    return;
  }
  el.fromInput.value = range.from;
  el.toInput.value = range.to;
  setGranularity("commit");
  loadSeries();
});

window.addEventListener("resize", debounce(drawChart, 100));

function nearestPoint(x, y) {
  let best = null;
  let bestDist = Infinity;
  for (const point of chart.points) {
    const dist = Math.hypot(point.x - x, point.y - y);
    const hitRadius = Math.max(12, point.radius + 5);
    if (dist <= hitRadius && dist < bestDist) {
      best = point;
      bestDist = dist;
    }
  }
  return best;
}

function debounce(fn, delay) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, ch => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

async function init() {
  state.meta = await api("/api/meta");
  setupControls(state.meta);
  await loadShaderTree();
  await loadSeries();
}

init().catch(err => {
  el.statusLine.textContent = err.message;
});
