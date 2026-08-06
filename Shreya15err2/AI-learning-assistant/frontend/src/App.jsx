import { useState, useEffect } from "react";
import Sidebar from "./components/Sidebar";
import ChatPage from "./pages/ChatPage";
import QuizPage from "./pages/QuizPage";
import FlashcardsPage from "./pages/FlashcardsPage";
import SummaryPage from "./pages/SummaryPage";
import StudyPlanPage from "./pages/StudyPlanPage";
import LoginPage from "./pages/LoginPage";
import UploadBanner from "./components/UploadBanner";
import { api } from "./utils/api";
import { isLoggedIn, logout, getUsername } from "./utils/auth";
import "./styles/global.css";

export default function App() {
  const [loggedIn, setLoggedIn] = useState(isLoggedIn());
  const [activePage, setActivePage] = useState("chat");
  const [uploadedDoc, setUploadedDoc] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [chatHistory, setChatHistory] = useState([
    { role: "ai", content: "Hello! Upload a PDF or select an existing document in the library. You can ask me questions, create study plans, generate quizzes, and summarize topics. 📚" }
  ]);

  useEffect(() => {
    if (loggedIn) fetchDocuments();
  }, [loggedIn]);

  async function fetchDocuments() {
    try {
      const docs = await api.getDocuments();
      setDocuments(docs);
    } catch (e) {
      console.error("Failed to load documents", e);
    }
  }

  async function handleDeleteDocument(docId) {
    try {
      await api.deleteDocument(docId);
      if (uploadedDoc && uploadedDoc.document_id === docId) {
        setUploadedDoc(null);
      }
      fetchDocuments();
    } catch (e) {
      alert(`Failed to delete document: ${e.message}`);
    }
  }

  function handleLogout() {
    logout();
    setLoggedIn(false);
    setDocuments([]);
    setUploadedDoc(null);
    setChatHistory([
      { role: "ai", content: "Hello! Upload a PDF or select an existing document in the library. You can ask me questions, create study plans, generate quizzes, and summarize topics. 📚" }
    ]);
  }

  // Show login page if not authenticated
  if (!loggedIn) {
    return <LoginPage onSuccess={() => setLoggedIn(true)} />;
  }

  const pages = {
    chat: (
      <ChatPage
        doc={uploadedDoc}
        hasDocs={documents.length > 0}
        messages={chatHistory}
        setMessages={setChatHistory}
      />
    ),
    quiz: <QuizPage doc={uploadedDoc} hasDocs={documents.length > 0} />,
    flashcards: <FlashcardsPage doc={uploadedDoc} hasDocs={documents.length > 0} />,
    summary: <SummaryPage doc={uploadedDoc} hasDocs={documents.length > 0} />,
    studyplan: <StudyPlanPage />,
  };

  return (
    <div className="app-shell">
      <Sidebar
        activePage={activePage}
        onNavigate={setActivePage}
        uploadedDoc={uploadedDoc}
        onSelectDoc={setUploadedDoc}
        documents={documents}
        onRefreshDocs={fetchDocuments}
        onDeleteDoc={handleDeleteDocument}
        username={getUsername()}
        onLogout={handleLogout}
      />
      <main className="main-area">
        {!uploadedDoc && documents.length === 0 && activePage !== "studyplan" && (
          <UploadBanner />
        )}
        {pages[activePage]}
      </main>
    </div>
  );
}
