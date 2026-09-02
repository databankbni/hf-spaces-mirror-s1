// ---------------- State ----------------
const state = {
  rawChallenges: [], // as loaded from data/challenges.json, bilingual, unlocalized
  challenges: [], // localized for the current language
  currentChallenge: null,
  currentHintIndex: -1,
  lastResult: null,
  challengeCounter: 0,
};

const STORAGE_KEY = "promptChallenge.progress.v1";

// ---------------- Progress storage ----------------
function loadProgress() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { attempts: [] };
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed.attempts)) return { attempts: [] };
    return parsed;
  } catch (e) {
    return { attempts: [] };
  }
}

function saveAttempt(challenge, score) {
  const progress = loadProgress();
  progress.attempts.push({
    challengeId: challenge.id,
    title: challenge.title,
    category: challenge.category,
    score,
    date: new Date().toISOString(),
  });
  localStorage.setItem(STORAGE_KEY, JSON.stringify(progress));
}

// ---------------- Navigation ----------------
function showView(name) {
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  const el = document.getElementById(`view-${name}`);
  if (el) el.classList.add("active");
  if (name === "progress") renderProgress();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

document.querySelectorAll("[data-nav]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const target = btn.getAttribute("data-nav");
    if (target === "challenge" && !state.currentChallenge) {
      startChallenge();
    } else {
      showView(target);
    }
  });
});

// ---------------- Data loading (static JSON, no backend required) ----------------
function localizeChallenge(raw, lang) {
  return {
    id: raw.id,
    category: raw.category,
    difficulty: raw.difficulty,
    title: raw.title[lang] || raw.title.en,
    task: raw.task[lang] || raw.task.en,
    hints: raw.hints[lang] || raw.hints.en,
    useful_elements: raw.useful_elements || [],
  };
}

async function fetchChallenges() {
  if (!state.rawChallenges.length) {
    const res = await fetch("assets/data/challenges.json");
    if (!res.ok) throw new Error("Failed to load challenges");
    state.rawChallenges = await res.json();
  }
  const lang = getLang();
  return state.rawChallenges.map((c) => localizeChallenge(c, lang));
}

function findChallengeById(id) {
  const raw = state.rawChallenges.find((c) => c.id === id);
  return raw ? localizeChallenge(raw, getLang()) : null;
}

// ---------------- Evaluation (Worker if configured, otherwise the FastAPI backend) ----------------
async function evaluatePrompt(challenge, prompt) {
  const usingWorker = typeof EVAL_WORKER_URL === "string" && EVAL_WORKER_URL && !EVAL_WORKER_URL.includes("YOUR-SUBDOMAIN");
  const url = usingWorker ? EVAL_WORKER_URL : "/api/evaluate";
  const body = usingWorker
    ? {
        category: challenge.category,
        difficulty: challenge.difficulty,
        task: challenge.task,
        useful_elements: challenge.useful_elements,
        prompt,
        lang: getLang(),
      }
    : { challenge_id: challenge.id, prompt, lang: getLang() };

  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = "Something went wrong evaluating your prompt.";
    try {
      const err = await res.json();
      if (err.detail) detail = err.detail;
    } catch (e) {}
    throw new Error(detail);
  }
  return res.json();
}

// ---------------- Challenge flow ----------------
function pickRandomChallenge(pool) {
  return pool[Math.floor(Math.random() * pool.length)];
}

function currentUserLevelPool() {
  const progress = loadProgress();
  const completed = progress.attempts.length;
  if (completed < 5) return state.challenges.filter((c) => c.difficulty === "beginner");
  if (completed < 15) return state.challenges.filter((c) => c.difficulty !== "challenge");
  return state.challenges;
}

async function ensureChallengesLoaded() {
  if (state.challenges.length) return;
  state.challenges = await fetchChallenges();
}

async function startChallenge(surpriseAnyCategory) {
  showView("challenge");
  toggleChallengeLoading(true);
  try {
    await ensureChallengesLoaded();
    const pool = surpriseAnyCategory ? state.challenges : currentUserLevelPool();
    const chosen = pickRandomChallenge(pool.length ? pool : state.challenges);
    loadChallenge(chosen);
  } catch (e) {
    showEmptyChallengeState();
  } finally {
    toggleChallengeLoading(false);
  }
}

function toggleChallengeLoading(isLoading) {
  document.getElementById("challenge-loading").hidden = !isLoading;
  document.getElementById("challenge-content").hidden = isLoading;
  document.getElementById("challenge-empty").hidden = true;
}

