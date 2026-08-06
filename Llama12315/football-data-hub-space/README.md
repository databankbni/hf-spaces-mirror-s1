---
title: Football Data Hub Phase 1
emoji: 🏟️
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
license: mit
---

# HF Football Data Hub Phase 1 MVP

A free-Hugging-Face-compatible data layer for the Hermes football prediction system.

This project migrates only the **data acquisition / compact packet** layer:
- Titan007 compact/raw fetch
- multi-company ADI/SFI/convergence analysis
- K-line compact summary
- compact packet API
- optional HF Dataset persistence
- Hermes client with local fallback support

It does **not** migrate:
- final_pick
- strong_model_review
- bankroll_records
- MATCH_TRACKER_MASTER
- case_memory
- post_match_reviews

Those remain in Hermes local execution.

## Free HF Architecture

```
External trigger / Hermes keepalive / GitHub Actions
  -> HF Space API
  -> vendor Hermes fetch scripts
  -> compact_match_packet
  -> local cache + optional HF Dataset upload
  -> Hermes hf_data_client.py
```

No HF Jobs are required for Phase 1.

## Endpoints

- `GET /health`
- `GET /hot-matches?date_=YYYY-MM-DD`
- `POST /hot-matches`
- `GET /match-packet?match_id=...&date_=YYYY-MM-DD`
- `GET /crow-screener?match_id=...&date_=YYYY-MM-DD` (Dataset-only, data-only)
- `POST /refresh-match`
- `GET /source-status`

## Local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 7860
```

## Tests

```bash
pip install -r requirements.txt pytest
pytest -q
```
