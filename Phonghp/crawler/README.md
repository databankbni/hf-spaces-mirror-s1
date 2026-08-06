---
title: Crawler Web Truyen
emoji: 📚
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

Dự án Crawler và Convert truyện chữ tự động.
- Framework: FastAPI
- Engine: Playwright (Chromium)
- Translator: Aho-Corasick (1.4M phrases)
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --reload