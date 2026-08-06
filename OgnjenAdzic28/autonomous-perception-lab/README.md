---
title: Autonomous Perception Lab
emoji: 🚗
colorFrom: blue
colorTo: green
sdk: gradio
sdk_version: 5.49.1
app_file: app.py
pinned: false
license: mit
---

# Autonomous Perception Lab

Visual demo for the real KITTI learned-detector run, plus a short-video upload
path for live YOLO inference.

The main demo serves generated artifacts from the local pipeline:

- real KITTI tracking frames
- COCO-pretrained Ultralytics YOLO detections
- projected KITTI Velodyne sparse depth
- multi-object tracking
- approximate bird's-eye-view projection
- replay videos and benchmark metrics

The upload tab runs `yolo11n.pt` on a user-supplied short video and returns an
annotated MP4 plus a detection summary. The upload path is CPU-limited and does
not run calibrated KITTI depth projection or multi-object tracking.
