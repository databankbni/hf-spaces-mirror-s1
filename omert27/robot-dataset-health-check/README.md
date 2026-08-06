---
title: Calibra — Dataset Integrity
emoji: 🤖
colorFrom: purple
colorTo: blue
sdk: gradio
sdk_version: "5.50.0"
app_file: app.py
pinned: false
license: other
short_description: Integrity, quality & coverage checks for robot datasets
tags:
  - robotics
  - dataset-quality
  - dataset-integrity
  - lerobot
  - imitation-learning
  - data-curation
---

# Calibra — Dataset Integrity

Before diversity, coreset selection, or any other quality question, robotics teams first need to know: **can I trust this dataset?**

Enter a [LeRobot](https://github.com/huggingface/lerobot) dataset ID (e.g. `lerobot/pusht`) and Calibra checks:

**Integrity, first**
- Timestamp consistency and sensor sync
- Episode completeness
- Duplicate frames
- Camera freeze
- Blur
- Jittery / jerky motion (jerk spikes, velocity discontinuities, smoothness)

**Then Quality & Coverage**
- 0–100 score with grade (A–F) and certification status
- Concrete findings — dropout, jerk, redundant episodes
- Keep-fraction recommendation for building a smaller training set
- Community percentile comparison against 30+ audited public datasets
- Downloadable CalibraReport JSON for CI pipelines

## Run locally

```bash
pip install calibra-robotics
calibra integrity hf://lerobot/pusht      # can I trust this dataset?
calibra audit lerobot/pusht               # quality + coverage scoring
```

## Community benchmark

See [calibra-robot-dataset-quality-benchmark](https://huggingface.co/datasets/omert27/calibra-robot-dataset-quality-benchmark)
for audits of 30+ public LeRobot datasets with a sortable leaderboard.

## About

Powered by [Calibra](https://github.com/omertt27/Calibra) — open-source dataset
observability for robot learning: integrity, quality, coverage, and coreset
optimization in one pipeline.
