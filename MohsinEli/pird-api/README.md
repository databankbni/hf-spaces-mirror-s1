---
title: PIRD API
emoji: 📜
colorFrom: yellow
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
license: mit
---

# PIRD API — Paraphrase-Robust AI-Text Detection as a REST service

FastAPI wrapper around the trained PIRD checkpoint. CORS is open so browser
front-ends (e.g. the Next.js site on Vercel) can call it directly.

## Endpoints

- `GET /` — service info / health.
- `POST /predict` — body `{"text": "..."}` (≥ 20 words) → `{"p_ai": 0.97, "label": "ai", "words": 42}`.

`p_ai` is a temperature-calibrated probability that the passage is AI-generated.

## Notes

- Runs on CPU (free tier); single-text inference ≈ 1–2 s.
- Research demo — probabilistic output; do not use as sole evidence of misconduct.
