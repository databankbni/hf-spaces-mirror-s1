# Free Hugging Face Deployment Notes

This Phase 1 MVP is designed for a free Hugging Face Space with external triggering.

## What runs on the Space
- FastAPI query API
- `/refresh-match` on demand
- local cache
- optional upload to HF Dataset when `HF_DATASET_REPO` and `HF_TOKEN` are set

## What does NOT rely on free HF
- No HF Jobs required
- No long-running infinite scraper loop inside the Space
- No Playwright/Chromium
- No prediction/final_pick/bankroll/case_memory

## Required Space Variables / Secrets
Variables:
- `HF_DATASET_REPO=your-name/football-data-hub`
- `VENDOR_DIR=vendor/hermes_source`
- `DEFAULT_COMPANY_IDS=3,24,8`

Secrets:
- `HF_TOKEN=<your token>`
- `HF_DATA_HUB_API_KEY=<random write API key>`

## Start command
The Dockerfile starts:
`uvicorn app:app --host 0.0.0.0 --port 7860`

## Triggering
Use Hermes keepalive, local cron, or GitHub Actions to call:
`POST /refresh-match`
