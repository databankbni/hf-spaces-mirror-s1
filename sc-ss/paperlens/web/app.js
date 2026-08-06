let lastAnswer = null;

const sampleQuestions = [
  "What is self-attention and why is it useful?",
  "What is masked language modeling in BERT?",
  "What is next sentence prediction in BERT?",
  "How does retrieval augmented generation use external knowledge?",
  "What is the role of the retriever in RAG?",
  "How does LoRA reduce the number of trainable parameters?",
  "What parameters are trained in LoRA?",
  "Why does chain-of-thought prompting improve reasoning?",
];

const statusEl = document.getElementById("status");
const statusDot = document.getElementById("statusDot");
const paperListEl = document.getElementById("paperList");
const questionEl = document.getElementById("question");
const answerCard = document.getElementById("answerCard");
const loadingCard = document.getElementById("loadingCard");
const answerText = document.getElementById("answerText");
const strengthBadge = document.getElementById("strengthBadge");
const citationsEl = document.getElementById("citations");
const evidenceEl = document.getElementById("evidence");
const searchButton = document.getElementById("searchButton");
const charCounter = document.getElementById("charCounter");
const copyStatus = document.getElementById("copyStatus");
const recentQuestionsEl = document.getElementById("recentQuestions");

function recentQuestions() {
  return JSON.parse(localStorage.getItem("paperlensRecentQuestions") || "[]");
}

function saveRecentQuestion(question) {
  const next = [question, ...recentQuestions().filter((item) => item !== question)].slice(0, 6);
  localStorage.setItem("paperlensRecentQuestions", JSON.stringify(next));
  renderRecentQuestions();
}

function renderRecentQuestions() {
  const questions = recentQuestions();
  recentQuestionsEl.innerHTML = "";

  if (!questions.length) {
    recentQuestionsEl.innerHTML = `<p class="side-note">Your recent questions will appear here.</p>`;
    return;
  }

  questions.forEach((question) => {
    const button = document.createElement("button");
    button.className = "recent-question";
    button.textContent = question;
    button.addEventListener("click", () => {
      questionEl.value = question;
      updateCharCounter();
      questionEl.focus();
    });
    recentQuestionsEl.appendChild(button);
  });
}

async function loadStatus() {
  const response = await fetch("/api/health");
  const data = await response.json();

  if (data.ready) {
    statusEl.textContent = `${data.paper_count} papers · ${data.chunk_count} chunks`;
    statusDot.classList.add("ready");
  } else {
    statusEl.textContent = "Index not ready";
    statusDot.classList.remove("ready");
  }
}

async function loadPapers() {
  const response = await fetch("/api/papers");
  const data = await response.json();

  paperListEl.innerHTML = "";

  data.papers.forEach((paper) => {
    const label = document.createElement("label");
    label.className = "paper-item";
    label.innerHTML = `<input type="checkbox" checked value="${paper}" /> <span>${paper}</span>`;
    paperListEl.appendChild(label);
  });
}

function selectedPapers() {
  return Array.from(paperListEl.querySelectorAll("input:checked")).map((input) => input.value);
}

function setAllPapers(checked) {
  paperListEl.querySelectorAll("input").forEach((input) => {
    input.checked = checked;
  });
}

function searchMode() {
  return document.querySelector("input[name='searchMode']:checked").value;
}

function updateCharCounter() {
  charCounter.textContent = `${questionEl.value.length} / 500`;
}

function setLoading(isLoading) {
  searchButton.disabled = isLoading;
  searchButton.textContent = isLoading ? "Finding evidence..." : "Find Evidence";

  if (isLoading) {
    loadingCard.classList.remove("hidden");
    answerCard.classList.add("hidden");
    statusEl.textContent = "Reranking passages...";
    statusDot.classList.remove("ready");
  } else {
    loadingCard.classList.add("hidden");
  }
}

function showError(message) {
  answerCard.classList.remove("hidden");
  answerText.textContent = message;
  strengthBadge.className = "badge weak";
  strengthBadge.textContent = "Evidence: unavailable";
  citationsEl.innerHTML = "";
  evidenceEl.innerHTML = "";
}

async function search() {
  const question = questionEl.value.trim();
  const papers = selectedPapers();

  if (!question) {
    questionEl.focus();
    showError("Ask a question to begin.");
    return;
  }

  if (papers.length === 0) {
    showError("Select at least one paper to search.");
    return;
  }

  setLoading(true);

  try {
    const response = await fetch("/api/search", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        question,
        paper_titles: papers,
        search_mode: searchMode(),
      }),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "Search failed.");
    }

    const data = await response.json();
    lastAnswer = data;
    saveRecentQuestion(question);
    renderAnswer(data);
  } catch (error) {
    showError(error.message || "Something went wrong while searching. Please try again.");
  } finally {
    setLoading(false);
    await loadStatus();
  }
}

