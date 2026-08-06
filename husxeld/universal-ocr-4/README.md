---
title: OCR MCQ Automation Studio
emoji: 📄
colorFrom: green
colorTo: blue
sdk: docker
pinned: false
license: mit
short_description: OCR PDFs and generate MCQs
---

# OCR → MCQ Automation Studio

FastAPI + browser UI for this flow:

1. Upload PDF/image from browser **or** submit an absolute server path.
2. Run OCR using `auto`, `pdf-text`, or Playwright automation of `olmOCR` web.
3. Store original file, normalized PDF, OCR JSON/TXT, raw OCR, and `content.txt`.
4. Sanitize the whole PDF into one-line plain **Texts** content: no markdown, no tags, no newlines.
5. Generate MCQs from the sanitized content using rotating AI API keys.

## Local run

```bash
make install
make server
# open http://127.0.0.1:4033
```

Smoke test:

```bash
make test-with-server
```

## UI tabs

- **OCR Upload**: upload from device or server path.
- **Uploaded**: list stored files, OCR stats, sanitized preview, downloads, and MCQ generation controls.
- **MCQ Result**: view/copy/download generated MCQs.

## API quick examples

```bash
# Upload local PDF/image bytes
curl -F file=@doc.pdf \
  -F engine=auto \
  -F pages_per_chunk=6 \
  -F concurrency=1 \
  http://127.0.0.1:4033/upload

# Submit server/container path
curl -H 'Content-Type: application/json' \
  -d '{"path":"/abs/path/doc.pdf","engine":"olmocr-web"}' \
  http://127.0.0.1:4033/upload-path

# Poll OCR
curl http://127.0.0.1:4033/status/JOB_ID

# Sanitized content only, one line
curl -L http://127.0.0.1:4033/download/JOB_ID/content

# List uploaded/stored OCR jobs
curl http://127.0.0.1:4033/uploads

# AI catalog
curl http://127.0.0.1:4033/ai/catalog

# Generate MCQs (JSON response)
curl -H 'Content-Type: application/json' \
  -d '{"job_id":"JOB_ID","count":30,"language":"hinglish","provider":"nvidia","model":"qwen/qwen3.5-397b-a17b"}' \
  http://127.0.0.1:4033/mcq/generate

# Generate MCQs with realtime SSE logs
curl -N -H 'Accept: text/event-stream' -H 'Content-Type: application/json' \
  -d '{"job_id":"JOB_ID","count":30,"language":"hinglish","provider":"nvidia","model":"qwen/qwen3.5-397b-a17b"}' \
  http://127.0.0.1:4033/mcq/generate/stream
```

MCQ output contains `question`, 4 options (`A-D`), `correct_answer`, `explanation`, and a short `source_quote`. The UI uses `/mcq/generate/stream` with provider `stream=true` and shows live logs for prompt prep, provider/model/key, streamed characters, retries, AI response, parsing, saving, and HF storage sync. While streaming, partial raw AI text is saved continuously to `mcq-<GENERATION_ID>.partial.txt` and progress metadata to `mcq-<GENERATION_ID>.progress.json`.

## AI keys and rotation

The app is self-contained and loads only this folder's local `.env` file plus process/Hugging Face secrets. It supports these key names:

- Ollama Cloud: `OLAPI1`, `OLAPI2`, ...
- NVIDIA: `NVAPI1`, `NVAPI2`, ... or `NVIDIA_API_KEY`
- OpenRouter: `OPAPI1`, ... or `OPENROUTERAPI1`, ...

The key rotator uses a random bag and avoids using the same key twice in a row when more than one key exists.

## Hugging Face Spaces

This repo is Docker Space-ready. Docker listens on port `7860`.

Storage:

- Docker sets `OCR_DATA_DIR=/data/ocr-automation`.
- If Hugging Face persistent storage is attached, files survive restarts.
- Without persistent storage, free Spaces still work but storage is ephemeral.

Useful env/secrets:

- `HF_TOKEN`, `HF_USERNAME`
- `OCR_DEFAULT_ENGINE=auto|olmocr-web|pdf-text`
- `OCR_AI_PROVIDER=nvidia|ollama_cloud|openrouter`
- `OCR_AI_MODEL=...`
- `NVAPI1...`, `OLAPI1...`, `OPAPI1...`
- `OCR_PAGES_PER_CHUNK=6`
- `OCR_CHUNK_CONCURRENCY=1`
- `OCR_ALLOW_SERVER_PATH=1`
- `OCR_AI_CONTEXT_MAX_CHARS=180000`

Deploy helper:

```bash
scripts/deploy_hf.sh
```

## Files

- `app/main.py` - FastAPI OCR, storage, sanitized text, MCQ routes
- `app/ai_service.py` - AI providers + rotating keys
- `app/static/index.html` - no-build UI
- `Dockerfile` - Hugging Face Docker Space image
- `Makefile` - local server/test/docker commands
- `scripts/smoke_test.py` - local smoke test
- `scripts/deploy_hf.sh` - HF CLI private Docker Space deploy
