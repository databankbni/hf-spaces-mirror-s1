---
title: GenAI Gradio Space
emoji: 💬
colorFrom: indigo
colorTo: purple
sdk: gradio
sdk_version: 4.44.0
app_file: app.py
pinned: false
license: mit
---

# GenAI Gradio Space

Instant-demo flavor of Hugging Face Spaces — no Docker required. HF reads the
frontmatter above, installs `requirements.txt`, and runs `app.py` automatically.

This block of `---` frontmatter is the **Space card**: it is how HF knows the SDK
(`gradio`), the version, and which file to launch. See
https://huggingface.co/docs/hub/spaces-config-reference

## Add your model key on the Space

After creating the Space, go to **Settings → Variables and secrets** and add a
secret named `GOOGLE_API_KEY` (the value from `../../../module3_agents/.env`). The
`deploy_hf` script in the parent folder can also push files for you.

## Files

- `app.py` — Greet tab (zero-setup hello world) + Ask AI tab (Gemini-backed).
- `requirements.txt` — `gradio`, `google-genai`.
