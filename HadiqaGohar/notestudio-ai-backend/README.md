---
title: NoteStudio AI Backend
emoji: 🎵
colorFrom: purple
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
license: mit
---

# NoteStudio AI Backend

FastAPI backend powering NoteStudio AI — a lightweight NotebookLM clone built with free AI tools.

## Features
- **Chat/Q&A** — Ask questions grounded in source text (Gemini via OpenRouter)
- **Audio Overview** — Narrated audio summaries (edge-tts)
- **Image Generation** — Illustrative images (Pollinations.ai)
- **Video Generation** — Slideshow videos with narration (moviepy + ffmpeg)

## API Endpoints
- `POST /api/chat` — Chat with source text
- `POST /api/audio` — Generate audio overview
- `POST /api/image` — Generate illustrative image
- `POST /api/video` — Generate video with images + narration
- `GET /api/health` — Health check

## Environment Variables
- `OPENROUTER_API_KEY` — Required. Set as a Hugging Face secret.
