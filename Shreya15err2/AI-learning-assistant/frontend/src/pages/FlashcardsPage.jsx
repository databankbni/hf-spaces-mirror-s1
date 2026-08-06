import { useState } from "react";
import { api } from "../utils/api";
import Flashcard from "../components/Flashcard";

export default function FlashcardsPage({ doc, hasDocs }) {
  const [numCards, setNumCards] = useState(10);
  const [cards, setCards] = useState(null);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [viewMode, setViewMode] = useState("navigate"); // "navigate" | "grid"
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function generate() {
    setLoading(true);
    setError("");
    setCards(null);
    setCurrentIndex(0);
    try {
      const res = await api.generateFlashcards(numCards, doc?.document_id);
      setCards(res);
    } catch (e) {
      setError(e.message || "Failed to generate flashcards.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <div className="page-header">
        <div className="page-header-info">
          <h2>Flashcards</h2>
          <p>Generate interactive study cards and flip to test your recall</p>
        </div>
        {hasDocs && (
          <div className={`focus-badge ${doc ? "focus-doc" : "focus-all"}`}>
            <span className="dot" />
            <span className="focus-label">
              Focus: {doc ? doc.filename : "All files"}
            </span>
          </div>
        )}
      </div>

      <div className="page-content">
        {!hasDocs && (
          <div className="error-box">
            Please upload a PDF document in the sidebar to generate flashcards.
          </div>
        )}

        {hasDocs && (
          <div className="card">
            <div className="card-header">
              <span className="card-title">⚙️ Settings</span>
            </div>
            <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "flex-end" }}>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label className="form-label">Number of flashcards</label>
                <select
                  id="flashcard-count-select"
                  className="form-select"
                  style={{ maxWidth: 200 }}
                  value={numCards}
                  onChange={(e) => setNumCards(+e.target.value)}
                >
                  {[5, 10, 15, 20].map((n) => (
                    <option key={n} value={n}>{n} cards</option>
                  ))}
                </select>
              </div>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label className="form-label">View mode</label>
                <select
                  id="flashcard-view-select"
                  className="form-select"
                  style={{ maxWidth: 200 }}
                  value={viewMode}
                  onChange={(e) => setViewMode(e.target.value)}
                >
                  <option value="navigate">Navigate one by one</option>
                  <option value="grid">Grid view (all cards)</option>
                </select>
              </div>
            </div>
            <button
              id="generate-flashcards-btn"
              className="btn btn-primary"
              style={{ marginTop: 16 }}
              onClick={generate}
              disabled={loading}
            >
              {loading ? (
                <>
                  <div className="spinner" style={{ marginRight: 6 }} /> Generating...
                </>
              ) : (
                "🃏 Generate Flashcards"
              )}
            </button>
          </div>
        )}

        {error && <div className="error-box">{error}</div>}

        {cards && (
          <>
            <div style={{ marginBottom: 16, fontSize: 13, color: "var(--text2)", fontWeight: 500 }}>
              {cards.total} flashcard{cards.total !== 1 ? "s" : ""} generated
              {viewMode === "navigate" ? " · use the buttons below to navigate" : " · click any card to flip it"}
            </div>

            {viewMode === "navigate" ? (
              <Flashcard
                cards={cards.flashcards}
                index={currentIndex}
                onPrev={() => setCurrentIndex((i) => Math.max(0, i - 1))}
                onNext={() => setCurrentIndex((i) => Math.min(cards.flashcards.length - 1, i + 1))}
              />
            ) : (
              <div className="flashcard-grid">
                {cards.flashcards.map((c, i) => (
                  <Flashcard key={i} card={c} />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
