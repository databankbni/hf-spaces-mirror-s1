---
title: RICS Report Genius
emoji: 🏠
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: RICS v2 report generator from past reports + notes.
---

# Report Genius AI

Report Genius AI turns a surveyor's **messy site notes** (and optional inspection photos) into a
structured **RICS Home Survey Level 3** report draft — written in the firm's own voice — that the
surveyor then reviews, edits, and signs off. It is a Retrieval-Augmented Generation (RAG) system:
each firm's own past reports and standard paragraphs shape the *wording*, while the surveyor's notes
remain the only source of *facts*. Data is isolated per firm ("tenant").

The backend is a Python **FastAPI** service (`backend/`, started with `uvicorn backend.main:app`);
the UI is a single static HTML file (`frontend/index.html`). There is **no SQL database** — all state
is files on disk under `DATA_DIR`, and the FAISS search index runs inside the API process.

---

## Documentation

**Start here:** the full technical documentation pack lives in **[docs/](docs/README.md)**. It takes a
new engineer from zero to contributing — architecture, the AI pipeline, retrieval, prompts, APIs,
setup, deployment, testing, security, and current status.

Fast links:

- New to the project? [docs/01 — System overview](docs/01-system-overview.md)
- Where does code live? [docs/02 — Architecture & code map](docs/02-architecture-and-code-map.md)
- Getting it running? [docs/09 — Development setup](docs/09-development-setup.md)
- Gentle narrative tour: [docs/CODEBASE_GUIDE.md](docs/CODEBASE_GUIDE.md)

---

## Quick start

Prerequisites: **Python 3.11+**, an **OpenAI API key** (optional for offline dev), and Docker if you
want the container path. Full instructions with troubleshooting are in
[docs/09 — Development setup](docs/09-development-setup.md).

```bash
git clone https://github.com/My-Report-AI/Report-genius-ai.git
cd Report-genius-ai
cp .env.example .env          # then set OPENAI_API_KEY and, for local dev, PDF_EXTRACTOR=pypdf

python -m venv .venv
.venv\Scripts\activate        # Windows (macOS/Linux: source .venv/bin/activate)
pip install -e ".[dev]"
pip install -r backend/requirements.txt

uvicorn backend.main:app --reload --port 8000
# open http://localhost:8000  (interactive API docs at /docs)
```

Docker (local/demo image, bakes the embedding + reranker models for offline start):

```bash
docker compose -f docker-compose.v2.yml up --build   # http://localhost:8000
```

The first local run downloads the local embedding + reranker weights (multi-GB, several GB RAM). See
[docs/10 — Deployment & configuration](docs/10-deployment-and-configuration.md) for the deploy paths
and the full configuration reference.

---

## Repository layout

| Path | What it is |
|------|------------|
| `backend/` | The FastAPI backend — all business logic (see [docs/02](docs/02-architecture-and-code-map.md)) |
| `frontend/` | `index.html` (production UI) and `v2.html` (demo UI) |
| `docs/` | This documentation pack |
| `scripts/`, `backend/scripts/` | Operator/ingest tooling and dev/deploy helpers |
| `Dockerfile` | Hugging Face Spaces image (port 7860) |
| `Dockerfile.v2`, `docker-compose.v2.yml` | Local/demo image (port 8000) |
| `Master Standard report and paragraphs/` | Operator template bundle (runtime; may be absent locally) |

---

## Running tests

```bash
python -m pytest backend/tests -q -o addopts=""   # offline; no API key needed
```

The suite is offline and deterministic by default (LLM/embeddings are stubbed). One caveat: if your
local `.env` sets `PII_SCRUBBING_ENABLED=false`, a number of PII tests fail *by design* — see
[docs/09](docs/09-development-setup.md#troubleshooting) and
[docs/11](docs/11-testing-and-evaluation.md). Lint/type-check with `black`, `ruff`, and `mypy backend/`.

---

## Deployment

- **Hugging Face Spaces** (current demo): built from `Dockerfile`, served on port 7860.
- **Local/demo Docker:** `Dockerfile.v2` + `docker-compose.v2.yml`, port 8000.

Details, CI, and environments: [docs/10 — Deployment & configuration](docs/10-deployment-and-configuration.md).

------

## Licence

MIT — see [LICENSE](LICENSE).
