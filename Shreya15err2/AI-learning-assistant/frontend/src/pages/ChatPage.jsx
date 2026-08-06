import { useState, useRef, useEffect } from "react";
import { api } from "../utils/api";

function Message({ msg }) {
  const [showSources, setShowSources] = useState(false);
  const isUser = msg.role === "user";

  return (
    <div className={`message ${isUser ? "user" : "ai"}`}>
      <div className="msg-avatar">{isUser ? "👤" : "🤖"}</div>
      <div className="msg-content-wrapper">
        <div className="msg-bubble">
          {msg.loading ? (
            <div className="typing-dots">
              <span /><span /><span />
            </div>
          ) : (
            <div className="markdown-content" style={{ whiteSpace: "pre-line" }}>
              {msg.content}
            </div>
          )}
        </div>
        {!isUser && msg.sources && msg.sources.length > 0 && !msg.loading && (
          <>
            <button className="sources-toggle" onClick={() => setShowSources(!showSources)}>
              📎 Cites {msg.sources.length} reference{msg.sources.length > 1 ? "s" : ""} {showSources ? "▲" : "▼"}
            </button>
            {showSources && (
              <div className="sources-list">
                {msg.sources.map((s, i) => (
                  <div key={i} className="source-chip">
                    <span className="source-chip-meta">
                      <strong>{s.filename}</strong> · Page {s.page} · {(s.similarity * 100).toFixed(0)}% Match
                    </span>
                    <div className="source-chip-preview">{s.preview}</div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
        {!isUser && msg.model_used && !msg.loading && (
          <div className="msg-model-tag">
            via {msg.model_used}
          </div>
        )}
      </div>
    </div>
  );
}

export default function ChatPage({ doc, hasDocs, messages, setMessages }) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  // Default to Fast Direct Search (true) for sub-second responses
  const [directSearch, setDirectSearch] = useState(true);
  const bottomRef = useRef();

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function send() {
    const q = input.trim();
    if (!q || loading) return;
    setInput("");
    
    setMessages((m) => [...m, { role: "user", content: q }]);
    setMessages((m) => [...m, { role: "ai", content: "", loading: true }]);
    setLoading(true);
    
    try {
      const res = await api.askQuestion(q, doc?.document_id, 5, directSearch);
      setMessages((m) => {
        const updated = [...m];
        updated[updated.length - 1] = {
          role: "ai",
          content: res.answer,
          sources: res.sources,
          model_used: res.model_used,
          loading: false,
        };
        return updated;
      });
    } catch (e) {
      setMessages((m) => {
        const updated = [...m];
        updated[updated.length - 1] = {
          role: "ai",
          content: `Error: ${e.message || "Failed to communicate with server."}`,
          loading: false,
        };
        return updated;
      });
    } finally {
      setLoading(false);
    }
  }

  const focusText = doc 
    ? `Focused on: ${doc.filename}` 
    : hasDocs 
      ? "Searching all uploaded materials" 
      : "Upload a document to get started";

  return (
    <div className="chat-container">
      <div className="page-header">
        <div className="page-header-info">
          <h2>Ask Questions</h2>
          <p>Get answers with direct page references</p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          {hasDocs && (
            <label className="direct-search-toggle" style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--text-secondary)", cursor: "pointer", fontWeight: 600, background: "rgba(255, 255, 255, 0.03)", padding: "6px 12px", borderRadius: "var(--radius-pill)", border: "1px solid var(--border-color)" }}>
              <input 
                type="checkbox" 
                checked={directSearch} 
                onChange={(e) => setDirectSearch(e.target.checked)} 
                style={{ accentColor: "var(--accent)", cursor: "pointer" }}
              />
              ⚡ Fast Direct Search
            </label>
          )}
          <div className={`focus-badge ${doc ? "focus-doc" : hasDocs ? "focus-all" : "focus-none"}`}>
            <span className="dot"></span>
            <span className="focus-label">{focusText}</span>
          </div>
        </div>
      </div>
      
      <div className="chat-messages">
        {messages.map((m, i) => <Message key={i} msg={m} />)}
        <div ref={bottomRef} />
      </div>

      <div className="chat-input-area">
        <div className="chat-input-row">
          <textarea
            rows={1}
            placeholder={
              hasDocs 
                ? doc 
                  ? `Ask a question about "${doc.filename}"...` 
                  : "Ask a question across all study materials..."
                : "Please upload a PDF in the sidebar first..."
            }
            value={input}
            disabled={!hasDocs || loading}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { 
                e.preventDefault(); 
                send(); 
              }
            }}
          />
          <button 
            className="send-btn" 
            onClick={send} 
            disabled={!hasDocs || loading || !input.trim()}
          >
            {loading ? <div className="spinner" style={{ width: 14, height: 14 }} /> : "↑"}
          </button>
        </div>
      </div>
    </div>
  );
}
