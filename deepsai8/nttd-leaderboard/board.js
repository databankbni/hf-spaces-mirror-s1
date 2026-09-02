// The board: fetch, filter, sort, render.
//
// Presentation only. The ranking, the per-shape numbering, the seed counting and the
// blank-versus-zero cost rule are decided in table.py, where they are tested, and arrive
// already shaped in board.json. Reading the parquet here would mean reimplementing all of
// it in JavaScript, and that copy is the one nobody would check.

const RESULTS = "https://huggingface.co/datasets/deepsai8/nttd-submissions/resolve/main";
const BOARD = `${RESULTS}/board.json`;

// Eleven of about twenty. The rest are one click away.
//
// size, terrain and seed are all default, and the seed is the reason: those three are
// everything needed to generate the identical map, so a reader can go and play the same
// problem. They also explain the numbering, which restarts within each world shape and
// would otherwise read as a bug.
//
// score and cargo are both straight from the game: OpenTTD's own performance rating, and
// every unit delivered. The derived business metrics that used to sit here, margin and
// credit used, are gone from the board; they describe how a company was run rather than
// what it achieved, and they live in nttd's monitor which reads the same series.
// The order a reader sees first, value leading because that is what the board is about.
const DEFAULT_COLUMNS = [
  "#", "entrant", "value", "cargo", "cost", "size", "terrain", "seed", "verified",
];

// The order behind "All columns": the same run of figures, then score, then everything
// that describes HOW it was played rather than how it went.
const ALL_COLUMN_ORDER = [
  "#", "entrant", "value", "cargo", "score", "cost", "size", "terrain", "seed",
  "verified", "system", "class", "mode", "model", "session",
];

// Present on every row and never shown as one.
//
// `submission` is the slot an entrant filed under. It joins a row to its checks and its
// trajectory, keys the expanded view, and names the bundle at
// submissions/<entrant>/<submission>/, so every row needs to carry it. None of that needs a
// column: `session` already identifies the run, and for a submission filed without --id the
// two are the same string printed twice. It still heads the expanded view.
const HIDDEN_COLUMNS = new Set(["submission"]);

// Right-aligned with tabular figures, because a column of numbers is read by comparing
// digits in the same position.
const HASH_TITLE =
  "Position within this map size and terrain, not overall. A 64x64 flat run and a "
  + "1024x1024 mountainous one are not competing, so they are numbered separately.";

const NUMERIC = new Set([
  "score", "cargo", "value", "cost",
]);

// Rendered with a leading currency mark. `cost` already arrives as a formatted string from
// the shaping step; `value` arrives as a bare number and is the board's headline figure.
const CURRENCY = new Set(["value"]);

// Where an entrant's profile lives. The entrant IS a HuggingFace account: `nttd publish`
// reads it from the token, and the ingest refuses a pull request touching anything outside
// submissions/<the account that opened it>/. So the link is sound by construction for
// anything filed that way.
const HF_PROFILE = "https://huggingface.co/";

// Shown behind the toggle rather than by default: it identifies a run precisely and is
// long, so it earns its place in the expanded view and not in the ten column summary.
const WIDE_COLUMNS = new Set(["session"]);

const state = {
  rows: [],
  checks: [],
  trajectories: [],
  columns: DEFAULT_COLUMNS,
  // Value leads: it is the figure the board is read for, and the one the default
  // column set puts first.
  sort: { key: "value", desc: true },
  selected: null,
};

const $ = (id) => document.getElementById(id);
const FILTERS = { size: "f-size", terrain: "f-terrain", verified: "f-verdict", class: "f-class" };

async function load() {
  try {
    const response = await fetch(BOARD, { cache: "no-store" });
    // 404 is the expected state before the first verification has published anything,
    // not a fault. Reporting it as an error made an empty board read as a broken one.
    //
    // Not an early return: that would skip the render below, and a board with no table
    // at all is worse than one with the wrong message.
    if (response.status !== 404) {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const board = await response.json();
      state.rows = board.rows ?? [];
      state.checks = board.checks ?? [];
      state.trajectories = board.trajectories ?? [];
    }
  } catch (error) {
    // Any other failure is worth saying out loud: an empty board and an unreachable one
    // look identical if this is silent, and they are very different things to a reader.
    state.error = String(error);
  }
  fillFilters();
  render();
}

