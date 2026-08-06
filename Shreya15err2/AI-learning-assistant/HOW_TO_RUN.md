# How to Run AI Learning Assistant v2.0

## One-Time Setup

### 1. Backend setup
```
cd AI-Learning-Assistant/backend
python -m venv venv
venv\Scripts\activate       # Windows
pip install -r requirements.txt
```

### 2. Frontend setup
```
cd AI-Learning-Assistant/frontend
npm install
```

### 3. Start Ollama (in a separate terminal)
```
ollama serve
```
Make sure llama3 is pulled:
```
ollama pull llama3
```

---

## Every Day — Start the App

### Terminal 1 — Backend
```
cd AI-Learning-Assistant/backend
venv\Scripts\activate
uvicorn main:app --reload --port 8000
```

### Terminal 2 — Frontend
```
cd AI-Learning-Assistant/frontend
npm run dev
```

### Terminal 3 — Ollama
```
ollama serve
```

Open browser: http://localhost:5173

---

## API Docs
FastAPI auto-docs: http://localhost:8000/docs

---

## Features
- Upload PDF → OCR extracts text → stored in ChromaDB
- Ask questions → RAG retrieval → Ollama LLaMA3 answers
- Generate quizzes with MCQs
- Generate flashcards (click to flip)
- Get document summaries
- Create personalized study plans

---

## If Ollama is not running
The /ask endpoint still works — it returns the raw retrieved chunks.
Quiz, Flashcards, Summary, and Study Plan require Ollama.
