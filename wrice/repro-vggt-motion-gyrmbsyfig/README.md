---
title: VGGT-Motion Evidence
emoji: "🔎"
colorFrom: blue
colorTo: green
sdk: gradio
sdk_version: 5.44.0
app_file: app.py
tags:
  - icml2026-repro
  - paper-GyRMbsYFiG
---

# VGGT-Motion Evidence

CPU-only evidence for ICML 2026 paper `GyRMbsYFiG`, based on pinned arXiv
source `2602.05508v1`.

The bundle audits the released TeX source and runs deterministic toy checks of
the optical-flow motion classifier, turning-preserving submap partitioning, and
Sim(3) alignment. It does not claim KITTI, Waymo, 4Seasons, Complex Urban, A2D2,
or runtime results as reproduced measurements.

Run locally:

```bash
python generate_evidence.py --output evidence/bundle.json
pytest -q
```
