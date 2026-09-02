# CareerTrust AI Services

AI microservices for the CareerTrust platform, focused on recruitment intelligence and candidate analysis.

## Overview

This repository contains the Python/FastAPI AI service used by CareerTrust. It provides:

- Job recommendation and matching (hybrid semantic + rule-based scoring)
- Face detection and embedding extraction for verification workflows
- Resume parsing and related AI utilities

Primary service directory:

- `backend-ai/`

## Tech Stack

- Python
- FastAPI + Uvicorn
- InsightFace (face detection/embeddings)
- Sentence-transformers and ML/NLP tooling (via `requirements.txt`)

## Repository Structure

```text
careerTrust-AIServices/
├─ backend-ai/
│  ├─ app/
│  │  ├─ face_recognition/        # Face embedding routes and utilities
│  │  ├─ resume/                  # Resume parsing routes and parser
│  │  ├─ job_recommendation/      # Job recommendation engine modules
│  │  ├─ sentiment_analysis/      # Review sentiment inference routes
│  │  └─ main.py                  # FastAPI app entrypoint
│  ├─ model_output_v3/            # Model outputs/artifacts
│  ├─ requirements.txt            # Python dependencies
│  ├─ setup-venv.ps1              # Optional Windows venv setup helper
│  ├─ test_matching_examples.py   # Matching behavior examples/tests
│  ├─ test_model_diagnostics.py   # Model diagnostics script
│  └─ MATCHING_ARCHITECTURE.md    # Detailed matching system design
└─ README.md                      # Repository documentation (single source)
```

## Quick Start (Windows PowerShell)

```powershell
cd backend-ai
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Service will be available at:

- `http://localhost:8000`

## Running Diagnostics and Tests

From `backend-ai/`:

```powershell
python test_matching_examples.py
python test_model_diagnostics.py
```

## Matching System

The recommendation engine uses a production-oriented hybrid approach:

- Skills: set coverage + semantic similarity + bonus logic
- Job title: semantic similarity + hierarchy awareness
- Experience: numeric rule-based scoring
- Summary: semantic relevance scoring

For detailed design and scoring rationale, see:

- `backend-ai/MATCHING_ARCHITECTURE.md`

## Notes

- This service extracts and returns face embeddings; storage and duplicate checks are handled by the main backend.
- Keep `.venv/` out of version control.

## Troubleshooting

If `insightface` fails to install on Windows:

1. Install Visual C++ Build Tools (Desktop development with C++).
2. Reopen PowerShell.
3. Retry dependency installation:

```powershell
pip install -r requirements.txt
```

## License

Private/internal project for CareerTrust.
