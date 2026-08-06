---
title: PaperLens
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# PaperLens

PaperLens is a citation-grounded research assistant for technical papers. It answers questions from selected research papers using hybrid retrieval, reranking, and source-backed evidence.

The project is designed as a practical RAG system, not just a PDF chatbot. It focuses on transparent retrieval, page-level citations, evidence strength, benchmarked retrieval quality, and a custom deployed web experience.

## Live Demo

Hugging Face Space:

https://huggingface.co/spaces/sc-ss/paperlens

## Current Features

- Custom FastAPI backend
- Custom HTML, CSS, and JavaScript frontend
- Docker deployment on Hugging Face Spaces
- Built-in sample paper collection
- Paper source filtering
- Semantic search with Sentence Transformers and FAISS
- Keyword search with BM25
- Hybrid retrieval using Reciprocal Rank Fusion
- Cross-encoder reranking
- Citation-grounded answer generation
- Evidence strength labels
- Citation cards with page numbers
- Evidence cards with retrieval and reranking scores
- Recent question history in the browser
- Random sample question button
- Select all and clear paper filters
- Copy answer button
- Downloadable answer report

## Paper Collection

The default demo uses five public AI research papers:

- Attention Is All You Need
- BERT
- Retrieval-Augmented Generation
- LoRA
- Chain-of-Thought Prompting

## Architecture

```text
PDF papers
  -> page-level text extraction
  -> page-aware chunking
  -> Sentence Transformer embeddings
  -> FAISS semantic search
  -> BM25 keyword search
  -> Reciprocal Rank Fusion
  -> cross-encoder reranking
  -> citation-grounded answer
  -> custom web UI
```

## Retrieval Modes

| Mode | Description |
|---|---|
| Semantic search | Uses dense embeddings and FAISS to find meaning-based matches |
| Hybrid search | Combines FAISS semantic search and BM25 keyword search with Reciprocal Rank Fusion |

Hybrid search is the default because technical papers often contain exact method names, acronyms, and equations where keyword matching helps semantic retrieval.

## Model Choices

| Component | Model / Tool |
|---|---|
| Embeddings | BAAI/bge-small-en-v1.5 |
| Vector search | FAISS |
| Keyword search | BM25 |
| Fusion | Reciprocal Rank Fusion |
| Reranker | cross-encoder/ms-marco-MiniLM-L-6-v2 |
| Backend | FastAPI |
| Frontend | HTML, CSS, JavaScript |
| Deployment | Hugging Face Spaces Docker |

## Evaluation

PaperLens was evaluated on 15 manually written questions across five AI research papers.

| Metric | Result |
|---|---:|
| Top-1 paper routing accuracy | 100% |
| Top-5 paper routing accuracy | 100% |
| Strict page-level citation hit rate | 86.7% |

The strict page-level citation metric checks whether retrieved evidence appears on the expected source page. This is intentionally harder than just finding the correct paper.

## Demo Questions

Try these in the live app:

- What is self-attention and why is it useful?
- What is masked language modeling in BERT?
- What is next sentence prediction in BERT?
- How does retrieval augmented generation use external knowledge?
- What is the role of the retriever in RAG?
- How does LoRA reduce the number of trainable parameters?
- What parameters are trained in LoRA?
- Why does chain-of-thought prompting improve reasoning?

## API Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/` | GET | Serves the PaperLens web app |
| `/api/health` | GET | Returns index status and collection stats |
| `/api/version` | GET | Returns project version and model details |
| `/api/papers` | GET | Lists indexed papers |
| `/api/search` | POST | Searches selected papers and returns answer, citations, and evidence |
| `/api/benchmark` | GET | Returns benchmark metrics |

## Run Locally

Install dependencies:

```bash
pip install -r requirements.txt
```

Start the app:

```bash
uvicorn api.main:app --host 0.0.0.0 --port 7860
```

Open:

```text
http://localhost:7860
```

## Project Structure

```text
paperlens/
  api/
    main.py
    paper_service.py
    schemas.py
    version.py
  web/
    index.html
    styles.css
    app.js
  src/
    pdf_reader.py
    text_chunks.py
    search_index.py
    hybrid_search.py
    reranker.py
    answer_writer.py
    evaluation.py
  data/
    papers/
    questions/
  artifacts/
  assets/
    screenshots/
    diagrams/
  Dockerfile
  requirements.txt
  README.md
```

## What I Learned

- Built an end-to-end RAG pipeline from PDFs to cited answers
- Preserved page metadata for citation reliability
- Compared embedding models using retrieval benchmarks
- Improved retrieval with FAISS, BM25, RRF, and reranking
- Deployed a custom FastAPI Docker app on Hugging Face Spaces
- Built a more dynamic frontend without relying on Streamlit
- Added practical UX features such as source filters, recent questions, and downloadable reports

## Limitations

- Scanned or image-based PDFs may need OCR.
- Free CPU deployment can be slower during cold starts.
- The current default collection is limited to five papers.
- Page-level evaluation is strict, so useful evidence may sometimes appear on a nearby page.
- The answer writer is extractive and does not require a paid LLM API.

## Future Improvements

- Add OCR support for scanned PDFs
- Add upload mode to the FastAPI interface
- Save and load prebuilt search artifacts for faster startup
- Expand the benchmark from 15 to 30 questions
- Add side-by-side semantic vs hybrid retrieval comparison
- Add section-aware citations such as paper, page, and section name
- Add optional user-provided LLM key support while keeping the free no-key mode

## Resume Bullet

Built and deployed PaperLens, a citation-grounded RAG assistant over AI research papers using PDF parsing, FAISS vector search, BM25 keyword retrieval, Reciprocal Rank Fusion, cross-encoder reranking, and retrieval evaluation; achieved 100% top-1 paper routing accuracy and 86.7% strict page-level citation hit rate across 15 benchmark questions.
