import { useState } from "react";
import { api } from "../utils/api";

export default function QuizPage({ doc, hasDocs }) {
  const [config, setConfig] = useState({ num: 5, difficulty: "medium" });
  const [quiz, setQuiz] = useState(null);
  const [answers, setAnswers] = useState({});
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function generate() {
    setLoading(true); 
    setError(""); 
    setQuiz(null); 
    setAnswers({}); 
    setSubmitted(false);
    try {
      const res = await api.generateQuiz(config.num, config.difficulty, doc?.document_id);
      setQuiz(res);
    } catch (e) { 
      setError(e.message || "Failed to generate quiz."); 
    } finally { 
      setLoading(false); 
    }
  }

  function select(qi, opt) {
    if (submitted) return;
    setAnswers((a) => ({ ...a, [qi]: opt }));
  }

  const score = quiz ? quiz.questions.filter((q, i) => answers[i] === q.correct_answer).length : 0;
  const isButtonDisabled = Object.keys(answers).length < (quiz ? quiz.questions.length : 0);

  return (
    <div>
      <div className="page-header">
        <div className="page-header-info">
          <h2>Quiz Generator</h2>
          <p>Test your knowledge with AI-generated multiple-choice questions</p>
        </div>
        {hasDocs && (
          <div className={`focus-badge ${doc ? "focus-doc" : "focus-all"}`}>
            <span className="dot"></span>
            <span className="focus-label">
              Focus: {doc ? doc.filename : "All files"}
            </span>
          </div>
        )}
      </div>
      
      <div className="page-content">
        {!hasDocs && (
          <div className="error-box">
            Please upload a PDF document in the sidebar to generate quizzes.
          </div>
        )}

        {hasDocs && (
          <div className="card">
            <div className="card-header">
              <span className="card-title">⚙️ Quiz Configuration</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
              <div className="form-group">
                <label className="form-label">Number of questions</label>
                <select className="form-select" value={config.num} onChange={(e) => setConfig({ ...config, num: +e.target.value })}>
                  {[3, 5, 7, 10].map((n) => <option key={n} value={n}>{n} questions</option>)}
                </select>
              </div>
              <div className="form-group">
                <label className="form-label">Difficulty Level</label>
                <select className="form-select" value={config.difficulty} onChange={(e) => setConfig({ ...config, difficulty: e.target.value })}>
                  <option value="easy">Easy</option>
                  <option value="medium">Medium</option>
                  <option value="hard">Hard</option>
                </select>
              </div>
            </div>
            <button className="btn btn-primary" onClick={generate} disabled={loading}>
              {loading ? (
                <>
                  <div className="spinner" style={{ marginRight: 6 }} /> Generating Quiz...
                </>
              ) : (
                "🧠 Generate Quiz"
              )}
            </button>
          </div>
        )}

        {error && <div className="error-box">{error}</div>}

        {quiz && (
          <div className="quiz-results-container">
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
              <span style={{ fontSize: 14, color: "var(--text2)", fontWeight: 500 }}>
                {quiz.total} Questions · <span className="badge badge-purple" style={{ textTransform: "capitalize" }}>{quiz.difficulty}</span>
              </span>
              {submitted && (
                <span className={`badge ${score === quiz.total ? "badge-green" : "badge-amber"}`} style={{ fontSize: 13, padding: "4px 10px" }}>
                  Score: {score}/{quiz.total}
                </span>
              )}
            </div>

            {quiz.questions.map((q, qi) => (
              <div key={qi} className="quiz-question">
                <div className="quiz-q-text">
                  <span className="q-num">Q{qi + 1}.</span> {q.question}
                </div>
                <div className="quiz-options">
                  {q.options.map((opt) => {
                    let cls = "";
                    if (answers[qi] === opt) cls = "selected";
                    if (submitted) {
                      if (opt === q.correct_answer) cls = "correct";
                      else if (answers[qi] === opt) cls = "wrong";
                    }
                    return (
                      <button key={opt} className={`quiz-option ${cls}`} onClick={() => select(qi, opt)}>
                        {opt}
                      </button>
                    );
                  })}
                </div>
                {submitted && q.explanation && (
                  <div className="quiz-explanation">
                    <strong>Explanation:</strong> {q.explanation}
                  </div>
                )}
              </div>
            ))}

            {!submitted ? (
              <button 
                className="btn btn-primary" 
                onClick={() => setSubmitted(true)} 
                disabled={isButtonDisabled}
                style={{ marginTop: 10 }}
              >
                Submit Answers
              </button>
            ) : (
              <button 
                className="btn btn-secondary" 
                onClick={() => { setQuiz(null); setAnswers({}); setSubmitted(false); }}
                style={{ marginTop: 10 }}
              >
                Generate Another Quiz
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
