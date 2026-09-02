---
title: EdgeFirst Model Zoo
emoji: 🔬
colorFrom: indigo
colorTo: red
sdk: static
pinned: true
license: cc-by-nc-4.0
short_description: Multi-platform model zoo validated on real edge hardware
thumbnail: https://huggingface.co/spaces/EdgeFirst/Models/resolve/main/social-card.png
---

# EdgeFirst Model Zoo

This Space hosts the [EdgeFirst Model Zoo](https://huggingface.co/spaces/EdgeFirst/Models) landing page. The visual interface is rendered from `index.html`.

New here? Start with **[Introducing the EdgeFirst Model Zoo](https://huggingface.co/blog/EdgeFirst/model-zoo-intro)** — what is in the zoo, why every figure links to its validation session, and how to reproduce any of it on your own hardware.

Want a platform, model or task we don't cover yet? [Vote on what we measure next](https://github.com/orgs/EdgeFirstAI/discussions/categories/polls) — three polls, one click each.

Each model family lives in its own Hugging Face repo containing all size variants (nano through x-large) and platform-specific compiled formats. Models are trained and validated on [EdgeFirst Studio](https://edgefirst.studio), then published here.

---

## Model repositories

### Detection

| Repo | Model | Sizes | Nano mAP@0.5 |
|------|-------|-------|-------------|
| [EdgeFirst/yolo26-det](https://huggingface.co/EdgeFirst/yolo26-det) | YOLO26 | n/s/m | 55.0% |
| [EdgeFirst/yolo11-det](https://huggingface.co/EdgeFirst/yolo11-det) | YOLO11 | n/s/m | 53.1% |
| [EdgeFirst/yolov8-det](https://huggingface.co/EdgeFirst/yolov8-det) | YOLOv8 | n/s/m | 50.5% |
| [EdgeFirst/yolov5-det](https://huggingface.co/EdgeFirst/yolov5-det) | YOLOv5 | n/s/m | 47.8% |

### Segmentation

| Repo | Model | Sizes | Nano Mask mAP |
|------|-------|-------|--------------|
| [EdgeFirst/yolo26-seg](https://huggingface.co/EdgeFirst/yolo26-seg) | YOLO26 | n/s/m | 32.7% |
| [EdgeFirst/yolo11-seg](https://huggingface.co/EdgeFirst/yolo11-seg) | YOLO11 | n/s | 30.2% |
| [EdgeFirst/yolov8-seg](https://huggingface.co/EdgeFirst/yolov8-seg) | YOLOv8 | n/s/m | 28.7% |

---

## Repo structure

Each model repo follows a consistent layout with platform folders:

```text
EdgeFirst/yolov8-det/
├── README.md                                # Model card
├── onnx/
│   ├── yolov8n-det-fp32.onnx
│   └── ...
├── tflite/
│   ├── yolov8n-det-int8.tflite              # Default (logical split-decoder)
│   ├── yolov8n-det-int8-smart.tflite        # Smart variant
│   └── ...
├── imx95/
│   ├── yolov8n-det-int8.imx95.tflite
│   └── ...
├── hailo/
│   ├── yolov8n-det-int8.hailo8l.hef
│   └── ...
└── jetson/
    ├── yolov8n-det-fp16.orin-nano.engine
    └── ...
```

## Naming convention

**Pattern**: `{version}{size}-{task}-{precision}[-{variant}][.{platform}].{ext}`

| Component | Description | Examples |
|-----------|-------------|---------|
| `{version}{size}` | Model family + variant | `yolov8n`, `yolo11s`, `dfine-n` |
| `-{task}` | Task suffix | `-det`, `-seg`, `-semseg`, `-depth` |
| `-{precision}` | Weight precision | `-fp32`, `-fp16`, `-int8` |
| `-{variant}` | Decoder variant (optional) | `-smart` |
| `.{platform}` | Deployment target (optional) | `.imx95`, `.ara240`, `.hailo8l`, `.orin-nano` |
| `.{ext}` | File format | `.onnx`, `.tflite`, `.dvm`, `.hef`, `.engine` |

**Decoder variants**: No suffix = default for that format (logical split-decoder for INT8, combined for ONNX/float). `-smart` = multi-scale split-decoder offering better accuracy at higher compute cost.

**Examples:**

| Description | Filename |
|-------------|----------|
| ONNX FP32 (reference) | `yolov8n-det-fp32.onnx` |
| Generic INT8 TFLite | `yolov8n-det-int8.tflite` |
| Smart variant TFLite | `yolov8n-det-int8-smart.tflite` |
| NXP i.MX 95 TFLite | `yolov8n-det-int8.imx95.tflite` |
| Smart NXP i.MX 95 | `yolov8n-seg-int8-smart.imx95.tflite` |
| Hailo-8L HEF | `yolov8n-det-int8.hailo8l.hef` |
| Jetson TensorRT FP16 | `yolov8n-det-fp16.orin-nano.engine` |

## Supported hardware

![x86_64 | Linux](https://img.shields.io/badge/x86__64-Linux-6C757D?style=flat-square) ![aarch64 | Linux](https://img.shields.io/badge/aarch64-Linux-718096?style=flat-square) ![Apple | macOS](https://img.shields.io/badge/Apple-macOS-4B0082?style=flat-square) ![NXP i.MX 8M Plus](https://img.shields.io/badge/NXP-i.MX_8M_Plus-E8B820?style=flat-square) ![NXP i.MX 95](https://img.shields.io/badge/NXP-i.MX_95-1FA0A8?style=flat-square) ![NXP Ara240](https://img.shields.io/badge/NXP-Ara240-5BB8F5?style=flat-square) ![RPi5 + Hailo-8L](https://img.shields.io/badge/RPi5-Hailo--8L-D9534F?style=flat-square) ![NVIDIA Jetson](https://img.shields.io/badge/NVIDIA-Jetson-2E8B57?style=flat-square)

- **Linux x86_64** — ONNX Runtime CUDA / CPU (FP32 reference)
- **Linux aarch64** — ONNX Runtime / TFLite (ARM64 generic Linux)
- **Apple macOS** — ONNX Runtime + CoreML ANE / GPU / CPU (FP16)
- **NXP i.MX 8M Plus** — 2.3 TOPS, TFLite INT8
- **NXP i.MX 95** — 2.0 TOPS, eIQ Neutron TFLite *(YOLOv5 and YOLOv8 published; YOLO11 and YOLO26 are in progress — they compile, load and run on the NPU while validation accuracy is resolved with NXP)*
- **NXP Ara240** — 40 eTOPS, .DVM
- **RPi5 + Hailo-8L** — 13 TOPS, HailoRT HEF
- **NVIDIA Jetson Orin** — 67–157 TOPS, TensorRT

## Validation pipeline

Every artifact in the Model Zoo is measured on the same dataset on the same hardware users deploy on. Accuracy numbers and per-stage timing are produced by the same pipeline that runs the deployed model — there is no "benchmark configuration" separate from production.

### End-to-end flow

Each training session produces a single set of weights in [EdgeFirst Studio](https://edgefirst.studio). The export pipeline emits ONNX FP32, INT8 TFLite, and platform-specific compiled formats (NXP i.MX 95 Neutron, NXP Ara240 .DVM, Hailo HEF, Jetson TensorRT). Every output is paired with an on-target validation that captures both accuracy (COCO mAP) and full-pipeline timing. The ONNX FP32 run from each training session is the reference baseline; quantization and runtime loss are measured relative to it.

### EdgeFirst Profiler

The on-target measurement engine. Given a model and a dataset it runs the full pipeline on the target device — capture, preprocess, inference, postprocess — and **computes the accuracy there too**: COCO detection and segmentation metrics, the deployment confusion breakdown, and every timing block are calculated in-process, on the same machine that ran the model. There is no Python and no `pycocotools` on the device. It writes `metrics.yaml`, per-image predictions in EdgeFirst Arrow/Parquet, and a Perfetto trace.

Each runtime loads through its native delegate — VX Delegate on NXP i.MX 8M Plus, eIQ Neutron on NXP i.MX 95, NXP Ara SDK on Ara240, HailoRT on RPi5 + Hailo, TensorRT on Jetson, QNN on Qualcomm Hexagon, CoreML on Apple — so the timing reflects deployed-application reality rather than a benchmark harness.

### EdgeFirst Studio

Where results are published, compared and browsed — not where they are computed. The profiler publishes its metrics, predictions, charts and trace to a `v-XXXX` validation session, and that session is what every figure in this Model Zoo cites. A run does not need Studio at all: point the profiler at a local model, a directory of images and a ground-truth file and it writes the same outputs to disk with nothing uploaded.

### EdgeFirst HAL

The [EdgeFirst Hardware Abstraction Layer](https://github.com/EdgeFirstAI/hal) provides hardware-accelerated primitives used at both validation and deployment time: letterbox resize, color-space conversion, normalization, layout conversion, YOLO/ModelPack post-decode, NMS. HAL automatically selects DMA-BUF, OpenGL ES, NXP G2D, or CPU paths depending on the platform. Apache 2.0; Rust + Python + C surfaces.

### Latency and pipelined throughput

Per-frame latency is **work-time** — the sum of that frame's own stage durations — not wall-clock from capture to result. In an offline batch the capture workers race ahead of the bottleneck, so a wall-clock sojourn balloons with queue backlog and overstates per-image cost.

Throughput is measured separately, from the rate at which finished results actually emerge. The Model Zoo headlines **realized FPS** (`realized_fps_scalar`), the measured steady-state rate, not the derived `1000 / (preprocess + inference + postprocess)`. The two disagree because the runtime overlaps stages across frames.

Example: YOLOv5 Nano on NXP i.MX 95 eIQ Neutron, INT8, smart decoder, on an NXP FRDM-IMX95 board — per-stage means of 12.8 + 12.9 + 18.0 ms sum to 43.7 ms, which divides out to roughly 23 FPS. Measured throughput is **55.2 FPS** ([`v-8ad`](https://edgefirst.studio/public/validation/v-8ad/details?mode=charts)), and the run is bound by postprocess rather than by the NPU.

---

Validation results &amp; card data: [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) · YOLO model weights: © Ultralytics Inc. (AGPL-3.0) · © 2026 [Au-Zone Technologies](https://www.au-zone.com)

<sub>NXP<sup>®</sup>, i.MX, eIQ<sup>®</sup>, Neutron, and Ara240 are trademarks or products of NXP Semiconductors. Hailo is a trademark of Hailo Technologies Ltd. Jetson is a trademark of NVIDIA Corporation. All other trademarks are the property of their respective owners.</sub>
