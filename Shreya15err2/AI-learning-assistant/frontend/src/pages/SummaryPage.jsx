import { useState } from "react";
import { api } from "../utils/api";

export default function SummaryPage({ doc, hasDocs }) {
  const [length, setLength] = useState("medium");
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function generate() {
    setLoading(true); 
    setError(""); 
    setSummary(null);
    try {
      const res = await api.generateSummary(length, doc?.document_id);
      setSummary(res);
    } catch (e) { 
      setError(e.message || "Failed to generate summary."); 
    } finally { 
      setLoading(false); 
    }
  }

  return (
    <div>
      <div className="page-header">
        <div className="page-header-info">
          <h2>Summary</h2>
          <p>Get a concise summary and key takeaways from your educational materials</p>
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
            Please upload a PDF document in the sidebar to generate summaries.
          </div>
        )}

        {hasDocs && (
          <div className="card">
            <div className="card-header">
              <span className="card-title">⚙️ Summary Length</span>
            </div>
            <div style={{ display: "flex", gap: 10, marginBottom: 16 }}>
              {["short", "medium", "long"].map((l) => (
                <button 
                  key={l} 
                  className={`btn ${length === l ? "btn-primary" : "btn-secondary"}`} 
                  onClick={() => setLength(l)} 
                  style={{ textTransform: "capitalize", padding: "8px 20px" }}
                >
                  {l}
                </button>
              ))}
            </div>
            <button className="btn btn-primary" onClick={generate} disabled={loading}>
              {loading ? (
                <>
                  <div className="spinner" style={{ marginRight: 6 }} /> Generating Summary...
                </>
              ) : (
                "📋 Generate Summary"
              )}
            </button>
          </div>
        )}

        {error && <div className="error-box">{error}</div>}

        {summary && (
          <div className="summary-results">
            <div className="summary-box">
              <div style={{ marginBottom: 10, fontSize: 12, color: "var(--text3)", fontWeight: 500 }}>
                {summary.word_count} words
              </div>
              <p style={{ lineHeight: 1.8, fontSize: "14.5px" }}>{summary.summary}</p>
            </div>
            {summary.key_points && summary.key_points.length > 0 && (
              <div className="card">
                <div className="card-header">
                  <span className="card-title">📌 Key Takeaways</span>
                </div>
                <ul className="key-points">
                  {summary.key_points.map((p, i) => (
                    <li key={i}>{p}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
