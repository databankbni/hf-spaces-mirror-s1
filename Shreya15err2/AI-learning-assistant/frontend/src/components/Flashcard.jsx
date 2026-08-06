import { useState } from "react";

/**
 * Standalone Flashcard component with 3D flip animation.
 * Supports standalone use (just pass `card`) or navigable mode
 * (pass `cards`, `index`, `onPrev`, `onNext`).
 */
export default function Flashcard({ card, cards, index, onPrev, onNext }) {
  const [flipped, setFlipped] = useState(false);

  // Reset flip when card changes
  const total = cards ? cards.length : null;
  const current = card || (cards && cards[index]);

  if (!current) return null;

  function handleFlip() {
    setFlipped((f) => !f);
  }

  return (
    <div className="flashcard-wrapper">
      {/* Progress indicator (only in navigable mode) */}
      {total !== null && (
        <div className="flashcard-progress">
          <span className="flashcard-progress-text">
            Card <strong>{index + 1}</strong> of <strong>{total}</strong>
          </span>
          <div className="flashcard-progress-bar">
            <div
              className="flashcard-progress-fill"
              style={{ width: `${((index + 1) / total) * 100}%` }}
            />
          </div>
        </div>
      )}

      {/* Card */}
      <div
        className={`flashcard ${flipped ? "flipped" : ""}`}
        onClick={handleFlip}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => e.key === "Enter" && handleFlip()}
        aria-label={flipped ? "Show question" : "Show answer"}
      >
        <div className="flashcard-inner">
          <div className="flashcard-front">
            <div className="flashcard-label">Question</div>
            <div className="flashcard-text">{current.front}</div>
            {current.topic && (
              <div className="flashcard-topic">{current.topic}</div>
            )}
            <div className="flashcard-flip-hint">Tap to reveal answer 🔄</div>
          </div>
          <div className="flashcard-back">
            <div className="flashcard-label">Answer</div>
            <div className="flashcard-text">{current.back}</div>
            {current.topic && (
              <div className="flashcard-topic">{current.topic}</div>
            )}
            <div className="flashcard-flip-hint">Tap to see question 🔄</div>
          </div>
        </div>
      </div>

      {/* Navigation (only in navigable mode) */}
      {total !== null && (
        <div className="flashcard-nav">
          <button
            id="flashcard-prev-btn"
            className="flashcard-nav-btn"
            onClick={() => { setFlipped(false); onPrev(); }}
            disabled={index === 0}
            aria-label="Previous card"
          >
            ← Previous
          </button>
          <span className="flashcard-nav-dots">
            {cards.map((_, i) => (
              <span
                key={i}
                className={`flashcard-dot ${i === index ? "active" : ""}`}
              />
            ))}
          </span>
          <button
            id="flashcard-next-btn"
            className="flashcard-nav-btn"
            onClick={() => { setFlipped(false); onNext(); }}
            disabled={index === total - 1}
            aria-label="Next card"
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}

