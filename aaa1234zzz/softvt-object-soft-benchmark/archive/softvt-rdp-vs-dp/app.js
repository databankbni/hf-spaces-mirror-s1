const $ = (selector) => document.querySelector(selector);

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function renderMethods(methods) {
  const chart = $("#method-chart");
  methods.forEach((method) => {
    const row = element("div", `method-row ${method.id}`);
    const meta = element("div", "method-meta");
    meta.append(
      element("span", "", method.label),
      element("strong", "", `${method.successes}/${method.total} · ${method.rate_percent}%`),
    );

    const track = element("div", "bar-track");
    track.setAttribute(
      "aria-label",
      `${method.label}: ${method.successes} of ${method.total}, ${method.rate_percent} percent; 95 percent interval ${method.ci_percent[0]} to ${method.ci_percent[1]} percent`,
    );
    const fill = element("div", "bar-fill");
    fill.style.width = `${method.rate_percent}%`;

    const ci = element("div", "ci-line");
    ci.style.left = `${method.ci_percent[0]}%`;
    ci.style.width = `${Math.max(method.ci_percent[1] - method.ci_percent[0], 0.35)}%`;
    track.append(fill, ci);
    row.append(meta, track);
    chart.append(row);
  });
}

function renderTasks(tasks) {
  const grid = $("#task-grid");
  grid.append(element("div", "task-cell header", "paired cell"));
  tasks.forEach((task) => {
    const header = element("div", "task-cell header");
    header.append(document.createTextNode(`task ${task.task}`), element("span", "asset-name", task.asset));
    header.title = `Reset ${task.reset_state_sha256}`;
    grid.append(header);
  });

  [
    ["RDP treatment", "rdp"],
    ["Frozen DP", "dp"],
  ].forEach(([label, key]) => {
    grid.append(element("div", "task-cell row-label", label));
    tasks.forEach((task) => {
      const cell = element("div", "task-cell outcome");
      const success = task[key] === 1;
      const badge = element("span", `outcome-badge${success ? " success" : ""}`);
      badge.setAttribute("aria-label", success ? "success" : "failure");
      badge.title = `${label} · task ${task.task}: ${success ? "success" : "failure"}`;
      cell.append(badge);
      grid.append(cell);
    });
  });
}

function renderBootstrap(effect) {
  const chart = $("#bootstrap-chart");
  const max = Math.max(...effect.distribution.map((item) => item.probability_percent));
  effect.distribution.forEach((item) => {
    const column = element(
      "div",
      `bootstrap-column${item.value === effect.percentage_points ? " observed" : ""}`,
    );
    const probability = element("span", "bootstrap-prob", `${item.probability_percent.toFixed(1)}%`);
    const wrap = element("div", "bootstrap-bar-wrap");
    const bar = element("div", "bootstrap-bar");
    bar.style.height = `${(item.probability_percent / max) * 100}%`;
    bar.title = `${item.probability_percent.toFixed(3)}% of paired task resamples produce ${item.value} percentage points`;
    wrap.append(bar);
    const value = element("span", "bootstrap-value", `${item.value > 0 ? "+" : ""}${item.value} pp`);
    column.append(probability, wrap, value);
    chart.append(column);
  });
}

function renderTreatment(items) {
  const list = $("#treatment-list");
  items.forEach((item, index) => {
    const card = element("div", "treatment-item", item);
    card.prepend(element("span", "", String(index + 1).padStart(2, "0")));
    list.append(card);
  });
}

function renderProtocol(data) {
  const benchmark = data.benchmark;
  const cards = [
    ["perception", "Dual RGB + bilateral marker flow", "language + proprioception"],
    ["pairing", "5 object-soft task/reset cells", "all reset hashes match"],
    ["seeds", `policy ${benchmark.policy_seed} · simulator ${benchmark.simulator_seed}`, "development pool"],
    ["runtime", `${benchmark.horizon_controls} controls · ${benchmark.frequency_hz} Hz`, "one action per control"],
  ];
  const grid = $("#protocol-grid");
  cards.forEach(([label, value, note]) => {
    const card = element("div", "protocol-card");
    card.append(element("span", "", label), element("strong", "", value), element("small", "", note));
    grid.append(card);
  });

  const provenance = [
    ["RoboProgram revision", data.provenance.roboprogram_revision],
    ["SoftVTBench revision", benchmark.revision],
    ["Dataset revision", benchmark.dataset_revision],
    ["RDP checkpoint SHA-256", data.methods[0].checkpoint_sha256],
    ["DP checkpoint SHA-256", data.methods[1].checkpoint_sha256],
    ["Raw gripper SHA-256", data.provenance.raw_gripper_command_sha256],
    ["Action target", data.provenance.action_target],
  ];
  const detail = $("#provenance-grid");
  provenance.forEach(([key, value]) => {
    detail.append(element("div", "key", key), element("div", "", String(value)));
  });
}