function showEmptyChallengeState() {
  document.getElementById("challenge-content").hidden = true;
  document.getElementById("challenge-empty").hidden = false;
}

function loadChallenge(challenge) {
  state.currentChallenge = challenge;
  state.currentHintIndex = -1;
  state.lastResult = null;
  state.challengeCounter += 1;

  document.getElementById("challenge-number").textContent = t("challenge_number")(state.challengeCounter);
  document.getElementById("challenge-category").textContent =
    (t("category_names")[challenge.category] || challenge.category).toUpperCase();
  document.getElementById("challenge-title").textContent = challenge.title;
  document.getElementById("challenge-task").textContent = challenge.task;

  const diffEl = document.getElementById("challenge-difficulty");
  diffEl.textContent = (t("difficulty_names")[challenge.difficulty] || challenge.difficulty).toUpperCase();
  diffEl.className = "chip chip-difficulty " + challenge.difficulty;

  document.getElementById("prompt-input").value = "";
  document.getElementById("hint-box").hidden = true;
  document.getElementById("results-panel").hidden = true;
  document.getElementById("evaluate-error").hidden = true;
  document.getElementById("example-panel").hidden = true;
  document.getElementById("btn-hint").disabled = false;

  document.getElementById("challenge-content").hidden = false;
}

// ---------------- Hints ----------------
document.getElementById("btn-hint").addEventListener("click", () => {
  if (!state.currentChallenge) return;
  const hints = state.currentChallenge.hints || [];
  const nextIndex = state.currentHintIndex + 1;
  const box = document.getElementById("hint-box");
  const textEl = document.getElementById("hint-text");
  const btn = document.getElementById("btn-hint");

  if (nextIndex >= hints.length) {
    textEl.textContent = t("no_more_hints");
    box.hidden = false;
    btn.disabled = true;
    return;
  }

  state.currentHintIndex = nextIndex;
  textEl.textContent = hints[nextIndex];
  box.hidden = false;
  if (nextIndex + 1 >= hints.length) {
    btn.disabled = true;
  }
});

// ---------------- Evaluate ----------------
document.getElementById("btn-evaluate").addEventListener("click", () => runEvaluation());
document.getElementById("btn-retry-evaluate").addEventListener("click", () => runEvaluation());

async function runEvaluation() {
  const promptText = document.getElementById("prompt-input").value.trim();
  if (!promptText) {
    alert(t("write_prompt_alert"));
    return;
  }

  document.getElementById("evaluate-error").hidden = true;
  document.getElementById("results-panel").hidden = true;
  document.getElementById("evaluating-state").hidden = false;
  document.getElementById("btn-evaluate").disabled = true;

  try {
    const result = await evaluatePrompt(state.currentChallenge, promptText);
    state.lastResult = result;
    state.lastUserPrompt = promptText;
    saveAttempt(state.currentChallenge, result.score);
    renderResults(result, promptText);
  } catch (e) {
    document.getElementById("evaluate-error-text").textContent = e.message;
    document.getElementById("evaluate-error").hidden = false;
  } finally {
    document.getElementById("evaluating-state").hidden = true;
    document.getElementById("btn-evaluate").disabled = false;
  }
}

function renderResults(result, userPrompt) {
  document.getElementById("result-score").textContent = result.score;
  document.getElementById("result-level").textContent = t("level_names")[result.level] || result.level;
  document.getElementById("result-short-feedback").textContent = result.short_feedback;

  fillList("result-strengths", result.strengths, t("empty_strengths"));
  fillList("result-missing", result.missing, t("empty_missing"));
  fillList("result-suggestions", result.suggestions, t("empty_suggestions"));

  document.getElementById("example-panel").hidden = true;
  document.getElementById("example-user-prompt").textContent = userPrompt;
  document.getElementById("example-strong-prompt").textContent = result.example_prompt || "";
  document.getElementById("example-why").textContent = result.why_example_is_better || "";

  document.getElementById("results-panel").hidden = false;
  document.getElementById("results-panel").scrollIntoView({ behavior: "smooth", block: "start" });
}

function fillList(elementId, items, emptyText) {
  const el = document.getElementById(elementId);
  el.innerHTML = "";
  const list = Array.isArray(items) ? items : [];
  if (!list.length) {
    const li = document.createElement("li");
    li.textContent = emptyText;
    li.style.opacity = "0.7";
    el.appendChild(li);
    return;
  }
  list.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    el.appendChild(li);
  });
}

