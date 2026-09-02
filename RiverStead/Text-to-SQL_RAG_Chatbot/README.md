---
title: F1InsightAI
emoji: 🏎️
colorFrom: red
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# 🏎️ F1InsightAI — AI-Powered Formula 1 Text-to-SQL RAG Chatbot

An AI-powered RAG (Retrieval-Augmented Generation) chatbot that converts natural language questions into SQL queries over a comprehensive Formula 1 database (1950–2024) hosted on **TiDB Cloud**. Built with Flask, a LangGraph agentic pipeline, Groq API (GPT OSS 120B), and FAISS-based RAG for schema-aware SQL generation.

## ✨ Features

### Core
- **Natural Language to SQL** — Ask questions about F1 in plain English, get accurate SQL queries
- **RAG-Powered Schema Retrieval** — FAISS + sentence-transformers for context-aware SQL generation
- **LangGraph Agentic Pipeline** — Multi-step reasoning with classify → retrieve → generate → execute → reflect → answer
- **Auto-Retry with Error Feedback** — If a query fails, the agent gets the error and automatically fixes the SQL
- **Read-Only SQL Enforcement** — Only SELECT queries are allowed; all write operations are blocked
- **Groq API** — Lightning-fast inference using GPT OSS 120B (free tier)
- **RAG Evaluation Metrics** — Live MRR, Recall@K, Context Relevance, and Faithfulness scores displayed per query

### User Experience
- **🎬 Cinematic "Kinetic Cockpit" Interface** — tsParticles network background, mouse-following spotlight, telemetry grid overlay, 3D card tilt on hover
- **📊 Auto Chart Visualizations** — Bar, pie, and line charts auto-generated with distinct F1-themed colors
- **💡 AI Follow-up Suggestions** — LLM-generated follow-up questions appear as clickable pill chips
- **📌 Pin & Rename Chats** — Pin important conversations and rename them for easy reference
- **⋮ ChatGPT-Style Three-Dot Menu** — Hover to reveal dots, click for dropdown with Rename/Pin/Delete
- **🧠 Agent Reasoning** — Collapsible accordion showing each step of the AI's thinking process
- **✨ Rotating Conic Border** — Animated glow effect on the search input using `@property` CSS
- **🎯 Animated Hero Title** — Multi-stop gradient animation with flowing color effect
- **SQL Syntax Highlighting** — Color-coded keywords in a dark IDE-style card
- **CSV Export** — Download any query result table as a `.csv` file
- **SQL Download** — Download generated SQL as a `.sql` file
- **Glassmorphism UI** — Frosted-glass cards, staggered cascade animations, responsive design
- **📊 RAG Evaluation Card** — Live retrieval quality metrics (MRR, Recall@K, Context Relevance, Faithfulness) in the bento grid
- **🐳 Docker Ready** — Dockerfile + Docker Compose for one-command deployment

## 🛠️ Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | Flask (Python) |
| Agent | LangGraph (multi-step reasoning) |
| LLM | Groq API (GPT OSS 120B) |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) |
| Vector Store | FAISS (Facebook AI Similarity Search) |
| Charts | Chart.js |
| Database | TiDB Cloud (F1 Database — 14 F1 tables, 700K+ rows) |
| Container | Docker + Docker Compose |

## 🏗️ Architecture

```
User Question
     │
     ▼
┌─────────────┐
│  Flask API  │  (app.py — /api/chat)
└──────┬──────┘
       │ + chat history (last 20 msgs)
       ▼
┌──────────────────────────────────────────────────────┐
│         LangGraph Agent (9-node state graph)         │
│                                                      │
│  ┌──────────┐                                        │
│  │ classify │─── "conversation" ──▶ direct_answer ─▶ END │
│  └────┬─────┘                                        │
│       │ "database"                                   │
│       ▼                                              │
│  ┌─────────────────┐                                 │
│  │ retrieve_schema │  RAG: FAISS top-7 + co-occurrence  │
│  └────────┬────────┘                                 │
│           ▼                                          │
│  ┌──────────────┐                                    │
│  │ generate_sql │  Groq LLM (GPT OSS 120B)          │
│  └──────┬───────┘                                    │
│         ▼                                            │
│  ┌─────────────┐                                     │
│  │ execute_sql │  TiDB Cloud (read-only)             │
│  └──────┬──────┘                                     │
│         ▼                                            │
│  ┌─────────┐    ❌ error                              │
│  │ reflect │───────────▶ retry_sql ──┐               │
│  └────┬────┘            (up to 2x)   │               │
│       │ ✅ ok       ◀────────────────┘               │
│       ▼                                              │
│  ┌─────────────────┐                                 │
│  │ generate_answer │  Natural language summary        │
│  └────────┬────────┘                                 │
│           ▼                                          │
│  ┌───────────────────┐                               │
│  │ generate_follow_  │  3 suggested questions         │
│  │       ups         │                               │
│  └────────┬──────────┘                               │
│           ▼                                          │
│          END                                         │
└──────────────────────────────────────────────────────┘
       │
       ▼
 Chat Response (Answer + SQL + Table + Chart + Follow-ups)
```

