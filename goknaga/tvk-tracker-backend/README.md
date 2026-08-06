---
title: TVK Tracker Backend
emoji: 🛡️
colorFrom: red
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: FastAPI backend for the TVK Files accountability tracker
---

# TVK Tracker Backend

FastAPI service that:
- Receives news article webhooks from Apify
- Processes them via OpenRouter → Claude Haiku 4.5 (categorize, flag credit-steals)
- Stores incidents in Supabase
- Serves stats + incidents to the Next.js frontend

## Endpoints
- `GET /health` — health check
- `GET /api/stats/dashboard` — top-line counters
- `GET /api/incidents/` — list approved incidents
- `GET /api/promises/` — manifesto promises
- `GET /api/members/` — TVK cabinet members
- `POST /api/ingest/apify-webhook` — Apify scraper webhook (auth: `x-apify-secret`)
- `POST /api/ingest/manual` — admin manual article submission

## Environment variables (set in HF Space settings)
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `OPENROUTER_API_KEY`
- `APIFY_API_TOKEN`
- `ADMIN_SECRET`
- `GOVT_START_DATE` (default `2026-05-11`)
- `ALLOWED_ORIGINS` (comma-separated, include Vercel frontend URL)

## Local dev
```bash
pip install -r requirements.txt
cp .env.example .env  # fill in keys
uvicorn app.main:app --reload --port 8000
```

Source repo: https://github.com/gokulnaga0305-wq/tvk-tracker
