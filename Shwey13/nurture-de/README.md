---
title: NurtureDE
emoji: 🤰
colorFrom: green
colorTo: gray
sdk: gradio
sdk_version: 6.24.0
python_version: '3.11'
app_file: app.py
pinned: false
license: mit
---

# NurtureDE

A cited, official-source Q&A assistant for pregnancy, *Mutterschutz*, and family benefits in
Germany — it reports what official German sources say and cites them, never decides eligibility,
and refuses medical questions. Ask in English or German.

**Not medical or legal advice — a portfolio prototype.** Stores nothing.

Source code, build journal, and the pipeline visualiser:
**https://github.com/shwey13fra/nurture-de**

The reranker is offloaded to a hosted API (Jina); everything else — E5 query embedding, Chroma,
BM25 — runs in this container from a prebuilt index.
