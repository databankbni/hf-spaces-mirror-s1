---
title: Ring Sizer
emoji: "\U0001F48D"
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
---

# Ring Sizer

Local computer-vision CLI tool that measures **finger outer diameter** from a single image using a **credit card** as scale reference. Achieves **±0.5 mm** diameter accuracy and **0% return rate** on a 10-subject evaluation (N=20 images).

## Live Demo
- Hugging Face Space: [https://huggingface.co/spaces/feng-x/ring-sizer](https://huggingface.co/spaces/feng-x/ring-sizer)
- Anyone can try the hosted web demo directly in the browser.
![Ring Size CV Web Demo Screenshot](doc/assets/ring-size-cv-demo.jpg)

## What it does
- Detects a credit card and computes `px/cm` scale (classical by default; SAM 2.1 prompt-based in the web demo).
- Segments the hand with SAM 2.1 (palm-center prompt) + MediaPipe landmarks.
- Measures finger width in the ring-wearing zone. Two modes:
  - `mask` (default) — width read directly from the SAM mask boundary.
  - `sobel` — bidirectional Sobel + subpixel parabola refinement, anchored on the SAM boundary.
- **Regression calibration** corrects systematic over-measurement (MAE: 0.158 → 0.060 cm).
- **Ring size recommendation** maps calibrated diameter to sizes 6–13 (best match + 2-size range). Supports multiple ring models: **Gen1/Gen2** and **Air**, each with its own size chart.
- **Multi-finger mode** measures index, middle, and ring fingers in one pass; consensus aggregation maximizes the chance at least one finger fits.
- **Optional AI explanation** (OpenAI) generates a human-readable rationale for the recommendation (size selection is always deterministic).
- **In-browser capture coach** (v5) opens the camera in-page and gates the shutter on live distance / level / brightness checks, eliminating bad-photo round trips.
- **Mobile-native flow** (v6) at `/m` paginates the demo into six steps (intro → form → guide → capture → confirm → result); `/` auto-routes mobile UAs there.
- **Post-result feedback** — successful runs get a 5-star rating + optional comment panel; data is attached to the measurement row and surfaced on the `/admin` dashboard (avg rating, rating distribution, per-row Rating and Comment columns).
- Writes JSON output and always writes a result PNG next to it.

## Accuracy

Validated on 10 subjects × 3 fingers × 2 photos = 60 measurements against caliper ground truth.

| Metric | Before Calibration | After Calibration |
|--------|-------------------|-------------------|
| MAE | 0.158 cm | **0.060 cm** |
| RMSE | 0.176 cm | **0.075 cm** |
| Max error | 0.347 cm | **0.174 cm** |

Pipeline stability: card detection CV = 0.44%, shot-to-shot repeatability = 0.028 cm.

### Ring Size Recommendation

Evaluated on 10 subjects × 2 photos = 20 images in multi-finger mode.

| Metric | Value |
|--------|-------|
| Return rate (fits no finger) | **0%** (0/20) |
| Exact size match | 55% (11/20) |
| Within ±1 size | 100% (20/20) |
| A/B photo consistency | 90% (9/10 same size) |

See full analysis: [`doc/algorithms/08-ring-size-recommendation.md`](doc/algorithms/08-ring-size-recommendation.md)

See calibration report: [`doc/report/calibration_report.md`](doc/report/calibration_report.md)

## Install
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run
```bash
# Single finger (default)
python measure_finger.py --input input/test_image.jpg --output output/result.json

# Multi-finger (recommended) — measures index, middle, ring in one pass
python measure_finger.py --input input/test_image.jpg --output output/result.json --mode multi

# Specify ring model (gen or air)
python measure_finger.py --input input/test_image.jpg --output output/result.json --mode multi --ring-model air
```

### Common options
```bash
# Save intermediate debug images next to the result PNG
python measure_finger.py --input image.jpg --output output/result.json --debug

# Pick a different finger
python measure_finger.py --input image.jpg --output output/result.json --finger-index ring

# Raw (uncalibrated) measurement only
python measure_finger.py --input image.jpg --output output/result.json --no-calibration

# SAM card detection (first run downloads ~150 MB of weights)
python measure_finger.py --input image.jpg --output output/result.json --card-method sam

# Subpixel Sobel gradient anchored on the SAM boundary
python measure_finger.py --input image.jpg --output output/result.json \
  --card-method sam --edge-method sobel --sobel-threshold 15 --sobel-kernel-size 3
```

## CLI flags
| Flag | Values | Default | Description |
|------|--------|---------|-------------|
| `--input` | path | *(required)* | Input image (JPG/PNG) |
| `--output` | path | *(required)* | Output JSON path |
| `--debug` | flag | false | Save intermediate debug images |
| `--finger-index` | auto, index, middle, ring, pinky | index | Which finger to measure (single mode) |
| `--mode` | single, multi | single | Single finger or all 3 fingers |
| `--ring-model` | gen, air | gen | Ring size chart |
| `--confidence-threshold` | float | 0.7 | Minimum acceptable confidence |
| `--edge-method` | mask, sobel | mask | `mask` = SAM boundary; `sobel` = subpixel gradient anchored on it |
| `--card-method` | classic, sam | classic | Card detector; CLI default is classical to avoid surprise 150 MB download |
| `--sobel-threshold` | float | 15.0 | Minimum gradient magnitude (sobel mode) |
| `--sobel-kernel-size` | 3, 5, 7 | 3 | Sobel kernel (sobel mode) |
| `--no-subpixel` | flag | false | Disable parabola refinement (sobel mode) |
| `--no-calibration` | flag | false | Output raw measurement only |
| `--skip-card-detection` | flag | false | Testing only |

## Output JSON
```json
{
  "finger_outer_diameter_cm": 1.78,
  "confidence": 0.91,
  "scale_px_per_cm": 128.03,
  "quality_flags": {
    "card_detected": true,
    "finger_detected": true,
    "view_angle_ok": true
  },
  "fail_reason": null,
  "edge_method_used": "mask",
  "raw_diameter_cm": 1.92,
  "calibration_applied": true,
  "ring_size": {
    "best_match": 8,
    "best_match_inner_mm": 18.6,
    "range_min": 8,
    "range_max": 9,
    "diameter_mm": 17.80,
    "ring_model": "gen"
  }
}
```

Notes:
- `raw_diameter_cm` is the pre-calibration measurement (present when calibration is applied).
- `ring_size` maps calibrated diameter to sizes 6–13 for the selected ring model. `ring_model` indicates which chart was used (`gen` or `air`).
- `edge_method_used` is `mask` or `sobel` depending on `--edge-method`.
- Result image path is auto-derived: `output/result.json` → `output/result.png`.

## Documentation
| Path | Contents |
|------|----------|
| [`doc/v0/`](doc/v0/) | v0 PRD, Plan, Progress (contour baseline; superseded) |
| [`doc/v1/`](doc/v1/) | v1 PRD, Plan, Progress (Sobel edge refinement; `auto`/`compare` modes later removed) |
| [`doc/v2/`](doc/v2/) | v2 Plan, Progress (calibration & regression) |
| [`doc/v3/`](doc/v3/) | v3 Progress (multi-finger, quality checks, AI explanation) |
| [`doc/v4/`](doc/v4/) | v4 PRD, Plan, Progress (SAM 2.1 card + hand segmentation) |
| [`doc/v5/`](doc/v5/) | v5 PRD, Plan, Progress (in-browser capture coach: live distance/level/brightness gates) |
| [`doc/v6/`](doc/v6/) | v6 PRD, Plan, Progress (mobile-native paginated flow at `/m` — **current surface**) |
| [`doc/report/`](doc/report/) | Validation, calibration & ring size mapping reports |
| [`doc/algorithms/`](doc/algorithms/) | Algorithm documentation |
| [`script/`](script/) | Batch measurement & analysis scripts |
| [`web_demo/`](web_demo/) | Web demo (Flask) |
