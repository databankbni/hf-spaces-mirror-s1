---
title: MiniMax H3 Demo
emoji: 🎬
colorFrom: purple
colorTo: indigo
sdk: static
pinned: false
---

# MiniMax H3 Demo

An interactive **static** demo for **[MiniMaxAI/MiniMax-H3](https://huggingface.co/MiniMaxAI/MiniMax-H3)** — a
general-purpose omni-modal system that generates **video with a synchronized stereo soundtrack** in a single
denoising pass.

> This Space is **static** (free). It showcases the official example outputs of the model rather than running the
> ~33B-parameter checkpoint itself, which requires paid GPU/ZeroGPU hardware.

## Workflows demonstrated

- **T2VA** — Text-to-Video + Audio (video and soundtrack from a prompt)
- **FL2VA** — First/Last-Frame-to-Video + Audio
- **I2VA** — Image-to-Video + Audio
- **Ref2VA** — Omni-reference-to-Video + Audio

## Try it live

Open the Space in the browser (it serves `index.html`). Videos are the official reproducible 768p outputs from the
model repo.

## What it would take to run the real model

- A **Gradio/Docker Space** (requires a paid **PRO** subscription — free accounts can no longer create those).
- **ZeroGPU / GPU hardware**, which consumes paid credits.
- The model is ~196 GB in bf16; it needs quantization (int8/NVFP4) plus CPU/group offload to fit on a single card.