function initVideoSwitcher() {
  const video = $("#episode-video");
  const source = $("#episode-video-source");
  const label = $("#episode-video-label");
  const detail = $("#episode-video-detail");
  const download = $("#download-camera");
  const downloadLabel = $("#download-camera-label");
  const buttons = document.querySelectorAll("[data-video-src]");
  if (!video || !source || !download || !downloadLabel || !buttons.length) return;

  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      if (button.classList.contains("active")) return;

      const priorTime = video.currentTime;
      const resume = !video.paused;
      buttons.forEach((candidate) => {
        const active = candidate === button;
        candidate.classList.toggle("active", active);
        candidate.setAttribute("aria-pressed", String(active));
      });

      video.pause();
      source.src = button.dataset.videoSrc;
      video.poster = button.dataset.videoPoster;
      label.textContent = button.dataset.videoLabel;
      detail.textContent = button.dataset.videoDetail;
      download.href = button.dataset.videoDownloadUrl;
      download.download = button.dataset.videoDownloadName;
      downloadLabel.textContent = button.dataset.videoDownloadLabel;
      video.load();
      video.addEventListener(
        "loadedmetadata",
        () => {
          video.currentTime = Math.min(priorTime, video.duration || priorTime);
          if (resume) video.play().catch(() => {});
        },
        {once: true},
      );
    });
  });
}

function initComparisonPlayback() {
  const play = $("#play-comparison");
  const pause = $("#pause-comparison");
  const videos = [$("#comparison-rdp-video"), $("#comparison-dp-video")];
  if (!play || !pause || videos.some((video) => !video)) return;

  play.addEventListener("click", () => {
    videos.forEach((video) => {
      video.pause();
      video.currentTime = 0;
    });
    Promise.allSettled(videos.map((video) => video.play()));
  });

  pause.addEventListener("click", () => videos.forEach((video) => video.pause()));
}

