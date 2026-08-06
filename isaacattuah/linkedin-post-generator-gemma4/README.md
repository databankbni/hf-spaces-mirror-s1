---
title: LinkedIn Post Generator
emoji: ✍️
colorFrom: blue
colorTo: purple
sdk: gradio
sdk_version: 6.20.0
app_file: app.py
pinned: false
license: apache-2.0
---

# ✍️ LinkedIn Post Generator

Generate professional, engaging LinkedIn posts in seconds — powered by
**Gemma 4 26B A4B**, an Apache 2.0-licensed, open-weight mixture-of-experts
model from Google DeepMind.

Companion demo for the article
[*You Don't Always Need a Frontier Model. You Need One That Fits.*](https://medium.com/@isaacattuah/you-dont-always-need-a-frontier-model-you-need-one-that-fits-7e2b44836f17)
· Full code (including a fully local Ollama version):
[GitHub repo](https://github.com/isaacattuah/linkedin-post-generator-gemma4)

## What it does

Paste in a topic, pick a tone and length, and get a ready-to-post LinkedIn
post. Inference runs through Hugging Face Inference Providers — no GPU
attached to this Space.

## Features

- **4 tone options** — Professional, Conversational, Inspirational, Educational
- **3 length options** — Short (~150 words), Medium (~300 words), Long (~500 words)
- **Pre-built examples** to get started instantly
- **Prompt layer tuned for LinkedIn** — strong hooks, scannable formatting,
  call-to-action endings, no markdown (LinkedIn renders plain text)

## Model

**[`google/gemma-4-26B-A4B-it`](https://huggingface.co/google/gemma-4-26B-A4B-it)**
— 25.2B total parameters with only ~3.8B active per token, giving
large-model quality at small-model per-token compute.

Two implementation details worth knowing (both bit me in production):

- **Gemma 4 is a thinking model.** Providers spend its reasoning tokens from
  the same `max_tokens` budget, so the app budgets `2× word target + 1024`.
  Budget only for the post and the model can hit the cap mid-thought and
  return empty content.
- **`content` can be `None`** and some providers return reasoning inline in
  `<think>` tags — the app normalizes both before displaying.

To use a different provider-served model, change one line in `app.py`
(e.g. `MODEL_ID = "Qwen/Qwen2.5-7B-Instruct"`), and check the model page's
Inference Providers panel to confirm it's served.

## Tech stack

- [Gradio 6](https://gradio.app/) — UI framework
- [Hugging Face Inference Providers](https://huggingface.co/docs/inference-providers) — serverless inference
- Shared prompt layer in `prompts.py` — same file drives the local Ollama version

## How to run locally

```bash
pip install -r requirements.txt
export HF_TOKEN=your_token_here
python app.py
```

You'll need a Hugging Face access token with the Inference Providers
permission. For the fully offline version (Ollama + Gemma 4 E2B, no token
needed), see [app_local.py in the repo](https://github.com/isaacattuah/linkedin-post-generator-gemma4/blob/main/app_local.py).

## Author

Built by [isaacattuah](https://huggingface.co/isaacattuah)