document.getElementById("btn-show-example").addEventListener("click", () => {
  const panel = document.getElementById("example-panel");
  panel.hidden = !panel.hidden;
});

document.getElementById("btn-try-again").addEventListener("click", () => {
  document.getElementById("results-panel").hidden = true;
  document.getElementById("prompt-input").focus();
  document.getElementById("challenge-content").scrollIntoView({ behavior: "smooth", block: "start" });
});

document.getElementById("btn-next-challenge").addEventListener("click", () => startChallenge(false));
document.getElementById("btn-new-challenge").addEventListener("click", () => startChallenge(false));

// ---------------- Landing actions ----------------
document.getElementById("btn-start-challenge").addEventListener("click", () => startChallenge(false));
document.getElementById("btn-random-challenge").addEventListener("click", () => startChallenge(true));
document.getElementById("btn-progress-start")?.addEventListener("click", () => startChallenge(false));

// ---------------- Progress view ----------------
function renderProgress() {
  const progress = loadProgress();
  const attempts = progress.attempts;

  if (!attempts.length) {
    document.getElementById("progress-empty").hidden = false;
    document.getElementById("progress-content").hidden = true;
    return;
  }
  document.getElementById("progress-empty").hidden = true;
  document.getElementById("progress-content").hidden = false;

  const completed = attempts.length;
  const avg = Math.round(attempts.reduce((s, a) => s + a.score, 0) / completed);
  const best = Math.max(...attempts.map((a) => a.score));
  const streak = computeStreak(attempts);

  document.getElementById("stat-completed").textContent = completed;
  document.getElementById("stat-average").textContent = avg;
  document.getElementById("stat-best").textContent = best;
  document.getElementById("stat-streak").textContent = streak;

  renderCategoryBars(attempts);
  renderRecentAttempts(attempts);
}

function computeStreak(attempts) {
  // Streak = consecutive most-recent attempts scoring 50+ ("Good Start" or better).
  let streak = 0;
  for (let i = attempts.length - 1; i >= 0; i--) {
    if (attempts[i].score >= 50) streak += 1;
    else break;
  }
  return streak;
}

function renderCategoryBars(attempts) {
  const counts = {};
  attempts.forEach((a) => {
    counts[a.category] = (counts[a.category] || 0) + 1;
  });
  const max = Math.max(...Object.values(counts));
  const container = document.getElementById("category-bars");
  container.innerHTML = "";
  const categoryNames = t("category_names");

  Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .forEach(([category, count]) => {
      const row = document.createElement("div");
      row.className = "category-bar-row";
      const label = categoryNames[category] || category;
      row.innerHTML = `
        <div class="category-bar-name">${label}</div>
        <div class="category-bar-track"><div class="category-bar-fill" style="width:${(count / max) * 100}%"></div></div>
        <div class="category-bar-count">${count}</div>
      `;
      container.appendChild(row);
    });
}

function renderRecentAttempts(attempts) {
  const container = document.getElementById("recent-attempts");
  container.innerHTML = "";
  const recent = attempts.slice(-8).reverse();
  const categoryNames = t("category_names");
  recent.forEach((a) => {
    const row = document.createElement("div");
    row.className = "recent-attempt-row";
    const date = new Date(a.date);
    const label = categoryNames[a.category] || a.category;
    row.innerHTML = `
      <div>
        <div class="recent-attempt-title">${a.title}</div>
        <div class="recent-attempt-date">${date.toLocaleDateString()} · ${label}</div>
      </div>
      <div class="recent-attempt-score">${a.score}</div>
    `;
    container.appendChild(row);
  });
}

// ---------------- Language change ----------------
function onLangChanged() {
  state.challenges = [];
  if (state.currentChallenge) {
    const refreshed = findChallengeById(state.currentChallenge.id);
    if (refreshed) {
      const keepPrompt = document.getElementById("prompt-input").value;
      const keepCounter = state.challengeCounter;
      loadChallenge(refreshed);
      state.challengeCounter = keepCounter; // re-displaying the same challenge shouldn't advance the counter
      document.getElementById("challenge-number").textContent = t("challenge_number")(state.challengeCounter);
      document.getElementById("prompt-input").value = keepPrompt;
    }
  }
  if (document.getElementById("view-progress").classList.contains("active")) {
    renderProgress();
  }
}

// ---------------- Init ----------------
showView("landing");