function initTactileVisualization(data) {
  const tactile = data.tactile_visualization;
  const scene = $("#tactile-scene-video");
  const left = $("#tactile-left-video");
  const right = $("#tactile-right-video");
  const canvas = $("#tactile-timeline");
  const status = $("#tactile-status");
  const time = $("#tactile-time");
  const detail = $("#tactile-arm-detail");
  const downloadLeft = $("#download-tactile-left");
  const downloadRight = $("#download-tactile-right");
  const armButtons = document.querySelectorAll("[data-tactile-arm]");
  if (!tactile || !scene || !left || !right || !canvas || !status || !time) return;

  const videos = [scene, left, right];
  let selected = "rdp";
  let arm = tactile.arms[selected];
  let animationFrame;

  function gateAt(runs, frame) {
    const run = runs.find(([first, last]) => frame >= first && frame <= last);
    return run ? run[2] : false;
  }

  function currentFrame() {
    return Math.min(
      arm.frames - 1,
      Math.max(0, Math.floor(scene.currentTime * tactile.timeline.sample_rate_hz)),
    );
  }

  function updateReadout() {
    const frame = currentFrame();
    const leftActive = gateAt(arm.contact_gate_runs.left, frame);
    const rightActive = gateAt(arm.contact_gate_runs.right, frame);
    time.textContent = `${scene.currentTime.toFixed(1)} / ${arm.duration_seconds.toFixed(1)} s`;
    status.textContent = `Frame ${frame} · left ${leftActive ? "contact active" : "below threshold"} · right ${rightActive ? "contact active" : "below threshold"}`;
  }

  function drawTimeline() {
    const bounds = canvas.getBoundingClientRect();
    const width = Math.max(300, Math.floor(bounds.width));
    const height = 180;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.floor(width * ratio);
    canvas.height = Math.floor(height * ratio);
    const context = canvas.getContext("2d");
    context.scale(ratio, ratio);

    const plotLeft = 70;
    const plotRight = width - 14;
    const plotWidth = plotRight - plotLeft;
    const rows = [
      ["LEFT", arm.contact_gate_runs.left, 54],
      ["RIGHT", arm.contact_gate_runs.right, 108],
    ];

    context.clearRect(0, 0, width, height);
    context.font = '9px "DM Mono", monospace';
    context.textBaseline = "middle";
    rows.forEach(([label, runs, y]) => {
      context.fillStyle = "#72808c";
      context.fillText(label, 8, y + 11);
      context.fillStyle = "#edf0f2";
      context.fillRect(plotLeft, y, plotWidth, 22);
      runs.forEach(([first, last, active]) => {
        if (!active) return;
        const x = plotLeft + (first / arm.frames) * plotWidth;
        const runWidth = ((last + 1 - first) / arm.frames) * plotWidth;
        context.fillStyle = "#19785d";
        context.fillRect(x, y, Math.max(runWidth, 1), 22);
      });
      context.strokeStyle = "#dce1dc";
      context.strokeRect(plotLeft + 0.5, y + 0.5, plotWidth - 1, 21);
    });

    context.textAlign = "center";
    for (let tick = 0; tick <= 4; tick += 1) {
      const fraction = tick / 4;
      const x = plotLeft + fraction * plotWidth;
      context.strokeStyle = "rgba(22, 33, 43, 0.10)";
      context.beginPath();
      context.moveTo(x, 34);
      context.lineTo(x, 140);
      context.stroke();
      context.fillStyle = "#72808c";
      context.fillText(`${(fraction * arm.duration_seconds).toFixed(1)} s`, x, 158);
    }

    const fraction = Math.min(scene.currentTime / arm.duration_seconds, 1);
    const cursor = plotLeft + fraction * plotWidth;
    context.strokeStyle = "#e85d3f";
    context.lineWidth = 2;
    context.beginPath();
    context.moveTo(cursor, 27);
    context.lineTo(cursor, 140);
    context.stroke();
    context.fillStyle = "#e85d3f";
    context.beginPath();
    context.arc(cursor, 24, 4, 0, Math.PI * 2);
    context.fill();
    updateReadout();
  }

  function synchronizeSensors() {
    [left, right].forEach((video) => {
      if (Math.abs(video.currentTime - scene.currentTime) > 0.12) {
        video.currentTime = scene.currentTime;
      }
    });
  }

  function animate() {
    synchronizeSensors();
    drawTimeline();
    if (!scene.paused && !scene.ended) animationFrame = requestAnimationFrame(animate);
  }

  function pauseAll() {
    videos.forEach((video) => video.pause());
    cancelAnimationFrame(animationFrame);
    drawTimeline();
  }

  function playAll() {
    synchronizeSensors();
    Promise.allSettled(videos.map((video) => video.play()));
    cancelAnimationFrame(animationFrame);
    animationFrame = requestAnimationFrame(animate);
  }

  function loadArm(name) {
    selected = name;
    arm = tactile.arms[selected];
    pauseAll();
    const sources = [arm.scene_video, arm.left.path, arm.right.path];
    const posters = [arm.scene_poster, arm.left.poster_path, arm.right.poster_path];
    videos.forEach((video, index) => {
      video.src = sources[index];
      video.poster = posters[index];
      video.load();
    });
    armButtons.forEach((button) => {
      const active = button.dataset.tactileArm === selected;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    detail.textContent = `${arm.frames} frames · ${arm.duration_seconds.toFixed(1)} s · ${tactile.timeline.sample_rate_hz} fps`;
    downloadLeft.href = arm.left.download_url;
    downloadLeft.download = arm.left.path.split("/").pop();
    downloadRight.href = arm.right.download_url;
    downloadRight.download = arm.right.path.split("/").pop();
    canvas.setAttribute("aria-label", `${arm.label}: timeline of left and right tactile marker contact gates`);
    drawTimeline();
  }

  armButtons.forEach((button) => {
    button.addEventListener("click", () => loadArm(button.dataset.tactileArm));
  });
  $("#restart-tactile").addEventListener("click", () => {
    videos.forEach((video) => {
      video.currentTime = 0;
    });
    playAll();
  });
  $("#play-tactile").addEventListener("click", playAll);
  $("#pause-tactile").addEventListener("click", pauseAll);
  scene.addEventListener("play", playAll);
  scene.addEventListener("pause", pauseAll);
  scene.addEventListener("seeking", () => {
    synchronizeSensors();
    drawTimeline();
  });
  scene.addEventListener("timeupdate", drawTimeline);
  canvas.addEventListener("click", (event) => {
    const bounds = canvas.getBoundingClientRect();
    const plotLeft = 70;
    const plotRight = bounds.width - 14;
    const fraction = Math.min(
      1,
      Math.max(0, (event.clientX - bounds.left - plotLeft) / (plotRight - plotLeft)),
    );
    scene.currentTime = fraction * arm.duration_seconds;
    synchronizeSensors();
    drawTimeline();
  });

  if ("ResizeObserver" in window) {
    new ResizeObserver(drawTimeline).observe(canvas);
  } else {
    window.addEventListener("resize", drawTimeline);
  }
  loadArm("rdp");
}

async function init() {
  try {
    const response = await fetch("./benchmark.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    renderMethods(data.methods);
    renderTasks(data.tasks);
    renderBootstrap(data.paired_difference);
    renderTreatment(data.treatment);
    renderProtocol(data);
    initVideoSwitcher();
    initComparisonPlayback();
    initTactileVisualization(data);
    $("#claim-boundary").textContent = data.claim_boundary;
  } catch (error) {
    document.body.prepend(
      element("div", "load-error", `Could not load the benchmark data: ${error.message}`),
    );
  }
}

init();
