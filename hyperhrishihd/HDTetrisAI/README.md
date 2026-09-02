---
title: HDTetris
emoji: 🎮
colorFrom: blue
colorTo: purple
sdk: docker
pinned: false
---

# 🎮 HDTetris

An advanced, real-time autonomous **Tetris AI** powered by **PyTorch Deep Q-Networks (DQN)** and a selective **depth-5 expectiminimax search**, running live on Hugging Face Spaces.

[![Hugging Face Spaces](https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-Spaces-blue)](https://huggingface.co/spaces/hyperhrishihd/HDTetrisAI)
[![GitHub Repository](https://img.shields.io/badge/GitHub-HDTetrisAI-green)](https://github.com/HyperHrishi-HD/HDTetrisAI)

---

## 🔥 Key Features

* **🧠 Deep Q-Learning Neural Network (PyTorch)**: Learns optimal Tetris piece placement strategies through deep reinforcement learning, prioritized experience replay, and target-network iterations.
* **🔮 Selective Depth-5 Expectiminimax**: Searches legal bitboard placements, known next-piece max nodes, and 7-bag chance nodes with transposition caching and column-pruned beams.
* **☁️ Durable 24/7 Persistence**: Streams stable per-episode records to Hugging Face, merge-syncs the complete SQLite archive, and mirrors compressed checkpoints to GitHub without losing history across Space restarts.
* **🛡️ Health Watchdog & Recovery**: Detects training errors, stalled heartbeats, and shrinking history, then restores the latest validated Hugging Face health checkpoint atomically.
* **📊 Strategy Benchmark Gate**: Compares CHAMPION, SURVIVAL, TETRIS_SETUP, FLAT_STACK, and WELL_BUILDER over identical 10,000-seed 7-bag streams before promotion.
* **⚡ SSE Real-Time Live Streaming**: Server-Sent Events (`/stream`) deliver low-overhead live game updates to the browser canvas.
* **🎨 Cyberpunk Neon UI & Web Audio Synth**: Neon block rendering, line-clear particles at the actual cleared rows, audio effects, and screen shake in both simulation and human play.
* **⏩ Compressed Replay Engine**: High-score replay theater starts at human-paced 1x and supports 2x/5x/10x/20x playback controls.

---

## 🛠️ Architecture & Tech Stack

* **Backend**: Python 3.11, Flask, Gunicorn, PyTorch (CPU)
* **Storage**: SQLite (`ai_evolution.db`), Hugging Face Hub checkpoints, compressed GitHub mirror
* **Frontend**: HTML5 Canvas, Web Audio API, Chart.js, SSE EventSource
* **Container**: Docker SDK on Hugging Face Spaces

---

## 🚀 Running Locally

```bash
# Install dependencies
pip install flask gunicorn requests torch

# Run local development server
python app.py

# Run the training-free strategy gate
python benchmark.py --seeds 10000 --max-moves 80 --workers 5
```

The benchmark dashboard is available at `/benchmark` while the app is running. Check out the Hugging Face configuration reference at [Hugging Face Spaces Docs](https://huggingface.co/docs/hub/spaces-config-reference).
