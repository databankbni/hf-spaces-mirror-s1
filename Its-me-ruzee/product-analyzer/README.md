---
title: Product Analyzer
emoji: 🔍
colorFrom: blue
colorTo: purple
sdk: docker
pinned: false
license: mit
short_description: Multi-layer content moderation for e-commerce products
---

# Product Analyzer v2.0

Multi-layer content moderation system for detecting inappropriate e-commerce products.

## Architecture

### Analysis Pipeline

| Layer | What | How | Speed |
|-------|------|-----|-------|
| **Layer 1** | Keyword matching | Local regex + leet-speak decoder | Instant |
| **Layer 2** | NSFW text classification | HF Inference API (`michellejieli/NSFW_text_classifier`) | ~10-30s |
| **Layer 3** | Image text extraction | HF Inference API (`Salesforce/blip-image-captioning-large`) | ~10-30s per image |
| **Layer 4** | NSFW image detection | HF Inference API (`Falconsai/nsfw_image_detection`) | ~10-30s per image |

- **Layer 1** runs locally for instant feedback (keyword/regex, no API calls)
- **Layers 2-4** use HF Inference API (free tier) with rate limiting
- Jobs are queued and processed sequentially to respect API limits

### Supported Languages (Layer 1 Keywords)

- English
- Tamil (Roman + Unicode script)
- Sinhala (Roman + Unicode script)

### Prohibited Categories

Explicit content, weapons, drugs, alcohol, gambling, piracy, hate/violence, suspicious APKs, slang/euphemisms

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/analyze` | Submit product for analysis |
| GET | `/job/{job_id}` | Check job status and result |
| GET | `/queue/stats` | Queue stats and rate limit status |
| GET | `/health` | Health check |
| GET | `/test` | Test Layer 1 (should flag) |
| GET | `/test-clean` | Test Layer 1 (should pass) |
| GET | `/test-api` | Test Layer 2 API (slow) |
| GET | `/rate-limit-status` | Check API rate limits |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `HF_TOKEN` | Yes | Hugging Face API token for Inference API |

Set `HF_TOKEN` in HF Spaces Settings → Repository Secrets.

## Rate Limiting (Free Tier)

- Max 10 API requests/minute
- Max 950 requests/day (safety margin under 1000 limit)
- 6-second minimum between requests
- Exponential backoff on 429 errors
- Estimated processing: 2-4 minutes per product (3 API calls)

## Tech Stack

- **Runtime:** Python 3.11 + FastAPI + Uvicorn
- **AI:** HF Inference API (free tier) — no local model loading
- **Container:** Docker (slim image, no PyTorch)

## Deployment

1. Set `HF_TOKEN` in HF Spaces repository secrets
2. Push to HF Space — Docker build is instant (no model downloads)
3. App starts in seconds
