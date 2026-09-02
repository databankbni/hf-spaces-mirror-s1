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

## Website embed (16:9 hero)

Use the Space's direct `*.hf.space` URL (or `?embed=true`) so Hugging Face chrome stays out of the iframe:

```html
<div style="position:relative;width:100%;aspect-ratio:16/9;border-radius:16px;overflow:hidden;">
  <iframe
    src="https://YOUR-USERNAME-YOUR-SPACE.hf.space"
    title="RAG Knowledge Base"
    style="position:absolute;inset:0;width:100%;height:100%;border:0;"
    allow="clipboard-write"
    loading="lazy"
  ></iframe>
</div>
```

The app is scrollable, so the full RAG explainer sits under the chat UI in both the Space page and the website iframe.

## Secrets / Variables

- `GROQ_API_KEY` (secret): required
- `DAILY_TOKEN_LIMIT` (variable, optional): shared daily token budget for all users (default `50000`)
- `GROQ_MODEL` (variable, optional): override Groq model (default `llama-3.1-8b-instant`)