## 🚀 Setup Guide

### Prerequisites
- Python 3.9+
- TiDB Cloud account with F1 database ([tidbcloud.com](https://tidbcloud.com))
- Groq API key (free at [console.groq.com](https://console.groq.com))

### Step 1: Set up TiDB Cloud

1. Create a free TiDB Serverless cluster on [TiDB Cloud](https://tidbcloud.com)
2. Import the F1 database — you can use the [f1db dataset](https://github.com/f1db/f1db)
3. Note your connection details (host, port, user, password)

### Step 2: Install Python Dependencies

```bash
# Create a virtual environment (recommended)
python -m venv venv
venv\Scripts\activate   # Windows
# source venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt
```

### Step 3: Configure Environment

Copy `.env.example` to `.env` and fill in your TiDB Cloud credentials:

```env
MYSQL_HOST=gateway01.ap-southeast-1.prod.aws.tidbcloud.com
MYSQL_PORT=4000
MYSQL_USER=your_tidb_user
MYSQL_PASSWORD=your_tidb_password
MYSQL_DATABASE=f1db
MYSQL_SSL=true
GROQ_API_KEY=your_groq_api_key
```

### Step 4: Run the Application

```bash
python app.py
```

Visit **http://localhost:5000** in your browser.

### Alternative: Docker Deployment

1. **Ensure your `.env` file** has these values:
   ```env
   GROQ_API_KEY=your_groq_api_key
   MYSQL_PASSWORD=f1insight123
   MYSQL_DATABASE=f1db
   ```

2. **Build and start:**
   ```bash
   docker-compose up --build
   ```

Visit **http://localhost:5000**.

## 📁 Project Structure

```
Project/
├── app.py                    # Flask app — API endpoints + orchestration
├── config.py                 # Centralized config (loads .env)
├── requirements.txt          # Python dependencies
├── .env                      # Environment variables (not in git)
├── .env.example              # Template for environment setup
│
├── agent/
│   ├── __init__.py           # Module: LangGraph agentic SQL pipeline
│   ├── agent.py              # 9-node state graph (classify → retrieve → generate → execute → reflect → answer) + RAG metrics
│   └── tools.py              # Agent tools (schema retrieval, SQL execution, validation, faithfulness check)
│
├── database/
│   ├── __init__.py           # Module: MySQL/TiDB connection + chat storage
│   ├── connector.py          # Connection pool + retry logic + safe query execution
│   └── chat_store.py         # Server-side conversation CRUD (rename, pin, delete)
│
├── rag/
│   ├── __init__.py           # Module: FAISS vector index + schema retrieval
│   └── embeddings.py         # Schema embedding + FAISS retrieval + co-occurrence rules + semantic enrichment
│
├── llm/
│   ├── __init__.py           # Module: Groq API integration + SQL generation
│   ├── prompt_templates.py   # System prompts + few-shot examples + F1 domain knowledge
│   └── sql_generator.py      # Groq LLM calls — SQL gen, auto-retry, answer gen
│
├── templates/
│   └── index.html            # Cinematic Data Interface (tsParticles + bento grid + spotlight + grid overlay)
│
├── static/
│   ├── css/styles.css        # Glassmorphism dark theme, cinematic effects (spotlight, grid, conic border, 3D tilt)
│   └── js/app.js             # Chat engine, bento renderer, chart rendering, three-dot menu, card tilt
│
├── Dockerfile                # Container build config
└── docker-compose.yml        # Multi-service orchestration
```

## 💬 Example Questions

- *"Who has the most race wins in F1 history?"*
- *"Compare Hamilton and Verstappen career stats"*
- *"Show the 2023 race calendar with circuits"*
- *"Which circuit has hosted the most races?"*
- *"What is the average pit stop duration by team?"*
- *"List all champions from 2000 to 2024"*
- *"Show lap time trends for the Monaco Grand Prix"*

## 🔑 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Serve chat UI |
| POST | `/api/chat` | Send a question, get SQL + results |
| GET | `/api/health` | Health check (DB + RAG + LLM status) |
| GET | `/api/stats` | Database statistics (tables, rows, columns, model) |
| GET | `/api/tables` | List all available tables |
| GET | `/api/conversations` | List all conversations |
| POST | `/api/conversations` | Create a new conversation |
| DELETE | `/api/conversations/<id>` | Delete a conversation |
| PATCH | `/api/conversations/<id>/rename` | Rename a conversation |
| PATCH | `/api/conversations/<id>/pin` | Pin/unpin a conversation |

## 📄 License

This project is for educational/academic purposes (capstone project).
