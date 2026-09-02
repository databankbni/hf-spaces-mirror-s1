# F1InsightAI — Project Summary Report

**Project Title:** F1InsightAI — AI-Powered Formula 1 Text-to-SQL RAG Chatbot  
**Student:** Venkateswara Sahu (12204893)  
**Course:** Term 8 — Capstone Project  
**Date:** March 2026

---

## 1. Introduction & Problem Statement

F1InsightAI is an AI-powered chatbot that allows users to query a comprehensive Formula 1 database (1950–2024, 14 F1 tables, 700K+ rows) using plain English. The system converts natural language questions into SQL queries using Retrieval-Augmented Generation (RAG) and a multi-step agentic pipeline.

**Problem:** Querying structured databases requires SQL expertise, creating a barrier for non-technical users. Naive Text-to-SQL approaches that send the entire schema to an LLM suffer from token inefficiency, reduced accuracy, and no error recovery.

**Solution:** A RAG pipeline retrieves only the relevant table schemas for each question, combined with a LangGraph agent that supports intent classification, self-reflection, and automatic error correction.

---

## 2. Technology Stack

| Component | Technology |
|-----------|------------|
| Backend | Flask (Python) |
| Agent Framework | LangGraph (9-node state graph) |
| LLM | Groq API — GPT OSS 120B |
| Embeddings | Sentence-Transformers (all-MiniLM-L6-v2) |
| Vector Store | FAISS (Facebook AI Similarity Search) |
| Database | TiDB Cloud (MySQL-compatible, serverless) |
| Frontend | HTML/CSS/JS + particles.js + Chart.js |
| Deployment | Docker + Docker Compose |

---

## 3. System Architecture

The system follows a 3-layer architecture:

**Frontend** → "Kinetic Cockpit" cinematic dark UI with tsParticles background, mouse-following spotlight, telemetry grid overlay, 3D card tilt, glassmorphism cards, rotating conic border on search, and a bento-grid results layout.

**Flask API** → REST endpoints for chat, conversations (CRUD, pin, rename), health check, and database stats.

**LangGraph Agent** → A 9-node stateful pipeline:

1. **classify** — Determines if the question needs SQL or is conversational
2. **retrieve_schema** — RAG retrieves top-7 relevant table schemas from FAISS + co-occurrence rules inject related tables
3. **generate_sql** — LLM generates a SQL SELECT query using schema context + F1 domain knowledge
4. **execute_sql** — Executes on TiDB Cloud (read-only enforced)
5. **reflect** — Validates results; routes to retry or answer
6. **retry_sql** — Feeds error back to LLM for auto-correction (up to 2 retries)
7. **generate_answer** — LLM creates a natural language summary
8. **generate_follow_ups** — LLM suggests 3 related follow-up questions
9. **direct_answer** — Handles conversational queries without SQL

---

## 4. RAG Pipeline

The RAG (Retrieval-Augmented Generation) pipeline ensures the LLM receives only relevant schema context:

- **Indexing (startup):** All 14 F1 table schemas (excluding 2 system tables) are converted to rich text documents, embedded using all-MiniLM-L6-v2 (384-dim vectors), normalized, and stored in a FAISS IndexFlatIP.
- **Retrieval (per query):** The user's question is embedded, and FAISS performs a top-7 cosine similarity search. Co-occurrence rules then auto-inject related tables (e.g., `results` → `drivers`, `races` → `circuits`).
- **Augmentation:** The retrieved table descriptions are injected into the LLM system prompt alongside few-shot examples and F1 domain knowledge (team name changes, race name changes, circuit name mappings).

This approach improves SQL accuracy compared to sending the full 100+ column schema in every prompt.

---

## 5. Key Features