function fillFilters() {
  for (const [key, id] of Object.entries(FILTERS)) {
    const select = $(id);
    const values = [...new Set(state.rows.map((row) => row[key]).filter(Boolean))].sort();
    for (const value of values) {
      select.append(Object.assign(document.createElement("option"), { value, textContent: value }));
    }
    select.addEventListener("change", render);
  }
  $("f-q").addEventListener("input", render);
  $("f-reset").addEventListener("click", () => {
    for (const id of Object.values(FILTERS)) $(id).value = "";
    $("f-q").value = "";
    render();
  });
  $("f-columns").addEventListener("click", (event) => {
    const showingAll = state.columns !== DEFAULT_COLUMNS;
    state.columns = showingAll ? DEFAULT_COLUMNS : allColumns();
    event.target.textContent = showingAll ? "All columns" : "Fewer columns";
    event.target.setAttribute("aria-expanded", String(!showingAll));
    render();
  });
}

function allColumns() {
  // The declared order first, then anything a row carries that it does not mention. The
  // tail matters: a column added to a published row must appear somewhere without anyone
  // having to remember to list it here, which is how `system` came to be invisible.
  const seen = ALL_COLUMN_ORDER.filter((name) => !HIDDEN_COLUMNS.has(name));
  for (const row of state.rows) {
    for (const key of Object.keys(row)) {
      if (!seen.includes(key) && !HIDDEN_COLUMNS.has(key)) seen.push(key);
    }
  }
  return seen;
}

function visible() {
  const query = $("f-q").value.trim().toLowerCase();
  return state.rows.filter((row) => {
    for (const [key, id] of Object.entries(FILTERS)) {
      const chosen = $(id).value;
      if (chosen && String(row[key] ?? "") !== chosen) return false;
    }
    if (!query) return true;
    return [row.entrant, row.model, row.submission]
      .some((field) => String(field ?? "").toLowerCase().includes(query));
  });
}

function sorted(rows) {
  const { key, desc } = state.sort;
  // Money and percentages arrive as rendered strings, so sorting reads the number out
  // of them rather than comparing "$9.00" against "$10.00" as text.
  const value = (row) => {
    const raw = row[key];
    if (typeof raw === "number") return raw;
    const numeric = Number(String(raw ?? "").replace(/[$,%\s]/g, ""));
    return Number.isFinite(numeric) && String(raw ?? "").trim() !== "" ? numeric : null;
  };
  return [...rows].sort((a, b) => {
    const [x, y] = [value(a), value(b)];
    // Blanks last whichever way the column is sorted: an unreported cost is not the
    // cheapest run.
    if (x === null && y === null) return String(a.entrant).localeCompare(String(b.entrant));
    if (x === null) return 1;
    if (y === null) return -1;
    if (x === y) return String(a.entrant).localeCompare(String(b.entrant));
    return desc ? y - x : x - y;
  });
}

