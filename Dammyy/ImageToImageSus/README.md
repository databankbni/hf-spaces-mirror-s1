---
title: Instruction Image Editor (CPU)
emoji: 🖼️
colorFrom: indigo
colorTo: pink
sdk: gradio
sdk_version: 5.9.1
app_file: app.py
pinned: false
---

# Instruction Image Editor (CPU only)

Upload an image and describe an edit as a natural-language instruction
(e.g. "Change the clothes to professional"). Built on
[InstructPix2Pix](https://huggingface.co/timbrooks/instruct-pix2pix), which
runs entirely on CPU — no GPU hardware required.

## Deploying on Hugging Face Spaces
1. Create a new Space, SDK = **Gradio**, Hardware = **CPU basic** (free tier works).
2. Upload `app.py`, `requirements.txt`, and this `README.md`.
3. The Space will build automatically and download the model on first launch
   (~5GB, cached afterward).

## Notes
- CPU inference takes roughly 1–3 minutes per image depending on steps/size.
- Default settings (512px, 15 steps) are tuned for a reasonable speed/quality
  balance on free CPU tiers. Lower `steps` for faster (but rougher) results.