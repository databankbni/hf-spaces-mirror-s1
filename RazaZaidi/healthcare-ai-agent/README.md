---
title: Healthcare AI Agent
emoji: 🏥
colorFrom: green
colorTo: blue
sdk: docker
pinned: false
---

# Healthcare AI Agent

An AI-powered healthcare assistant built with FastAPI, multi-agent routing, OCR report parsing, and Docker deployment.

## Live Deployment

- Hugging Face Space (Live): https://huggingface.co/spaces/RazaZaidi/healthcare-ai-agent
- GitHub Repository: https://github.com/rsyedmuhammad428-cmd/HealthCare_AI_Project

## Key Features

- Intelligent healthcare chat assistant
- Multi-agent routing:
  - General Assistant
  - Research Agent
  - Lifestyle Agent
  - Emergency Guidance Agent
- Medical report upload and parsing:
  - PDF, image, DOCX, TXT support
  - OCR with Tesseract
  - Basic vitals extraction and analysis
- User authentication and chat history
- Dockerized deployment (local + cloud)

## Tech Stack

- Backend: FastAPI, Uvicorn
- AI/Agent Framework: LangChain, LangGraph
- OCR/Parsing: Tesseract, pdfplumber, Pillow
- Database: SQLite
- Containerization: Docker, Docker Compose
- Hosting: Hugging Face Spaces (Docker SDK)

## Run Locally (Docker)

```bash
docker compose up -d
```

Local app URL:

- http://127.0.0.1:7860/

Health endpoint:

- http://127.0.0.1:7860/api/health

## Environment Variables

Configure these in your `.env`:

- `SECRET_KEY`
- `GROQ_API_KEY`
- `GROQ_MODEL` (optional; defaults to `openai/gpt-oss-20b`)
- `GOOGLE_API_KEY`
- `OPENROUTER_API_KEY`
- `HOST` (default `0.0.0.0`)
- `PORT` (default `7860` for Space deployment)
- `DB_PATH`
- `UPLOAD_DIR`

## Deployment Notes

- Hugging Face Docker Spaces require the app to listen on port `7860`.
- Binary/runtime files (e.g., `uploads/`, large media, local DB snapshots) should not be pushed to Space git history.
- Keep API keys in Space Secrets / environment settings, not in source code.

## Project Status

This project is fully deployed and running on Hugging Face Spaces:

- https://huggingface.co/spaces/RazaZaidi/healthcare-ai-agent