function render() {
  const rows = sorted(visible());

  const head = $("head");
  head.replaceChildren(...state.columns.map((name) => {
    const th = document.createElement("th");
    th.textContent = name;
    // Worth saying in the header rather than only in a footnote. With mixed sizes and
    // terrains on screen and the default sort by score, the numbers interleave, which
    // reads as a bug until you know they are per-shape.
    if (name === "#") th.title = HASH_TITLE;
    if (state.sort.key === name) {
      th.setAttribute("aria-sort", state.sort.desc ? "descending" : "ascending");
      th.append(Object.assign(document.createElement("span"),
        { className: "arrow", textContent: state.sort.desc ? "↓" : "↑" }));
    }
    th.addEventListener("click", () => {
      state.sort = state.sort.key === name
        ? { key: name, desc: !state.sort.desc }
        : { key: name, desc: true };
      render();
    });
    return th;
  }));

  const body = $("rows");
  if (!rows.length) {
    const message = state.error
      ? `Could not load the board: ${state.error}`
      : state.rows.length
        ? "No runs match these filters."
        : "No submissions have been verified yet. The columns above are what a row will carry.";
    // Built rather than interpolated: `message` can carry a fetch error string, and
    // innerHTML here would make any future message a scripting hole.
    const cell = document.createElement("td");
    cell.className = "empty";
    cell.colSpan = state.columns.length;
    cell.textContent = message;
    const tr = document.createElement("tr");
    tr.append(cell);
    body.replaceChildren(tr);
    $("count").textContent = "";
    return;
  }

  body.replaceChildren(...rows.map((row) => {
    const tr = document.createElement("tr");
    tr.tabIndex = 0;
    const key = `${row.entrant}/${row.submission}`;
    if (state.selected === key) tr.setAttribute("aria-selected", "true");
    for (const name of state.columns) tr.append(cell(row, name));
    const open = () => { state.selected = key; render(); showDetail(row); };
    tr.addEventListener("click", open);
    tr.addEventListener("keydown", (event) => { if (event.key === "Enter") open(); });
    return tr;
  }));

  const total = state.rows.length;
  $("count").textContent = rows.length === total
    ? `${total} run${total === 1 ? "" : "s"}`
    : `${rows.length} of ${total} runs`;
}

function cell(row, name) {
  const td = document.createElement("td");
  const raw = row[name];

  if (name === "#") { td.className = "rank"; td.textContent = raw ?? ""; return td; }
  if (name === "entrant") {
    td.className = "who";
    const who = String(raw ?? "");
    // Linked only where the name is known to BE an account. `nttd publish` reads it from
    // the token and the ingest refuses a diff outside submissions/<the PR author>/, so
    // anything filed that way is real. `unknown-user` is the placeholder for a filing that
    // could not name one, and rows predating that rule carry a label rather than an
    // account. A link to a profile that does not exist is worse than no link.
    if (!who || !linkable(who)) {
      td.textContent = who;
      return td;
    }
    const link = document.createElement("a");
    link.href = HF_PROFILE + encodeURIComponent(who);
    link.textContent = who;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    td.append(link);
    return td;
  }

  if (name === "seed") {
    // Never thousand-separated. A seed exists to be copied and played, and 1,234,567 is
    // not something you can paste into a scenario file. Monospaced for the same reason:
    // it is an identifier to transcribe, not a magnitude to compare.
    td.className = "seed";
    const pinned = raw !== -1 && raw !== null && raw !== undefined;
    td.textContent = pinned ? String(raw) : "none";
    if (!pinned) td.classList.add("dim");
    return td;
  }

  if (name === "verified") {
    const wrap = document.createElement("span");
    wrap.className = "verdict";
    wrap.append(
      Object.assign(document.createElement("span"), { className: `dot ${raw}` }),
      document.createTextNode(String(raw ?? "")),
    );
    td.append(wrap);
    if (row["metrics agree"] === false) {
      td.append(Object.assign(document.createElement("span"),
        { className: "warn-metrics", textContent: " metrics disagree" }));
    }
    return td;
  }

  if (NUMERIC.has(name)) td.className = "num";
  if (raw === "" || raw === null || raw === undefined) {
    // Left blank rather than filled with a placeholder. An unreported cost is exactly
    // that: absent, which the footnote says is different from zero.
    td.classList.add("dim");
    td.textContent = "";
    return td;
  }
  if (typeof raw === "number") {
    td.textContent = (CURRENCY.has(name) ? "$" : "") + raw.toLocaleString();
    return td;
  }
  td.textContent = String(raw);
  return td;
}

// Entrants that are not HuggingFace accounts, so their names are shown as plain text.
const NOT_AN_ACCOUNT = new Set(["unknown-user", "claude-code"]);

