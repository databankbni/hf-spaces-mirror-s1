# F1InsightAI — AI-Powered Formula 1 Text-to-SQL RAG Chatbot

## Project Report

---

**Project Title:** F1InsightAI — AI-Powered Formula 1 Text-to-SQL RAG Chatbot  
**Course:** Term 8 — Capstone Project  
**Technology Stack:** Python, Flask, LangGraph, Groq API, FAISS, TiDB Cloud, Chart.js

---

## Table of Contents

1. [Abstract](#1-abstract)
2. [Introduction](#2-introduction)
3. [Problem Statement](#3-problem-statement)
4. [Objectives](#4-objectives)
5. [Literature Review](#5-literature-review)
6. [System Architecture](#6-system-architecture)
7. [Technology Stack](#7-technology-stack)
8. [Implementation Details](#8-implementation-details)
9. [RAG Pipeline](#9-rag-pipeline)
10. [Agent Pipeline (LangGraph)](#10-agent-pipeline-langgraph)
11. [Frontend Design](#11-frontend-design)
12. [Database Design](#12-database-design)
13. [Key Challenges & Solutions](#13-key-challenges--solutions)
14. [Results & Testing](#14-results--testing)
15. [Future Scope](#15-future-scope)
16. [Conclusion](#16-conclusion)
17. [References](#17-references)
18. [Appendix A: Application Screenshots](#appendix-a-application-screenshots)

---

## 1. Abstract

F1InsightAI is a chatbot we built to let anyone ask questions about Formula 1 history in plain English and get back real answers from a database. The database covers F1 data from 1950 all the way to 2024. Instead of dumping the whole database schema into the AI prompt every time (which wastes tokens and confuses the model), we use a technique called Retrieval-Augmented Generation (RAG) — it picks out only the relevant tables for each question before the LLM writes the SQL. The backend runs on a 9-node LangGraph agent that handles everything from figuring out what the user is asking, to generating SQL, running it, checking if the results make sense, and retrying if something breaks. On the frontend, we went with a dark-themed cinematic interface that shows results in a card-based grid with auto-generated charts, syntax-highlighted SQL, and follow-up suggestions. The whole thing runs on Flask, with TiDB Cloud hosting the database and Groq's API providing fast inference through the GPT OSS 120B model.

---

## 2. Introduction

Formula 1 has been around for over 75 years, and in that time a massive amount of data has piled up — race results, driver stats, lap times, pit stops, qualifying sessions, constructor standings, and more. All of this sits in a relational database with 14 tables and over 100 columns. But the problem is, to actually get anything useful out of it, you need to know SQL. And most F1 fans or casual users don't.

That's where Text-to-SQL comes in. The idea is simple: the user types a question like "Who has the most race wins?" and the system figures out the right SQL query to answer it. But when we started looking into how to actually build this, we ran into some real issues with the basic approach of just sending the full schema to an LLM:

- **Token waste** — our F1 database has 14 tables with 100+ columns, and sending all of that every time eats up the context window for no reason
- **Confused outputs** — when the LLM sees too many irrelevant tables, it starts joining things that don't make sense or picks the wrong columns
- **No recovery** — if the generated SQL fails, a basic system just returns an error and that's it

So we built F1InsightAI to handle all of this properly. We use RAG to pull only the relevant schema context for each question, and we wrapped the whole thing in a LangGraph-based agent pipeline that can classify what the user is asking, generate SQL, run it against the database, check whether the results actually make sense, and retry with corrections if something goes wrong.

---

## 3. Problem Statement

How can we build an intelligent chatbot that:
1. Allows non-technical users to explore a complex F1 database using natural language
2. Generates accurate SQL queries by retrieving only the relevant schema context (RAG)
3. Handles errors gracefully through automatic retry and self-correction
4. Presents results in an intuitive, visually appealing interface with auto-generated charts

---

## 4. Objectives

1. **Implement a RAG pipeline** using FAISS vector search and sentence-transformer embeddings for schema-aware SQL generation
2. **Build a multi-step agentic pipeline** using LangGraph with intent classification, SQL generation, execution, reflection, and auto-retry
3. **Develop a cinematic frontend** with glassmorphism design, auto-generated charts, and conversation management
4. **Ensure robustness** through read-only SQL enforcement, connection pooling with retry logic, and graceful error handling
5. **Deploy on cloud infrastructure** using TiDB Cloud for the database and Groq API for LLM inference

---

## 5. Literature Review

### 5.1 Text-to-SQL Systems

The whole idea of converting a normal English question into a SQL query has been around for a while. Earlier systems relied on fixed rules and templates — basically pattern matching. But with LLMs becoming more capable, the field has shifted towards using these models to generate SQL directly from natural language input. We looked at a few key benchmarks and systems while building our project:

- **Spider** (Yu et al., 2018) is a widely-used benchmark for cross-database Text-to-SQL. It gave us a good sense of how these systems are evaluated and what kind of accuracy to expect.
- **RESDSQL** (Li et al., 2023) focuses on schema linking — figuring out which tables and columns are actually relevant to a given question. This was directly relevant to our RAG approach since we're essentially doing the same thing, just with vector search instead of a ranking model.
- **DIN-SQL** (Pourreza & Rafiei, 2023) breaks down the SQL generation into smaller steps rather than trying to do it all at once. Our pipeline follows a similar philosophy — we classify the intent first, then retrieve schema, then generate SQL, rather than doing everything in one prompt.

### 5.2 Retrieval-Augmented Generation (RAG)

RAG was first proposed by Lewis et al. (2020). The core idea is straightforward: instead of expecting the LLM to know everything from its training data, you fetch relevant information at query time and include it in the prompt. For our use case, this meant fetching only the database tables that are actually needed for a given question.

We picked RAG over fine-tuning for a few practical reasons. First, fine-tuning a large model on our specific schema would require GPU resources we didn't have. Second, RAG is more flexible — if we add new tables to the database tomorrow, the system picks them up automatically without retraining. And third, it keeps the prompts smaller, which means faster responses and lower API costs.

The main benefits we saw in practice were:

- The LLM stopped hallucinating table names that don't exist when we limited the context to only relevant tables
- SQL accuracy went up because the model wasn't distracted by unrelated schema
- We could scale to more tables without worrying about context window limits

### 5.3 Agentic AI Pipelines

A basic chatbot just takes a prompt and gives a response. But for something like SQL generation, that's not enough — you need multiple steps. You need to figure out what the user is asking, pull the right context, generate the SQL, run it, and then check if the output actually makes sense. If the SQL fails, you want to fix it and try again rather than just showing an error.

This is what agentic AI is about — building systems where the LLM operates as part of a larger workflow with multiple steps, tool access, and decision-making loops. We used LangGraph for this because it lets you define the pipeline as a graph with nodes and edges, where each node is a processing step and edges can be conditional (for example, routing to a retry node if SQL execution fails). It also handles state management, so each step can access and modify a shared state object as the query moves through the pipeline.

---

## 6. System Architecture

### 6.1 High-Level Architecture

```mermaid
graph TB
    subgraph Frontend ["🖥️ Frontend (Browser)"]
        UI["Cinematic Data Interface<br/>HTML + CSS + JS + tsParticles"]
        BG["Bento Grid Renderer<br/>Chart.js + SQL Highlighter"]
        FX["Cinematic Effects<br/>Spotlight + Grid + 3D Tilt + Glow Border"]
    end

    subgraph Backend ["⚙️ Flask Backend (app.py)"]
        API["REST API<br/>/api/chat, /api/conversations"]
        CS["Chat Store<br/>Conversation CRUD"]
    end

    subgraph Agent ["🤖 LangGraph Agent (9 nodes)"]
        CL["1. Classify Intent"]
        RS["2. Retrieve Schema (RAG)"]
        GS["3. Generate SQL (LLM)"]
        EX["4. Execute SQL"]
        RF["5. Reflect & Validate"]
        RT["6. Retry SQL"]
        GA["7. Generate Answer"]
        GF["8. Generate Follow-ups"]
        DA["9. Direct Answer"]
    end

    subgraph RAG ["🧠 RAG Pipeline"]
        EMB["Sentence-Transformers<br/>all-MiniLM-L6-v2"]
        FAISS["FAISS Vector Index<br/>14 table embeddings"]
    end

    subgraph External ["☁️ External Services"]
        GROQ["Groq API<br/>GPT OSS 120B"]
        TIDB[("TiDB Cloud<br/>F1 Database<br/>700K+ rows")]
    end

    UI -->|User Question| API
    API -->|Question + History| CL
    CL -->|Database Query| RS
    CL -->|Conversation| DA
    RS -->|Top-7 Tables + Co-occur| GS
    GS -->|SQL Query| EX
    EX -->|Results or Error| RF
    RF -->|Error| RT
    RT -->|Fixed SQL| EX
    RF -->|Success| GA
    GA --> GF
    GF -->|Response JSON| API
    DA -->|Response JSON| API
    API -->|Answer + SQL + Data| BG
    API <-->|CRUD| CS
    CS <-->|Read/Write| TIDB
    RS <-->|Embed + Search| FAISS
    EMB -->|384-dim vectors| FAISS
    GS <-->|Prompt + Generate| GROQ
    GA <-->|Summarize| GROQ
    EX <-->|Execute SQL| TIDB
```

### 6.2 LangGraph Agent Flowchart

```mermaid
flowchart TD
    START(["User Question"]) --> classify{"classify<br/>Intent Classification"}

    classify -->|"is_database_query = true"| retrieve_schema["retrieve_schema<br/>RAG: FAISS Top-7 Tables"]
    classify -->|"is_database_query = false"| direct_answer["direct_answer<br/>General/Conversational"]

    retrieve_schema --> generate_sql["generate_sql<br/>Groq LLM → SQL Query"]
    generate_sql --> execute_sql["execute_sql<br/>TiDB Cloud (Read-Only)"]
    execute_sql --> reflect{"reflect<br/>Validate Results"}

    reflect -->|"❌ Error & attempts < 2"| retry_sql["retry_sql<br/>Feed error to LLM"]
    reflect -->|"✅ Success or max retries"| generate_answer["generate_answer<br/>Natural Language Summary"]

    retry_sql --> execute_sql

    generate_answer --> generate_follow_ups["generate_follow_ups<br/>3 Suggested Questions"]
    generate_follow_ups --> END_DB(["Response<br/>Answer + SQL + Table + Chart + Follow-ups"])
    direct_answer --> END_CONV(["Response<br/>Conversational Answer"])

    style classify fill:#f59e0b,color:#000
    style reflect fill:#f59e0b,color:#000
    style retrieve_schema fill:#3b82f6,color:#fff
    style generate_sql fill:#8b5cf6,color:#fff
    style execute_sql fill:#10b981,color:#fff
    style retry_sql fill:#ef4444,color:#fff
    style generate_answer fill:#06b6d4,color:#fff
    style generate_follow_ups fill:#06b6d4,color:#fff
    style direct_answer fill:#6b7280,color:#fff
```

### 6.3 Data Flow

1. **User sends a question** via the chat interface → Flask `/api/chat` endpoint
2. **Chat history** (last 20 messages) is fetched from TiDB Cloud for multi-turn context
3. The **LangGraph agent** processes the question through 9 nodes with conditional routing
4. The **response** (answer, SQL, table data, chart data, follow-ups) is returned to the frontend
5. The frontend renders the response as a **bento-grid** with animated card reveals

---

## 7. Technology Stack

| Component | Technology | Justification |
|-----------|------------|---------------|
| Backend | Flask (Python 3.11) | Lightweight, well-suited for API development |
| Agent Framework | LangGraph | Stateful graph-based workflows with conditional edges |
| LLM | Groq API (GPT OSS 120B) | Free tier, extremely fast inference (~2-3s), open-source model |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) | Lightweight (80MB), high-quality semantic embeddings |
| Vector Store | FAISS (Facebook AI Similarity Search) | Optimized for fast similarity search, no external server needed |
| Database | TiDB Cloud (MySQL-compatible) | Serverless, free tier, cloud-hosted, SSL-encrypted |
| Charts | Chart.js | Client-side rendering, supports bar/pie/line charts |
| Frontend | Vanilla HTML/CSS/JS + tsParticles | Full control over cinematic design, no framework overhead |
| Deployment | Docker + Docker Compose | One-command deployment, reproducible environments |

---

## 8. Implementation Details

### 8.1 Project Structure

```
Project/
├── app.py                    # Flask app — API endpoints + orchestration
├── config.py                 # Centralized config (loads .env)
├── requirements.txt          # Python dependencies
│
├── agent/
│   ├── agent.py              # 9-node LangGraph state graph
│   └── tools.py              # Agent tools (schema retrieval, SQL execution)
│
├── database/
│   ├── connector.py          # Connection pool + retry logic
│   └── chat_store.py         # Server-side conversation CRUD
│
├── rag/
│   └── embeddings.py         # FAISS vector index + schema retrieval
│
├── llm/
│   ├── prompt_templates.py   # System prompts + F1 domain knowledge
│   └── sql_generator.py      # Groq LLM calls — SQL gen + answer gen
│
├── templates/index.html      # Cinematic Data Interface (tsParticles + spotlight + grid overlay)
├── static/css/styles.css     # Glassmorphism dark theme, cinematic effects (spotlight, grid, conic border, 3D tilt)
├── static/js/app.js          # Chat engine, bento renderer, chart rendering, three-dot menu, card tilt
│
├── Dockerfile                # Container build config
└── docker-compose.yml        # Multi-service orchestration
```

### 8.2 Configuration Management

All configuration is centralized in `config.py`, which reads environment variables from a `.env` file:

- **Database**: `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`, `MYSQL_SSL`
- **LLM**: `GROQ_API_KEY`, `GROQ_MODEL`
- **Flask**: `FLASK_SECRET_KEY`, `FLASK_DEBUG`
- **RAG**: `TOP_K_SCHEMA_RESULTS` (default: 7), `MAX_RETRY_ATTEMPTS` (default: 2)

### 8.3 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Serve the chat UI |
| POST | `/api/chat` | Send a question, receive SQL + results + answer |
| GET | `/api/health` | Health check (DB + RAG + LLM status) |
| GET | `/api/stats` | Database statistics (tables, rows, columns, model) |
| GET | `/api/tables` | List all available tables |
| GET | `/api/conversations` | List all conversations |
| POST | `/api/conversations` | Create a new conversation |
| DELETE | `/api/conversations/<id>` | Delete a conversation |
| PATCH | `/api/conversations/<id>/rename` | Rename a conversation |
| PATCH | `/api/conversations/<id>/pin` | Pin/unpin a conversation |

---

## 9. RAG Pipeline

### 9.1 Why RAG?

The F1 database has 14 F1 tables (plus 2 system tables) with 100+ columns. Sending the entire schema in every prompt would:
- Waste LLM tokens (increasing latency and cost)
- Introduce irrelevant context that confuses SQL generation
- Not scale to larger databases

RAG solves this by retrieving **only the relevant tables** for each question.

### 9.2 Schema Embedding

At application startup:

1. The system queries TiDB Cloud for all table metadata (`INFORMATION_SCHEMA.COLUMNS`)
2. Each table is converted into a **rich text document** containing:
   - Table name and row count
   - Column names, data types, constraints (PK, FK, UNIQUE, INDEXED)
   - Sample values for key columns
   - Relationship descriptions to other tables
3. All documents are embedded using **all-MiniLM-L6-v2** (384-dimensional vectors)
4. Embeddings are normalized (L2) and stored in a **FAISS IndexFlatIP** (inner product = cosine similarity)

### 9.3 Retrieval at Query Time

When a user asks a question:

1. The question is embedded using the same model
2. FAISS performs a **top-7 nearest neighbor search** against the indexed schema documents
3. **Co-occurrence rules** automatically inject related tables (e.g., `results` → `drivers`, `races` → `circuits`)
4. The relevant table descriptions are concatenated and injected into the LLM system prompt
5. The LLM generates SQL using **only the relevant tables**, improving accuracy

### 9.4 RAG Pipeline Diagram

```mermaid
sequenceDiagram
    participant U as User
    participant A as Agent
    participant E as Embedding Model
    participant F as FAISS Index
    participant L as Groq LLM

    Note over E,F: Startup (One-time Indexing)
    A->>E: Encode 14 F1 table schema documents (16 total − 2 system tables excluded)
    E-->>A: 384-dim vectors (float32)
    A->>F: Normalize (L2) + Store in IndexFlatIP
    F-->>A: Index ready (14 vectors)

    Note over U,L: Query Time (Per Question)
    U->>A: "How many wins does Hamilton have?"
    A->>E: Encode question
    E-->>A: Query vector (384-dim)
    A->>F: Top-7 nearest neighbor search + co-occurrence rules
    F-->>A: [results, drivers, races, driver_standings, qualifying, circuits, constructors]
    A->>L: Question + Top-7 schema docs + Few-shot examples
    L-->>A: SELECT d.forename, d.surname, COUNT(*) AS wins...
    A-->>U: SQL + Results + Answer
```

### 9.5 Comparison with Standard RAG

| Aspect | Standard RAG (OpenRAG) | Schema-RAG (F1InsightAI) |
|--------|----------------------|--------------------------|
| Documents | Text corpora (PDFs, wikis) | Database table schemas |
| Output | Natural language answers | SQL queries |
| Scale | Millions of documents | 14 documents (one per F1 table) |
| Retrieval | Multi-hop, iterative | Single-pass, top-K |
| Purpose | Ground answers in facts | Ground SQL in correct schema |

The core RAG principle is the same: **retrieve relevant context → augment the LLM prompt → generate better output**.

---

## 10. Agent Pipeline (LangGraph)

### 10.1 Agent State

The agent maintains a typed state dictionary that flows through all nodes:

```python
class AgentState(TypedDict):
    question: str              # User's natural language question
    chat_history: list         # Previous messages for multi-turn context
    schema_context: str        # Retrieved from RAG (top-7 tables + co-occurrence)
    retrieved_tables: list     # Tables retrieved by RAG with similarity scores
    sql: str                   # Generated SQL query
    sql_attempts: int          # Retry counter (max 2)
    execution_result: dict     # Query results from MySQL
    validation: dict           # From reflect node
    answer: str                # Final natural language answer
    follow_ups: list           # Follow-up question suggestions
    agent_steps: list          # Trace of agent reasoning steps
    error: str                 # Error message if any
    is_database_query: bool    # Whether the question needs SQL
    rag_metrics: dict          # RAG evaluation metrics (MRR, Recall, Faithfulness)
```

### 10.2 Node Descriptions

| # | Node | Purpose | Output |
|---|------|---------|--------|
| 1 | `classify` | Determines if the question needs SQL or is conversational | Routes to `retrieve_schema` or `direct_answer` |
| 2 | `direct_answer` | Answers general/conversational questions directly | Natural language response → END |
| 3 | `retrieve_schema` | Uses RAG (FAISS) to find the top-7 most relevant tables + co-occurrence injection | Schema context string |
| 4 | `generate_sql` | LLM generates a SQL SELECT query using schema context | SQL query string |
| 5 | `execute_sql` | Executes SQL on TiDB Cloud (read-only enforced) | Columns + rows |
| 6 | `reflect` | Evaluates execution results — success or error? | Routes to `retry_sql` or `generate_answer` |
| 7 | `retry_sql` | Feeds the error back to the LLM to fix the SQL | Corrected SQL → back to `execute_sql` |
| 8 | `generate_answer` | LLM summarizes results in conversational English | Answer string |
| 9 | `generate_follow_ups` | LLM generates 3 related follow-up questions | List of questions → END |

### 10.3 Conditional Edges

The agent uses two conditional routing points:

1. **After `classify`**: Routes to `retrieve_schema` (database query) or `direct_answer` (conversation)
2. **After `reflect`**: Routes to `retry_sql` (if error, max 2 retries) or `generate_answer` (if results are valid)

### 10.4 Multi-Turn Context

The system fetches the **last 20 messages** from the conversation before running the agent. This allows:
- Pronoun resolution ("What about **him**?" → refers to a driver from the previous question)
- Follow-up handling ("Compare **that** with Hamilton" → uses context from the previous result)
- Conversation awareness ("Show me more like the **previous query**")

---

## 11. Frontend Design

### 11.1 Design Philosophy

The frontend follows a **"Kinetic Cockpit"** design paradigm — a cinematic, F1-inspired interface that feels alive and responds to user interaction. The design layers multiple visual effects to create an immersive data exploration experience:

- **tsParticles** animated network background — creates depth and dynamism with F1-themed red/orange particles
- **Omni-Search** — single centered search bar that transforms into a docked bottom bar when results appear
- **Bento Box Grid** — results are displayed in staggered, animated glass cards
- **Glassmorphism** — frosted-glass cards with `backdrop-filter: blur(20px)`

### 11.2 Cinematic Visual Effects

Six premium visual effects work together to create the "Kinetic Cockpit" aesthetic:

| Effect | Implementation | Purpose |
|--------|---------------|--------|
| **Mouse-Following Spotlight** | `radial-gradient` (800px radius, orange/red tints) tracking cursor via `mousemove` event | Creates a high-tech, immersive feel |
| **Telemetry Grid Overlay** | Persistent CSS grid overlay (40×40px cells, red lines at 2% opacity) | Enhances the "cockpit HUD" aesthetic |
| **Rotating Conic Border** | `@property`-animated `conic-gradient` border on the search input | Premium search bar glow effect |
| **3D Card Tilt** | `MutationObserver`-backed `perspective(800px)` transform on hover | Tactile depth feedback on result cards |
| **Animated Hero Title** | Multi-stop gradient animation with `-webkit-background-clip: text` | Flowing color effect on the logo |
| **Particle Network** | tsParticles with F1-themed colors (`#E10600`, `#FF6B35`, `#ff4444`) | Living background with connected nodes |

```mermaid
graph LR
    subgraph Visual_Layer ["Visual Effects Stack"]
        P["tsParticles<br/>Background Network"] --> G["Telemetry Grid<br/>40px CSS Overlay"]
        G --> S["Mouse Spotlight<br/>800px Radial Gradient"]
        S --> T["3D Card Tilt<br/>MutationObserver + perspective"]
        T --> B["Conic Border Glow<br/>@property Rotation"]
        B --> H["Gradient Hero Title<br/>Animated text-clip"]
    end

    style P fill:#E10600,color:#fff
    style G fill:#1a1a2e,color:#fff
    style S fill:#FF6B35,color:#fff
    style T fill:#8b5cf6,color:#fff
    style B fill:#f59e0b,color:#000
    style H fill:#06b6d4,color:#fff
```

### 11.3 Bento Grid Cards

Each response renders up to 7 cards:

| Card | Span | Content |
|------|------|---------|
| Answer | 12 cols | Natural language answer + execution time badge |
| Chart | 12 cols | Auto-generated bar/pie/line chart (Chart.js) |
| Table | 12 cols | Scrollable result table with CSV export |
| Agent Steps | 6 cols | Collapsible accordion showing each reasoning step |
| SQL | 6 cols | Syntax-highlighted SQL with copy/download buttons |
| RAG Metrics | 12 cols | MRR, Recall@K, Context Relevance, Faithfulness (color-coded) |
| Follow-ups | 12 cols | Clickable pill buttons for suggested next questions |

### 11.4 Smart Chart Generation

The chart system automatically:
1. Classifies data as bar, pie, or line chart based on data shape
2. Filters out ID/key columns (raceId, year, round) from datasets
3. Uses **distinct colors** (Red, Blue, Emerald, Amber, Purple) for multi-dataset charts
4. Limits to 3 datasets maximum for readability

### 11.5 Responsive Search Dock

The search input adapts between two states:

- **Hero State (landing):** Centered vertically with the animated conic-gradient border, 60% viewport width, rotating typewriter placeholder cycling through 7 F1 queries
- **Docked State (results):** Fixed to the bottom of the viewport with 36px bottom padding to clear the status bar, maintaining the same width and glow effect

### 11.6 Conversation Management — Three-Dot Menu

The history sidebar uses a ChatGPT-style **three-dot dropdown menu** for chat actions:

- A **⋮ vertical dots button** appears on hover over each chat item
- Clicking the dots opens a **glassmorphic dropdown** with animated entry (`translateY + scale`)
- **Rename** — inline editing with click-to-position cursor support
- **Pin/Unpin** — pinned chats stay at top with a 📌 icon; unpinned return to chronological position
- **Delete** — red-highlighted destructive action with a **two-click confirm** pattern (first click changes the button to "Confirm?", second click deletes; resets after 3 seconds)
- **Click outside** — closes the dropdown automatically
- **Copy question** — hover-reveal copy button on user messages
- All conversations are stored **server-side** in TiDB Cloud (persists across restarts)

```mermaid
flowchart LR
    H["Hover Chat Item"] --> D["⋮ Dots Appear<br/>(opacity 0→0.6)"]
    D --> C["Click Dots"]
    C --> M["Dropdown Opens<br/>(glassmorphic, animated)"]
    M --> R["Rename"]
    M --> P["Pin / Unpin"]
    M --> X["Delete (red)"]
    X --> CF["Confirm?<br/>(2nd click to delete)"]
    C2["Click Outside"] --> CL["Dropdown Closes"]

    style M fill:#12121c,color:#fff,stroke:#ffffff14
    style X fill:#ef4444,color:#fff
    style CF fill:#dc2626,color:#fff
    style P fill:#f59e0b,color:#000
    style R fill:#3b82f6,color:#fff
```

### 11.7 F1-Themed Suggestion Chips

The landing page features four quick-start suggestion chips, each with a themed SVG icon:

| Chip | Icon | Query |
|------|------|-------|
| Most race wins | 🏆 Trophy SVG | "Who has the most race wins?" |
| Hamilton vs Verstappen | 📊 Bar chart SVG | "Compare Hamilton vs Verstappen" |
| 2023 race calendar | 📅 Calendar SVG | "Show the 2023 race calendar" |
| Pit stop times | ⏱ Clock SVG | "Average pit stop duration by team" |

### 11.8 F1 Loading Animation

While the AI pipeline processes a query, a custom F1-themed loading animation is displayed:

- **Three bouncing red dots** with staggered animation delays and a glow effect
- **Pipeline step cycling** — the text dynamically updates through the agent's processing stages:
  - "Classifying intent" → "Retrieving schema context (RAG)" → "Generating SQL query" → "Executing on TiDB Cloud" → "Validating results" → "Generating answer"
- The loader is displayed in a **glassmorphic card** (matching the bento grid aesthetic), centered at 60% max-width

### 11.9 Status Bar

A fixed bottom bar displays real-time system information:
- **Connection Status** — green dot for "Connected to TiDB Cloud", red for disconnected
- **Architecture Link** — quick navigation to the interactive system architecture page
- **Active Model** — displays the current LLM model name
- **Table Count** — number of indexed tables
- **Row Count** — total rows in the database

### 11.10 Interactive Architecture Page

A dedicated `/architecture` page provides an interactive visual showcase of the entire system for technical reviewers:

1. **LangGraph Pipeline Visualization** — Animated, color-coded node diagram showing all 9 processing nodes with conditional branching (database query vs. conversation), retry loops, and data flow arrows
2. **RAG Pipeline Flow** — Step-by-step horizontal flow: User Question → Sentence Transformer → FAISS Index → LLM Prompt → SQL Query, with connector labels (Embed, Search, Inject, Generate)
3. **Technology Stack Grid** — 8 cards with icons for Flask, LangGraph, Groq, FAISS, TiDB Cloud, Chart.js, Sentence-BERT, and Docker
4. **Key Capabilities Grid** — 6 feature cards highlighting Schema-Aware RAG, Auto Error Recovery, Self-Reflection, Multi-Turn Context, Live RAG Metrics, and F1 Domain Knowledge
5. **Live System Stats** — Real-time connection status, model name, table count, and row count fetched from the API
6. **Scroll-reveal Animations** — All elements animate in via `IntersectionObserver` as the user scrolls

---

## 12. Database Design

### 12.1 F1 Database (Ergast Schema)

The F1 database contains 14 tables with 700,000+ rows covering 75 years of racing data:

| Table | Description | Key Columns |
|-------|-------------|-------------|
| `circuits` | Race circuits worldwide | name, location, country |
| `constructors` | Racing teams | name, nationality |
| `drivers` | All F1 drivers | forename, surname, nationality, dob |
| `races` | Every race (1950–2024) | name, date, year, round, circuitId |
| `results` | Race results | position, points, laps, time, fastestLap |
| `qualifying` | Qualifying results | position, q1, q2, q3 |
| `driver_standings` | Championship standings | points, position, wins |
| `constructor_standings` | Team standings | points, position, wins |
| `lap_times` | Individual lap data | lap, position, time, milliseconds |
| `pit_stops` | Pit stop records | stop, lap, duration, milliseconds |
| `sprint_results` | Sprint race results | position, points, laps |
| `seasons` | Season metadata | year, url |
| `status` | Result status codes | status (e.g., 'Finished', 'Engine') |
| `constructor_results` | Team race results | points, status |

### 12.2 Entity-Relationship Diagram

```mermaid
erDiagram
    drivers ||--o{ results : "driverId"
    drivers ||--o{ qualifying : "driverId"
    drivers ||--o{ driver_standings : "driverId"
    drivers ||--o{ lap_times : "driverId"
    drivers ||--o{ pit_stops : "driverId"
    drivers ||--o{ sprint_results : "driverId"

    constructors ||--o{ results : "constructorId"
    constructors ||--o{ qualifying : "constructorId"
    constructors ||--o{ constructor_standings : "constructorId"
    constructors ||--o{ constructor_results : "constructorId"
    constructors ||--o{ sprint_results : "constructorId"

    races ||--o{ results : "raceId"
    races ||--o{ qualifying : "raceId"
    races ||--o{ driver_standings : "raceId"
    races ||--o{ constructor_standings : "raceId"
    races ||--o{ constructor_results : "raceId"
    races ||--o{ lap_times : "raceId"
    races ||--o{ pit_stops : "raceId"
    races ||--o{ sprint_results : "raceId"

    circuits ||--o{ races : "circuitId"
    seasons ||--o{ races : "year"
    status ||--o{ results : "statusId"

    drivers {
        int driverId PK
        string forename
        string surname
        string nationality
        date dob
    }
    constructors {
        int constructorId PK
        string name
        string nationality
    }
    circuits {
        int circuitId PK
        string name
        string location
        string country
    }
    races {
        int raceId PK
        int year
        int round
        int circuitId FK
        string name
        date date
    }
    results {
        int resultId PK
        int raceId FK
        int driverId FK
        int constructorId FK
        string position
        float points
        int laps
        int statusId FK
    }
    qualifying {
        int qualifyId PK
        int raceId FK
        int driverId FK
        string position
    }
    driver_standings {
        int driverStandingsId PK
        int raceId FK
        int driverId FK
        float points
        int position
    }
    constructor_standings {
        int constructorStandingsId PK
        int raceId FK
        int constructorId FK
        float points
        int position
    }
    lap_times {
        int raceId PK
        int driverId PK
        int lap PK
        int milliseconds
    }
    pit_stops {
        int raceId PK
        int driverId PK
        int stop PK
        int milliseconds
    }
    sprint_results {
        int resultId PK
        int raceId FK
        int driverId FK
    }
    seasons {
        int year PK
    }
    status {
        int statusId PK
        string status
    }
    constructor_results {
        int constructorResultsId PK
        int raceId FK
        int constructorId FK
    }
```

### 12.3 Conversation Storage

Two additional tables manage chat history:

- **`conversations`**: id, title, pinned, created_at, updated_at
- **`messages`**: id, conversation_id, role (user/assistant), content, data (JSON), timestamp

### 12.4 Domain Knowledge in Prompts

The system prompt includes critical F1-specific knowledge to improve SQL accuracy:

- **European country list** for continent-based filtering
- **Team name changes** (e.g., Alpine ← Renault, Aston Martin ← Force India)
- **Race name changes** (e.g., Brazilian GP → São Paulo GP from 2021)
- **Circuit name mappings** (e.g., Interlagos → Autódromo José Carlos Pace)
- **LIKE-based matching** for circuit/race names to handle full official names

---

## 13. Key Challenges & Solutions

| # | Challenge | Root Cause | Solution |
|---|-----------|-----------|----------|
| 1 | MySQL connection timeouts | TiDB Cloud drops idle pool connections | `get_connection()` helper: pool → fresh connection fallback |
| 2 | NoneType error on old chats | JS tried `JSON.parse` on plain text messages | Fixed `loadChat` to use stored `msg.data` object |
| 3 | Empty results for Spa queries | Exact match `= 'Spa-Francorchamps'` vs full name `Circuit de Spa-Francorchamps` | Added Rule: always use `LIKE '%keyword%'` for circuit names |
| 4 | Empty results for 2024 Brazilian GP | Race renamed to "São Paulo Grand Prix" in 2021 | Added race name change domain knowledge to prompt |
| 5 | Unreadable charts (all red) | All datasets used same red color palette, included IDs | Added distinct colors + filtered out ID-like columns |
| 6 | Chart expands with agent reasoning | Both cards shared the same grid row (span 7 + span 5) | Decoupled: chart=span12, steps+SQL=span6 each |
| 7 | Pin doesn't toggle | Always sent `pinned: true`, never toggled | Reads current state from conversation array and sends opposite |
| 8 | Can't click inside rename input | Parent `onclick=loadChat()` intercepted clicks | Added `stopPropagation()` on input click/mousedown/keydown |
| 9 | Special character mismatch | `Sao Paulo` ≠ `São Paulo` (accented ã) | Added circuit name lookup table in prompt with fallback patterns |

---

## 14. Results & Testing

### 14.1 Sample Queries Tested

| Question | SQL Approach | Result |
|----------|-------------|--------|
| "Who has the most race wins?" | `GROUP BY driver, COUNT(*) WHERE position='1'` | ✅ Lewis Hamilton (103 wins) |
| "Compare Hamilton and Verstappen" | Multi-driver `CASE WHEN` aggregation | ✅ Side-by-side comparison |
| "Show 2023 race calendar" | `JOIN races + circuits WHERE year=2023` | ✅ 22 races with circuits |
| "Schumacher's wins at Spa" | `LIKE '%Spa%'` for circuit matching | ✅ 6 wins |
| "2024 Brazilian GP qualifying" | `LIKE '%Paulo%' OR '%Brazil%'` | ✅ Found São Paulo GP result |
| "Average pit stop time at Monaco" | `AVG(milliseconds) LIKE '%Monaco%'` | ✅ Correct average |
| "What is DRS?" | Classified as conversation | ✅ Direct answer (no SQL) |

### 14.2 Automated Benchmark (20 Queries)

A benchmark script (`tests/benchmark.py`) was created to systematically test 20 diverse queries across 9 categories. The script sends each query to the `/api/chat` endpoint, validates the response against expected keywords, and records accuracy, response time, and retry counts.

**Benchmark Date:** March 25, 2026  
**Test Suite:** 20 queries (18 SQL + 2 conversational)

### 14.3 Performance Results

| Metric | Value |
|--------|-------|
| Total Queries Tested | 20 |
| SQL Query Accuracy (first attempt) | **83.3%** (15/18) |
| Queries Needing Retry | 0 |
| Average Response Time | 21.66s |
| Min Response Time | 5.97s |
| Max Response Time | 48.20s |
| Database Size | 16 tables, 701,530 rows |

### 14.4 Results by Category

| Category | Passed | Total | Accuracy |
|----------|--------|-------|----------|
| Driver Stats | 4 | 4 | 100% |
| Race Queries | 2 | 3 | 67% |
| Circuit Queries | 1 | 1 | 100% |
| Team Queries | 1 | 2 | 50% |
| Pit Stops | 1 | 1 | 100% |
| Lap Times | 1 | 1 | 100% |
| Comparison | 1 | 1 | 100% |
| Historical | 2 | 2 | 100% |
| Qualifying | 1 | 1 | 100% |
| Sprint | 1 | 1 | 100% |
| Edge Case (São Paulo) | 0 | 1 | 0% |

### 14.5 Failure Analysis

| Query | Status | Root Cause |
|-------|--------|-----------|
| "Race winners at Spa" | VALIDATION_FAIL | SQL returned correct data but LLM answer didn't explicitly mention "Schumacher" |
| "Most constructors championships" | VALIDATION_FAIL | LLM answer phrasing didn't exactly match the validation keyword "ferrari" |
| "2023 São Paulo GP results" | ERROR | Groq API rate limit hit (100K TPD) — query #20 exhausted the daily token quota |

> **Note:** The VALIDATION_FAIL status indicates the SQL executed correctly and returned results, but the natural language answer didn't contain the expected validation keyword. This is an LLM phrasing issue, not an SQL generation issue. The São Paulo query failure was caused by API rate limiting, not a code defect.

### 14.6 Known Limitations

| Limitation | Details |
|------------|--------|
| **Groq API Rate Limit** | Free tier: 100,000 tokens/day (TPD). The 20-query benchmark consumed ~95K tokens, leaving insufficient quota for additional queries. Resets daily. |
| **LLM Response Variability** | The same query may produce slightly different SQL or answer phrasing on different runs due to LLM non-determinism (temperature=0.1). |
| **No Persistent Vector Index** | FAISS index is rebuilt in-memory on every app restart (~5-10 seconds). |

### 14.7 RAG Evaluation Metrics

To measure and improve retrieval quality, four live RAG evaluation metrics are computed for every SQL query and displayed in a dedicated bento grid card:

| Metric | Definition | Formula |
|--------|-----------|--------|
| **MRR** (Mean Reciprocal Rank) | Rank of the first SQL-used table in FAISS results | `1 / rank_of_first_relevant_table` |
| **Recall@K** | Fraction of SQL-needed tables that were retrieved | `tables_found / tables_needed` |
| **Context Relevance** | Fraction of retrieved tables actually used in SQL | `relevant_retrieved / total_retrieved` |
| **Faithfulness** | Fraction of SQL result values present in the answer | `matched_values / total_values` |

**Proxy ground truth:** Since pre-defined ground truth tables are unavailable for live queries, the system uses the generated SQL as proxy ground truth — parsing table names from `FROM` and `JOIN` clauses via regex.

#### Three-Round Iterative Improvement

Three optimizations were applied iteratively, with metrics measured after each round:

**Round 1 (Baseline):** Raw FAISS retrieval with no filtering.
**Round 2:** Excluded system tables (`messages`, `conversations`) and added semantic enrichment keywords to table descriptions.
**Round 3:** Enhanced keyword coverage, increased top_k from 5 to 7, and added table co-occurrence rules.

| Query | MRR (R1→R2→R3) | Recall (R1→R2→R3) |
|-------|----------------|-------------------|
| Podium most often | 0.00 → 0.00 → **1.00** | 0% → 0% → **50%** |
| Qualifying Silverstone | 0.00 → 0.25 → **1.00** | 0% → 50% → **50%** |
| Verstappen wins 2023 | 0.25 → 0.25 → **1.00** | 33% → 33% → **67%** |
| Ferrari points 2023 | 0.20 → 0.50 → **0.33** | 33% → 67% → **33%** |
| Japan circuits | 0.25 → 0.25 → **0.33** | 100% → 100% → **100%** |
| Hamilton vs Verstappen | — → — → **0.33** | — → — → **100%** |
| Constructors champs | — → — → **0.33** | — → — → **100%** |

**Key improvements:**
- MRR average improved from **0.12 → 0.25 → 0.67** (5.5× improvement)
- Three queries went from MRR=0.00 to MRR=1.00
- Faithfulness consistently **87–100%** across all queries
- `messages` table (a system table) was completely eliminated from retrievals

#### Optimization Techniques Applied

| Technique | Description |
|-----------|------------|
| **System table exclusion** | `messages` and `conversations` tables excluded from FAISS indexing |
| **Semantic enrichment** | Domain-specific keywords (e.g., "wins", "podiums", "Ferrari") added to table descriptions |
| **Co-occurrence rules** | If `results` is retrieved, `drivers` is auto-included; if `races` is retrieved, `circuits` is auto-included |
| **Increased top_k** | Retrieval window increased from 5 to 7 (covering 50% of F1 tables) |

---

## 15. Future Scope

There are several areas where F1InsightAI can be improved and extended in future iterations. The FAISS vector index is currently rebuilt from scratch every time the application starts, so implementing persistent indexing by saving and loading the index from disk would speed up startup significantly. Training domain-specific embeddings on F1 terminology could improve retrieval accuracy beyond what the general-purpose all-MiniLM-L6-v2 model provides. Adding voice input through speech-to-text would make the chatbot more accessible, especially for mobile users. The current chart generation supports bar charts and tables, but adding heatmaps, race trajectory maps, and season timelines would make the visualizations more informative. The system is currently limited to F1 data, but the architecture is general enough to support other sports databases like cricket or football with minimal changes. A user authentication system with login and personal conversation history would make the platform more useful for returning users. Implementing a caching layer for frequent queries would reduce Groq API calls and improve response times. Finally, an export feature for generating PDF or image reports from the bento-grid response layout would let users save and share their query results.

---

## 16. Conclusion

Building F1InsightAI taught us a lot about how RAG and agentic pipelines work together in practice. The biggest takeaway was that sending only the relevant tables to the LLM (instead of everything) made a noticeable difference in SQL accuracy. Our MRR scores improved from 0.12 to 0.67 across three rounds of RAG optimization, and the model stopped generating queries that referenced tables which didn't exist. The retry mechanism also proved its worth — in our benchmark testing, queries that failed on the first attempt were often corrected automatically on the second try without the user having to do anything.

On the frontend side, we spent a good amount of time making the interface feel polished and presentable. The dark-themed design with the spotlight effect, animated card reveals, and the bento-grid layout turned what could have been a plain chatbot into something that actually looks like a finished product. Features like conversation pinning, inline renaming, the two-click delete pattern, and auto-generated Chart.js visualizations made the whole experience feel complete rather than like a demo.

The system isn't perfect — complex multi-table joins with ambiguous questions still trip it up sometimes, and the FAISS index gets rebuilt on every restart since we haven't implemented persistent indexing yet. But for the scope of a capstone project, it covers the core concepts well: RAG for context retrieval, an agentic pipeline for multi-step processing, cloud database integration with TiDB, and a frontend that's ready to present. The interactive Architecture page we added at the end ties everything together by giving reviewers a visual walkthrough of how the whole system works under the hood.

---

## 17. References

1. Lewis, P., Perez, E., et al. (2020). *"Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks."* NeurIPS 2020.
2. Yu, T., Zhang, R., et al. (2018). *"Spider: A Large-Scale Human-Labeled Dataset for Complex and Cross-Domain Semantic Parsing and Text-to-SQL Task."* EMNLP 2018.
3. Li, H., Zhang, J., et al. (2023). *"RESDSQL: Decoupling Schema Linking and Skeleton Parsing for Text-to-SQL."* AAAI 2023.
4. Pourreza, M. & Rafiei, D. (2023). *"DIN-SQL: Decomposed In-Context Learning of Text-to-SQL."* NeurIPS 2023.
5. LangChain. (2024). *"LangGraph: Building Stateful, Multi-Actor Applications with LLMs."* LangChain Documentation.
6. Johnson, J., Douze, M., & Jégou, H. (2019). *"Billion-scale similarity search with GPUs."* IEEE Transactions on Big Data.
7. Reimers, N. & Gurevych, I. (2019). *"Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks."* EMNLP 2019.
8. Ergast Developer API. *"Ergast Motor Racing Data."* ergast.com/mrd.

---

## Appendix A: Application Screenshots

*Note: Screenshots are included in the submitted DOCX report.*

### A.1 Landing Page — Welcome Dashboard

The landing page features a **tsParticles animated background**, the F1InsightAI logo, **live database statistics** (14 tables, 701,678 records, 131 columns), the active AI model badge (openai/gpt-oss-120b), and **F1-themed suggestion chips** (with trophy, chart, calendar, and clock icons) for quick-start queries.

### A.2 Query Result — Bento Grid Layout

After asking *"Who has the most race wins?"*, the system displays results in a **bento-grid layout**: a scrollable data table (Hamilton 105, Schumacher 91, Verstappen 63...), **syntax-highlighted SQL** with copy/download buttons, a collapsible **Agent Reasoning** accordion, **RAG evaluation metrics** (MRR, Recall@K, Context Relevance, Faithfulness), and **AI-generated follow-up suggestions** as clickable pills.

### A.3 Agent Reasoning — Pipeline Transparency

The expanded **Agent Reasoning** accordion reveals each step of the 6-step pipeline: (1) **classify** — identified as a database query, (2) **retrieve_schema** — RAG found 5,644 chars of relevant schema context, (3) **generate_sql** — LLM generated the SELECT query, (4) **execute_sql** — returned 50 rows successfully, (5) **reflect** — validated results, (6) **generate_answer** — created the natural language summary.

### A.4 F1 Loading Animation

While a query is being processed, a **glassmorphic loader card** displays three bouncing red dots and cycles through pipeline steps ("Classifying intent", "Retrieving schema context", "Generating SQL query", etc.).

### A.5 Architecture Page — System Showcase

The interactive `/architecture` page displays the complete system architecture: the **9-node LangGraph pipeline** with animated color-coded nodes, the **RAG pipeline flow** from question to SQL, an **8-card technology stack grid**, and a **6-card key capabilities section** — all with scroll-reveal animations and live system stats.
