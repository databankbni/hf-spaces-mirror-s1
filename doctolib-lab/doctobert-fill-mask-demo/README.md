---
title: DoctoBERT Fill-Mask
emoji: 🩺
colorFrom: indigo
colorTo: purple
sdk: gradio
sdk_version: 6.19.0
app_file: app.py
short_description: Fill-mask demo for a French medical ModernBERT
python_version: "3.12"
startup_duration_timeout: 30m
---

# 🩺 DoctoBERT Fill-Mask

Fill-mask demo of [doctolib-lab/doctomodernbert-fr-base](https://huggingface.co/doctolib-lab/doctomodernbert-fr-base),
a French medical **ModernBERT** encoder. Write a sentence containing a `[MASK]` token and the
model predicts the most likely words, ranked by probability.

Runs on **ZeroGPU** when deployed (via `@spaces.GPU`); falls back to MPS/CPU when run locally.

## Run locally

```bash
uv venv --python 3.12 .venv
uv pip install torch transformers gradio
python app.py
```
