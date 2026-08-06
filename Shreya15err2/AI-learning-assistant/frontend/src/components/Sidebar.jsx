import { useState, useRef } from "react";
import { api } from "../utils/api";

const NAV_ITEMS = [
  { id: "chat", icon: "💬", label: "Ask Questions" },
  { id: "summary", icon: "📋", label: "Summary" },
  { id: "quiz", icon: "🧠", label: "Quiz Generator" },
  { id: "flashcards", icon: "🃏", label: "Flashcards" },
  { id: "studyplan", icon: "📅", label: "Study Planner" },
];

export default function Sidebar({
  activePage,
  onNavigate,
  uploadedDoc,
  onSelectDoc,
  documents,
  onRefreshDocs,
  onDeleteDoc,
  username,
  onLogout,
}) {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const fileRef = useRef();

  async function handleFile(file) {
    if (!file || !file.name.endsWith(".pdf")) {
      setError("Only PDF files are supported.");
      return;
    }
    setUploading(true);
    setError("");
    try {
      const result = await api.uploadPDF(file);
      await onRefreshDocs();
      onSelectDoc(result); // Select the newly uploaded document
    } catch (e) {
      setError(e.message || "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <h1>AI <span>Study Assistant</span></h1>
        <p>Analyze documents, generate quizzes & plans</p>
      </div>

      <div className="sidebar-upload">
        <div
          className={`upload-zone ${dragging ? "drag-over" : ""}`}
          onClick={() => !uploading && fileRef.current.click()}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            const f = e.dataTransfer.files[0];
            if (f) handleFile(f);
          }}
        >
          <div className="icon">{uploading ? "⏳" : "📁"}</div>
          <p>
            {uploading
              ? "Extracting PDF text..."
              : <><strong>Click or drag-drop</strong><br />any PDF file here</>}
          </p>
          <input
            ref={fileRef}
            type="file"
            accept=".pdf"
            onChange={(e) => handleFile(e.target.files[0])}
          />
        </div>

        {error && <div className="error-box" style={{ marginTop: 8, fontSize: 11 }}>{error}</div>}
      </div>

      <div className="sidebar-library">
        <div className="nav-section-label">Study Library</div>
        <div className="library-list">
          {documents.length > 0 && (
            <button
              className={`library-item ${!uploadedDoc ? "active" : ""}`}
              onClick={() => onSelectDoc(null)}
            >
              <span className="library-icon">🌐</span>
              <span className="library-label">Search All Files</span>
            </button>
          )}

          {documents.map((doc) => {
            const isSelected = uploadedDoc && uploadedDoc.document_id === doc.document_id;
            return (
              <div
                key={doc.document_id}
                className={`library-item-wrapper ${isSelected ? "selected" : ""}`}
              >
                <button
                  className="library-item-btn"
                  onClick={() => onSelectDoc(doc)}
                  title={doc.filename}
                >
                  <span className="library-icon">📄</span>
                  <span className="library-label">{doc.filename}</span>
                </button>
                <button
                  className="library-delete-btn"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteDoc(doc.document_id);
                  }}
                  title="Delete document"
                >
                  ✕
                </button>
              </div>
            );
          })}

          {documents.length === 0 && (
            <div className="library-empty">
              No documents uploaded yet.
            </div>
          )}
        </div>
      </div>

      <nav className="sidebar-nav">
        <div className="nav-section-label">Tools</div>
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            className={`nav-item ${activePage === item.id ? "active" : ""}`}
            onClick={() => onNavigate(item.id)}
          >
            <span className="nav-icon">{item.icon}</span>
            {item.label}
          </button>
        ))}
      </nav>

      <div className="sidebar-footer">
        {username && (
          <div className="sidebar-user">
            <span className="sidebar-user-avatar">{username[0].toUpperCase()}</span>
            <span className="sidebar-user-name">{username}</span>
            <button
              id="logout-btn"
              className="sidebar-logout-btn"
              onClick={onLogout}
              title="Sign out"
            >
              ⏏ Sign out
            </button>
          </div>
        )}
        <div className="sidebar-powered">Powered by AI · ChromaDB · FastAPI</div>
      </div>
    </aside>
  );
}