function linkable(who) {
  return !NOT_AN_ACCOUNT.has(who);
}

function showDetail(row) {
  const panel = $("detail");
  panel.hidden = false;
  panel.replaceChildren();

  panel.append(
    Object.assign(document.createElement("h2"),
      { textContent: `${row.entrant} / ${row.submission}` }),
    Object.assign(document.createElement("p"), {
      className: "sub",
      textContent: `${Number(row.score).toLocaleString()} on ${row.size} ${row.terrain}, `
        + `seed ${row.seed}. Verdict: ${row.verified}.`,
    }),
  );

  const grid = document.createElement("div");
  grid.className = "detail-grid";
  grid.append(checksTable(row), trendFigure(row));
  panel.append(grid);
  panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function checksTable(row) {
  const mine = state.checks.filter((check) => check.submission_id === row.submission);
  const figure = document.createElement("div");

  if (!mine.length) {
    figure.append(Object.assign(document.createElement("p"),
      { className: "sub", textContent: "No checks published for this run yet." }));
    return figure;
  }

  const table = document.createElement("table");
  table.className = "checks";
  const headRow = document.createElement("tr");
  for (const label of ["check", "result", "detail"]) {
    headRow.append(Object.assign(document.createElement("th"), { textContent: label }));
  }
  const head = document.createElement("thead");
  head.append(headRow);
  table.append(head);
  const body = document.createElement("tbody");

  for (const check of [...mine].sort((a, b) => String(a.check).localeCompare(String(b.check)))) {
    const tr = document.createElement("tr");
    // Not attempted is not failed. Collapsing the two would make the board look
    // stricter than it is.
    const [mark, cls] = check.passed === null || check.passed === undefined
      ? ["not run", "skip"]
      : check.passed ? ["pass", "pass"] : ["fail", "fail"];
    const name = Object.assign(document.createElement("td"),
      { textContent: check.check ?? "" });
    const result = Object.assign(document.createElement("td"),
      { className: cls, textContent: mark });
    const detail = Object.assign(document.createElement("td"),
      { textContent: check.detail ?? "" });
    tr.append(name, result, detail);
    body.append(tr);
  }
  table.append(body);
  figure.append(table);
  return figure;
}

// --- the trend ------------------------------------------------------------------
//
// One series over time, so a line: the question is the shape of the run, not the value
// at any one tick. One series means no legend, and the caption names it.

function trendFigure(row) {
  const series = state.trajectories
    .filter((point) => point.entrant === row.entrant && point.submission_id === row.submission)
    .sort((a, b) => a.game_date - b.game_date);

  const figure = document.createElement("figure");
  figure.append(Object.assign(document.createElement("figcaption"),
    { textContent: "Company value over the run" }));

  if (series.length < 2) {
    figure.append(Object.assign(document.createElement("p"), {
      className: "sub",
      textContent: "No series published for this run, so its shape cannot be drawn.",
    }));
    return figure;
  }
  figure.append(linePlot(series));
  return figure;
}

function linePlot(series) {
  const W = 520, H = 200, PAD = { top: 12, right: 14, bottom: 26, left: 52 };
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;

  const xs = series.map((p) => p.game_date);
  const ys = series.map((p) => p.value);
  const [x0, x1] = [Math.min(...xs), Math.max(...xs)];
  const yMax = Math.max(...ys, 1);

  const sx = (x) => PAD.left + (x1 === x0 ? innerW / 2 : ((x - x0) / (x1 - x0)) * innerW);
  const sy = (y) => PAD.top + innerH - (y / yMax) * innerH;

  const wrap = document.createElement("div");
  wrap.className = "plot";
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `Company value from game day ${x0} to ${x1}`);

  // Recessive grid, three lines. More would compete with the data.
  const grid = document.createElementNS(ns, "g");
  grid.setAttribute("class", "grid");
  const axis = document.createElementNS(ns, "g");
  axis.setAttribute("class", "axis");
  for (const fraction of [0, 0.5, 1]) {
    const value = yMax * fraction;
    const y = sy(value);
    const line = document.createElementNS(ns, "line");
    line.setAttribute("x1", PAD.left); line.setAttribute("x2", W - PAD.right);
    line.setAttribute("y1", y); line.setAttribute("y2", y);
    grid.append(line);
    const label = document.createElementNS(ns, "text");
    label.setAttribute("x", PAD.left - 8); label.setAttribute("y", y + 3);
    label.setAttribute("text-anchor", "end");
    label.textContent = compact(value);
    axis.append(label);
  }
  for (const [x, anchor] of [[x0, "start"], [x1, "end"]]) {
    const label = document.createElementNS(ns, "text");
    label.setAttribute("x", sx(x)); label.setAttribute("y", H - 8);
    label.setAttribute("text-anchor", anchor);
    label.textContent = `day ${x - x0}`;
    axis.append(label);
  }
  svg.append(grid, axis);

  const path = document.createElementNS(ns, "path");
  path.setAttribute("class", "line");
  path.setAttribute("d", series.map((p, i) =>
    `${i ? "L" : "M"}${sx(p.game_date).toFixed(1)} ${sy(p.value).toFixed(1)}`).join(" "));
  svg.append(path);

  const last = series[series.length - 1];
  const end = document.createElementNS(ns, "circle");
  end.setAttribute("class", "end-dot");
  end.setAttribute("cx", sx(last.game_date)); end.setAttribute("cy", sy(last.value));
  end.setAttribute("r", 4);
  svg.append(end);

  // Hover layer: crosshair plus a tooltip, which an SVG chart in a page should have by
  // default rather than as an extra.
  const crosshair = document.createElementNS(ns, "line");
  crosshair.setAttribute("class", "crosshair");
  crosshair.setAttribute("y1", PAD.top); crosshair.setAttribute("y2", PAD.top + innerH);
  crosshair.style.display = "none";
  const marker = document.createElementNS(ns, "circle");
  marker.setAttribute("class", "hover-dot");
  marker.setAttribute("r", 4.5);
  marker.style.display = "none";
  svg.append(crosshair, marker);

  const tip = document.createElement("div");
  tip.className = "tip";
  tip.style.display = "none";

  const hit = document.createElementNS(ns, "rect");
  hit.setAttribute("x", PAD.left); hit.setAttribute("y", PAD.top);
  hit.setAttribute("width", innerW); hit.setAttribute("height", innerH);
  hit.setAttribute("fill", "transparent");
  svg.append(hit);

  const move = (event) => {
    const box = svg.getBoundingClientRect();
    const px = ((event.clientX - box.left) / box.width) * W;
    let nearest = series[0];
    for (const point of series) {
      if (Math.abs(sx(point.game_date) - px) < Math.abs(sx(nearest.game_date) - px)) {
        nearest = point;
      }
    }
    const [cx, cy] = [sx(nearest.game_date), sy(nearest.value)];
    crosshair.setAttribute("x1", cx); crosshair.setAttribute("x2", cx);
    crosshair.style.display = "";
    marker.setAttribute("cx", cx); marker.setAttribute("cy", cy);
    marker.style.display = "";
    tip.textContent = `day ${nearest.game_date - x0} · ${Number(nearest.value).toLocaleString()}`;
    tip.style.display = "";
    tip.style.left = `${(cx / W) * 100}%`;
    tip.style.top = `${(cy / H) * 100}%`;
  };
  const leave = () => {
    crosshair.style.display = "none";
    marker.style.display = "none";
    tip.style.display = "none";
  };
  svg.addEventListener("pointermove", move);
  svg.addEventListener("pointerleave", leave);

  wrap.append(svg, tip);
  return wrap;
}

function compact(value) {
  const n = Number(value) || 0;
  if (Math.abs(n) >= 1e9) return `${(n / 1e9).toFixed(1)}B`;
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (Math.abs(n) >= 1e3) return `${Math.round(n / 1e3)}k`;
  return String(Math.round(n));
}

load();
