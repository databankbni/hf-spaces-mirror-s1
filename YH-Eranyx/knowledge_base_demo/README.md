---
title: Knowledge Base Demo
emoji: 🌍
colorFrom: indigo
colorTo: pink
sdk: gradio
sdk_version: 6.20.0
python_version: '3.11'
app_file: app.py
pinned: false
---

# Knowledge Base Demo (RAG)

Upload a PDF and ask questions grounded in that document.

## Secrets / Variables

- `GROQ_API_KEY` (secret): required
- `DAILY_TOKEN_LIMIT` (variable, optional): shared daily token budget for all users (default `50000`)
- `GROQ_MODEL` (variable, optional): override Groq model (default `llama-3.1-8b-instant`)