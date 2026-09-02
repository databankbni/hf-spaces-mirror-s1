---
title: SymSTS MiniLM — Sentence Similarity (In-Browser)
emoji: 🔬
colorFrom: blue
colorTo: purple
sdk: static
pinned: false
license: apache-2.0
---

# SymSTS-MiniLM · Sentence Similarity — running 100% in your browser

A free **static Space** that runs **[blueprint-ai/SymSTS-MiniLM](https://huggingface.co/blueprint-ai/SymSTS-MiniLM)** entirely client-side via **ONNX Runtime Web (WASM)** + the model exported to **fp16 ONNX** and mean-pooled exactly like the original sentence-transformers pipeline.

- **No server, no GPU, no PRO tier** — inference happens on your own CPU in the browser.
- **Private** — your text never leaves the device.
- Scores are **numerically verified** against the PyTorch model (identical to <0.01).

Files:
- `model.onnx` — SymSTS-MiniLM exported to fp16 ONNX (45 MB)
- `vocab.txt` — BERT WordPiece vocab
- `mybert.js` — minimal BERT tokenizer + mean-pool (validated byte-exact against `transformers`)
- `index.html` / `app.js` — UI + onnxruntime-web wiring
