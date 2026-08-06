---
title: Dementia Risk API
emoji: 🧠
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
---

# Dementia Risk Predictor API

FastAPI backend for the Dementia Risk Predictor project.
Built with XGBoost trained on non-medical variables from the NACC Uniform Data Set.

## Endpoints
- `GET /` — health check
- `GET /health` — model status
- `POST /predict` — risk prediction
- `POST /explain` — SHAP explanation
- `GET /metrics` — model comparison metrics
- `GET /feature-importance` — global SHAP ranking