- **Natural Language to SQL** with RAG-based schema retrieval
- **Auto-retry** with error feedback (agent self-corrects failed queries)
- **Multi-turn context** (last 20 messages for pronoun resolution and follow-ups)
- **Auto-generated charts** (bar, pie, line) with smart column filtering
- **Conversation management** — create, rename, pin, delete chats (server-side storage)
- **ChatGPT-style three-dot menu** — hover to reveal ⋮ dots, click for dropdown with Rename/Pin/Delete
- **Agent reasoning transparency** — collapsible accordion showing each pipeline step
- **SQL syntax highlighting** with copy and download buttons
- **CSV export** for query result tables
- **F1 domain knowledge** — European countries, team name history, race name changes, circuit name mappings
- **Live RAG evaluation** — MRR, Recall@K, Context Relevance, Faithfulness displayed per query in the UI
- **Docker deployment** — one-command setup with Docker Compose

### Cinematic Visual Effects ("Kinetic Cockpit" Design)

- **Mouse-following spotlight** — 800px radial gradient tracking cursor movement
- **Telemetry grid overlay** — persistent 40×40px CSS grid with red lines at 2% opacity
- **Rotating conic border** — `@property`-animated glow effect on the search input
- **3D card tilt on hover** — `MutationObserver`-backed perspective transform on result cards
- **Animated hero title** — multi-stop gradient animation with `-webkit-background-clip: text`
- **tsParticles network** — F1-themed red/orange connected particle background
- **Responsive search dock** — 60% viewport width, adapts from centered hero to fixed bottom bar
- **Fixed status bar** — real-time connection, model, table count, and row count display

---

## 6. Results (Automated Benchmark — 20 Queries)

A benchmark script (`tests/benchmark.py`) tested 20 diverse queries across 9 categories:

| Metric | Value |
|--------|-------|
| Total Queries Tested | 20 (18 SQL + 2 conversational) |
| SQL Query Accuracy (1st attempt) | **83.3%** (15/18) |
| Queries Needing Retry | 0 |
| Average Response Time | 21.66s |
| Database Coverage | 16 tables, 701,530 rows, 131 columns |

**Categories with 100% accuracy:** Driver Stats (4/4), Circuit Queries (1/1), Pit Stops (1/1), Lap Times (1/1), Comparison (1/1), Historical (2/2), Qualifying (1/1), Sprint (1/1)

**Sample queries tested successfully:**
- "Who has the most race wins in F1 history?" → Hamilton (105 wins) ✅
- "Compare Hamilton and Verstappen career stats" → side-by-side comparison ✅
- "Who won the first ever F1 race?" → Nino Farina ✅
- "Average pit stop duration in 2023" → correct aggregation ✅

---

## 7. RAG Evaluation Metrics

Four live metrics are computed per query and displayed in a dedicated bento grid card:

| Metric | What It Measures |
|--------|-----------------|
| **MRR** | Rank of first needed table in FAISS results |
| **Recall@K** | % of SQL-needed tables found in retrieval |
| **Context Relevance** | Useful tables / total retrieved |
| **Faithfulness** | SQL result values matched in the LLM answer |

**Three-round iterative improvement** was performed:
1. **Baseline:** Raw FAISS (MRR avg: 0.12)
2. **Fix 1:** Excluded system tables + semantic enrichment (MRR avg: 0.25)
3. **Fix 2:** Co-occurrence rules + top_k=7 + enhanced keywords (MRR avg: **0.67**, 5.5× improvement)

**Key optimizations:** System table exclusion, semantic enrichment keywords, table co-occurrence rules (e.g., `results` → auto-include `drivers`), increased retrieval window from 5 to 7 tables.

---

## 8. Conclusion

F1InsightAI demonstrates the practical application of RAG + agentic LLM pipelines for domain-specific Text-to-SQL tasks. The system achieves high SQL accuracy by retrieving only relevant schema context, handles errors through self-reflection and auto-retry, and presents results in a visually engaging "Kinetic Cockpit" interface with cinematic effects (mouse spotlight, telemetry grid, 3D card tilt, rotating conic border, animated hero title). The ChatGPT-style three-dot dropdown menu, conversation pinning, and server-side storage provide a polished chat management experience. Live RAG evaluation metrics provide transparency into retrieval quality. The project combines modern AI techniques (RAG, LangGraph agents, FAISS vector search) with robust engineering (connection pooling, read-only enforcement, Docker deployment) to create a production-quality data exploration tool for Formula 1 enthusiasts.