function badgeClass(strength) {
  if (strength === "weak") return "badge weak";
  if (strength === "moderate") return "badge moderate";
  return "badge";
}

function renderAnswer(data) {
  answerCard.classList.remove("hidden");
  answerText.textContent = data.answer;

  strengthBadge.className = badgeClass(data.evidence_strength);
  strengthBadge.textContent = `Evidence: ${data.evidence_strength}`;

  citationsEl.innerHTML = "";
  if (!data.citations.length) {
    citationsEl.innerHTML = `<div class="citation-card">No citations found for this question.</div>`;
  }

  data.citations.forEach((citation) => {
    const card = document.createElement("div");
    card.className = "citation-card";
    card.innerHTML = `
      <strong>${citation.paper_title}</strong>
      <span class="page-pill">Page ${citation.page_number}</span>
    `;
    citationsEl.appendChild(card);
  });

  evidenceEl.innerHTML = "";
  data.evidence.forEach((chunk, index) => {
    const scores = [];
    scores.push(`Search ${Number(chunk.search_score || 0).toFixed(3)}`);

    if (chunk.keyword_score !== null && chunk.keyword_score !== undefined) {
      scores.push(`Keyword ${Number(chunk.keyword_score).toFixed(3)}`);
    }

    if (chunk.rrf_score !== null && chunk.rrf_score !== undefined) {
      scores.push(`RRF ${Number(chunk.rrf_score).toFixed(4)}`);
    }

    if (chunk.rerank_score !== null && chunk.rerank_score !== undefined) {
      scores.push(`Rerank ${Number(chunk.rerank_score).toFixed(3)}`);
    }

    const card = document.createElement("div");
    card.className = "evidence-card";
    card.innerHTML = `
      <strong>${index + 1}. ${chunk.paper_title}, page ${chunk.page_number}</strong>
      <p>${chunk.text}</p>
      <div class="score-row">
        ${scores.map((score) => `<span class="score-chip">${score}</span>`).join("")}
      </div>
    `;
    evidenceEl.appendChild(card);
  });
}

function answerReport() {
  if (!lastAnswer) return "";

  return [
    `Question: ${lastAnswer.question}`,
    `Search mode: ${searchMode()}`,
    "",
    "Answer:",
    lastAnswer.answer,
    "",
    `Evidence strength: ${lastAnswer.evidence_strength}`,
    "",
    "Citations:",
    ...lastAnswer.citations.map((citation) => `- ${citation.citation}`),
    "",
    "Evidence:",
    ...lastAnswer.evidence.map((chunk, index) => (
      `${index + 1}. ${chunk.paper_title}, page ${chunk.page_number}\n${chunk.text}`
    )),
  ].join("\n");
}

searchButton.addEventListener("click", search);

questionEl.addEventListener("input", updateCharCounter);

questionEl.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    search();
  }
});

document.getElementById("clearButton").addEventListener("click", () => {
  questionEl.value = "";
  updateCharCounter();
  questionEl.focus();
});

document.getElementById("randomButton").addEventListener("click", () => {
  const question = sampleQuestions[Math.floor(Math.random() * sampleQuestions.length)];
  questionEl.value = question;
  updateCharCounter();
  questionEl.focus();
});

document.getElementById("selectAllPapers").addEventListener("click", () => {
  setAllPapers(true);
});

document.getElementById("clearPapers").addEventListener("click", () => {
  setAllPapers(false);
});

document.querySelectorAll("[data-question]").forEach((button) => {
  button.addEventListener("click", () => {
    questionEl.value = button.dataset.question;
    updateCharCounter();
    questionEl.focus();
  });
});

document.getElementById("copyButton").addEventListener("click", async () => {
  const text = answerReport();

  if (!text) return;

  await navigator.clipboard.writeText(text);
  copyStatus.classList.remove("hidden");

  setTimeout(() => {
    copyStatus.classList.add("hidden");
  }, 1800);
});

document.getElementById("downloadButton").addEventListener("click", () => {
  const text = answerReport();

  if (!text) return;

  const blob = new Blob([text], { type: "text/plain" });
  const url = URL.createObjectURL(blob);

  const link = document.createElement("a");
  link.href = url;
  link.download = "paperlens-answer.txt";
  link.click();

  URL.revokeObjectURL(url);
});

updateCharCounter();
renderRecentQuestions();
loadStatus();
loadPapers();