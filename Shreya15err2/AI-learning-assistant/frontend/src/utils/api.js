const BASE_URL = "/api";

function getAuthHeaders() {
  const token = localStorage.getItem("ai_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request(endpoint, options = {}) {
  const res = await fetch(`${BASE_URL}${endpoint}`, {
    headers: {
      "Content-Type": "application/json",
      ...getAuthHeaders(),
      ...options.headers,
    },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(err.detail || "Unknown error");
  }
  return res.json();
}

export const api = {
  uploadPDF: (file) => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`${BASE_URL}/upload`, { method: "POST", body: form }).then(
      async (r) => {
        if (!r.ok) {
          const e = await r.json().catch(() => ({ detail: "Upload failed" }));
          throw new Error(e.detail || "Upload failed");
        }
        return r.json();
      }
    );
  },
  
  getDocuments: () =>
    request("/documents", { method: "GET" }),
    
  deleteDocument: (documentId) =>
    request(`/documents/${documentId}`, { method: "DELETE" }),

  askQuestion: (question, documentId, topK = 5, directRetrieval = false) =>
    request("/ask", {
      method: "POST",
      body: JSON.stringify({ 
        question, 
        document_id: documentId, 
        top_k: topK,
        direct_retrieval: directRetrieval
      }),
    }),

  generateQuiz: (numQuestions = 5, difficulty = "medium", documentId) =>
    request("/generate-quiz", {
      method: "POST",
      body: JSON.stringify({ num_questions: numQuestions, difficulty, document_id: documentId }),
    }),

  generateFlashcards: (numCards = 10, documentId) =>
    request("/flashcards", {
      method: "POST",
      body: JSON.stringify({ num_cards: numCards, document_id: documentId }),
    }),

  generateSummary: (length = "medium", documentId) =>
    request("/summary", {
      method: "POST",
      body: JSON.stringify({ length, document_id: documentId }),
    }),

  createStudyPlan: (examDate, hoursPerDay, subjects, difficultyLevel) =>
    request("/study-plan", {
      method: "POST",
      body: JSON.stringify({
        exam_date: examDate,
        hours_per_day: hoursPerDay,
        subjects,
        difficulty_level: difficultyLevel,
      }),
    }),
};
