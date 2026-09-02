# Mahabharata Character Chatbot — Architecture & RAG Design

A retrieval-augmented generation (RAG) system that lets a user converse with 27 characters
of the Mahabharata. Each character answers in the first person, grounded in a corpus of
source texts (novels, retellings, and curated memories) rather than the language model's
parametric memory alone.

This document explains the system end to end and the design decisions behind it — written
to double as interview preparation.

---

## 1. What problem RAG solves here

A raw LLM "knows" the Mahabharata only as a blurry average of its training data. It will
confidently invent details. RAG fixes this by **retrieving** relevant passages from a
trusted corpus at query time and **augmenting** the prompt with them, so the model
**generates** an answer anchored in real text.

> One-line definition: *RAG = retrieve relevant documents from a vector store, inject them
> into the prompt, and let the LLM generate an answer grounded in them.*

The LLM (Groq) is the generator — it is supposed to be in the loop. What makes this RAG and
not "a single API call" is that **every** turn runs a retrieval step against a vector index
first, and the retrieved text is what the model is instructed to answer from.

---

## 2. Two-phase pipeline

### Phase 1 — Indexing (offline, run once via `src/ingest.py`)

| Step | Component | Detail |
|------|-----------|--------|
| Load | `PyPDFLoader`, `TextLoader` | Read `Books/*.pdf` and `data/*_memories.txt` into `Document` objects |
| Split | `RecursiveCharacterTextSplitter` | Chunk to ~800 chars, 120 overlap, on natural boundaries |
| Embed | `HuggingFaceEmbeddings` (`all-MiniLM-L6-v2`) | Each chunk → 384-dim vector, computed locally |
| Store | `PineconeVectorStore` | Upsert vectors + metadata (`source`, `type`) into the `mahabharata-characters` index |

The index is wiped and rebuilt on each run for reproducibility.

### Phase 2 — Query (online, every message via `src/character_bot.py`)

| Step | Component | Detail |
|------|-----------|--------|
| Bias + embed | `RunnableLambda` + retriever | Prepend the character name to the question, embed with the **same** model |
| Retrieve | `.as_retriever(k=6)` | Cosine-similarity search returns the top-k most relevant chunks |
| Augment | `ChatPromptTemplate` | Inject `{context}`, `{chat_history}`, and persona (`traits/style/values`) |
| Generate | `ChatGroq` (`llama-3.3-70b-versatile`) | Produce the in-character answer |
| Parse | `StrOutputParser` | Extract the plain string |
| Cite | `_extract_sources` | Return the de-duplicated `source` of each retrieved chunk |

**Critical invariant:** indexing and querying must use the *same* embedding model, because
similarity is only meaningful inside one shared vector space.

---

## 3. The chain (LCEL)

The query pipeline is composed with LangChain Expression Language (the `|` operator). It is
built to return **both** the answer and its source documents — the classic "return source
documents" RAG pattern:

```python
retrieve_docs = RunnableLambda(
    lambda x: retriever.invoke(f"{character_name}: {x['question']}")
)

generate_answer = (
    { "context": lambda x: format_docs(x["docs"]),
      "question": lambda x: x["question"],
      "chat_history": lambda x: history_string(),
      ... persona vars ... }
    | prompt | llm | StrOutputParser()
)

rag_chain = (
    RunnablePassthrough.assign(docs=retrieve_docs)
    | RunnablePassthrough.assign(answer=generate_answer)
)
```

Input `{"question": ...}` flows through, gains `docs`, then `answer`. The final dict carries
everything needed to display the reply *and* cite where it came from.

---

## 4. Key design decisions (and how to defend them)

**Why a shared retrieval pool instead of one index per character.**
Every book is titled after one character but is full of scenes involving everyone. Hard-
filtering by character would be precise but destroy recall — talking to Bhishma would lose
all the Bhishma scenes that live inside the Karna book. Instead, all chunks share one pool
and the query is **biased** with the character's name, so their own passages rank highest
while shared events stay reachable. This is a deliberate **precision-vs-recall trade-off**.

**Why `all-MiniLM-L6-v2` for embeddings.**
384 dimensions, runs locally, no per-call cost, no data leaving the machine. Good enough
semantic quality for narrative prose. Trade-off: larger hosted models (e.g. OpenAI
`text-embedding-3`) would retrieve marginally better but add cost and a network dependency.

**Why ~800-char chunks with overlap.**
Small enough that a retrieved chunk is mostly on-topic (precision), large enough to hold a
coherent scene. Overlap prevents a sentence being orphaned at a chunk boundary.

**Why cosine similarity.**
Sentence-transformer embeddings are direction-meaningful, not magnitude-meaningful; cosine
compares orientation, which is the standard choice for this model family.

**Why source citations.**
Returning and displaying the originating book is the strongest evidence the answer is
grounded and not hallucinated — and it makes the RAG loop visible to the user.

**Persona without 27 models.**
A single `MahabharataCharacter` class produces all personalities from config-driven prompt
variables (`traits/style/values` in `characters_config.json`) plus name-biased retrieval.
Scalable: adding a character is a config entry + memory file, not new code.

---

## 5. Anti-hallucination guardrail

The prompt instructs the model to answer **from the retrieved passages first**, to avoid
inventing specific facts, and to admit when the texts do not cover something rather than
fabricate. This keeps the LLM's fluency while constraining it to the corpus.

---

## 6. Tech stack

- **Orchestration:** LangChain (LCEL chains, loaders, splitters, retrievers)
- **LLM:** Groq — `llama-3.3-70b-versatile`
- **Embeddings:** HuggingFace `all-MiniLM-L6-v2` (sentence-transformers)
- **Vector DB:** Pinecone (serverless, cosine, 384-dim)
- **Backend:** Flask (web API) + a CLI entry point
- **Persistence:** SQLite + text files for chat history
- **Frontend:** vanilla HTML/CSS/JS

---

## 7. Roadmap — deeper RAG techniques

Implemented:
- [x] Book ingestion (PDF → chunks → vectors)
- [x] Name-biased shared-pool retrieval
- [x] Source-document citations in the UI
- [x] Grounding-focused prompt

Strong next steps to discuss or build:
- [ ] **History-aware retrieval** — rewrite follow-up questions into standalone queries using
  chat history before retrieving (`create_history_aware_retriever`).
- [ ] **MMR retrieval** — `search_type="mmr"` for relevant *and* diverse chunks.
- [ ] **Evaluation** — RAGAS metrics: faithfulness, answer relevancy, context precision/recall.
- [ ] **Reranking** — a cross-encoder to reorder retrieved chunks before generation.
- [ ] **OCR** — run OCR on scanned PDFs so image-only books become searchable.

---

## 8. Interview talking points (cheat-sheet)

- *"It's RAG because every turn retrieves from a Pinecone vector index and the LLM is
  instructed to answer from those passages — the model is the generator, not the knowledge."*
- *"I chose name-biased retrieval over hard metadata filtering as a precision/recall trade-off."*
- *"Indexing and querying share one embedding model so vectors are comparable."*
- *"I return source documents and cite them, which is both a UX feature and a hallucination check."*
- *"The chain is built in LCEL with `RunnablePassthrough.assign` so it emits answer + sources."*
- *"One class + config drives 27 personas; adding a character needs no new code."*
