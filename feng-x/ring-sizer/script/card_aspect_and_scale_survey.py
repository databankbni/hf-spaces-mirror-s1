#!/usr/bin/env python3
"""Measure detected card aspect ratio and scale_confidence across an image dir.

Two metrics are captured per image (both come from the SAM-detected card's
4 corner points after order_corners):

  aspect_ratio    = max(width_px, height_px) / min(width_px, height_px)
                    Compared to the true credit-card aspect 1.586.
  scale_confidence = 1 - |px_per_cm_w - px_per_cm_h| / max(...)
                    Consistency between the two independent scale estimates
                    you get from the W and H sides; falls below 1.0 whenever
                    the detected aspect deviates from 1.586 (perspective tilt,
                    SAM mask error on one edge, non-standard card).

Runs the same SAM hand + SAM card pipeline as the web demo. Prints per-image
values and distribution summaries (n, min, p05/10/25/50/75/90/95, max,
mean, std, coarse histograms, success/failure counts).

Usage:
    source .venv/bin/activate
    python3 script/card_aspect_and_scale_survey.py input/kol_success
"""
from __future__ import annotations

import argparse
import logging
import statistics as stats
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.card_detection import compute_scale_factor  # noqa: E402
from src.finger_segmentation import segment_hand  # noqa: E402
from src.sam_card_detection import (  # noqa: E402
    detect_credit_card_sam_prompt,
    suggest_card_seeds,
)

IMG_EXTS = {".jpg", ".jpeg", ".png"}
TRUE_ASPECT = 1.586  # ISO/IEC 7810 ID-1: 85.60 / 53.98


def _process_image(path: Path) -> Tuple[Optional[float], Optional[float], str]:
    """Return (aspect_ratio, scale_confidence, status) for a single image."""
    img = cv2.imread(str(path))
    if img is None:
        return None, None, "load_failed"

    try:
        hand_data = segment_hand(img)
    except Exception as e:
        return None, None, f"hand_error:{type(e).__name__}"
    if hand_data is None:
        return None, None, "hand_not_detected"

    canonical = hand_data.get("canonical_image", img)
    hand_mask = hand_data.get("mask")
    landmarks = hand_data.get("landmarks")
    if hand_mask is None or landmarks is None or len(landmarks) <= 9:
        return None, None, "no_landmarks"

    y_limit = int(round(landmarks[9, 1]))
    seed_info = suggest_card_seeds(hand_mask, canonical.shape[:2], y_limit)
    seeds = seed_info["kept"]
    if not seeds:
        return None, None, "no_seeds"

    palm_c = np.mean(landmarks[[0, 5, 9, 13, 17], :2], axis=0)
    negatives = [(int(round(palm_c[0])), int(round(palm_c[1])))]

    try:
        card = detect_credit_card_sam_prompt(
            canonical,
            seed_points=seeds,
            negative_points=negatives,
            hand_mask=hand_mask,
        )
    except Exception as e:
        return None, None, f"card_error:{type(e).__name__}"
    if card is None:
        return None, None, "card_not_detected"

    aspect = float(card["aspect_ratio"])
    _, scale_conf = compute_scale_factor(card["corners"])
    return aspect, float(scale_conf), "ok"


def _percentiles(values_sorted: List[float], p: float) -> float:
    n = len(values_sorted)
    if n == 1:
        return values_sorted[0]
    k = (n - 1) * p
    lo = int(k)
    hi = min(lo + 1, n - 1)
    frac = k - lo
    return values_sorted[lo] * (1 - frac) + values_sorted[hi] * frac


def _describe(values: List[float], label: str, *, fmt: str = "{:.3f}",
              hist_lo: float = 0.0, hist_hi: float = 1.0,
              hist_bin: float = 0.05) -> None:
    if not values:
        print(f"\n{label}: no successful measurements.")
        return
    vs = sorted(values)
    n = len(vs)
    print(f"\n=== {label} (n={n}) ===")
    for tag, p in [("min", 0.0), ("p05", 0.05), ("p10", 0.10), ("p25", 0.25),
                   ("median", 0.50), ("p75", 0.75), ("p90", 0.90), ("p95", 0.95),
                   ("max", 1.0)]:
        v = vs[0] if p == 0 else vs[-1] if p == 1 else _percentiles(vs, p)
        print(f"  {tag:6s} = " + fmt.format(v))
    print(f"  mean   = " + fmt.format(stats.mean(vs)))
    if n > 1:
        print(f"  std    = " + fmt.format(stats.stdev(vs)))

    # Coarse histogram
    edges = []
    e = hist_lo
    while e <= hist_hi + 1e-9:
        edges.append(round(e, 4))
        e += hist_bin
    counts = [0] * (len(edges) - 1)
    under = over = 0
    for v in vs:
        if v < edges[0]:
            under += 1
            continue
        placed = False
        for i in range(len(edges) - 1):
            if edges[i] <= v < edges[i + 1]:
                counts[i] += 1
                placed = True
                break
        if not placed:
            over += 1
    print("  histogram:")
    if under:
        print(f"    <{fmt.format(edges[0])}         : {under}")
    for i, c in enumerate(counts):
        if c == 0:
            continue
        bar = "#" * c
        print(f"    [{fmt.format(edges[i])},{fmt.format(edges[i+1])}) : {c:2d}  {bar}")
    if over:
        print(f"    >={fmt.format(edges[-1])}        : {over}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image_dir", type=Path)
    ap.add_argument("--limit", type=int, default=None,
                    help="optional cap on number of images processed")
    args = ap.parse_args()

    logging.getLogger().setLevel(logging.ERROR)

    if not args.image_dir.is_dir():
        print(f"Not a directory: {args.image_dir}")
        return 1

    images = sorted(
        p for p in args.image_dir.iterdir() if p.suffix.lower() in IMG_EXTS
    )
    if args.limit:
        images = images[: args.limit]
    if not images:
        print(f"No images found in {args.image_dir}")
        return 1

    print(f"Processing {len(images)} images from {args.image_dir}")
    print(f"{'#':>3}  {'file':<60} {'aspect':>7}  {'sc':>5}  status")

    aspects: List[float] = []
    confs: List[float] = []
    deltas: List[float] = []  # |aspect - 1.586| / 1.586
    status_counts = {}
    t_start = time.time()
    for i, path in enumerate(images, 1):
        t0 = time.time()
        aspect, sc, status = _process_image(path)
        dt = time.time() - t0
        status_counts[status] = status_counts.get(status, 0) + 1
        a_str = f"{aspect:.3f}" if aspect is not None else "  -  "
        c_str = f"{sc:.3f}" if sc is not None else "  -  "
        print(f"{i:>3}  {path.name:<60} {a_str:>7}  {c_str:>5}  {status}  ({dt:.1f}s)")
        if aspect is not None:
            aspects.append(aspect)
            deltas.append(abs(aspect - TRUE_ASPECT) / TRUE_ASPECT)
        if sc is not None:
            confs.append(sc)

    total_dt = time.time() - t_start
    print(f"\nElapsed: {total_dt:.1f}s ({total_dt / max(1, len(images)):.1f}s/img)")
    print(f"Status summary: {status_counts}")

    _describe(aspects, label="aspect_ratio (true = 1.586)",
              hist_lo=1.30, hist_hi=1.85, hist_bin=0.05)
    _describe(deltas, label="|aspect - 1.586| / 1.586  (current gate ≤ 0.150)",
              fmt="{:.4f}", hist_lo=0.0, hist_hi=0.20, hist_bin=0.02)
    _describe(confs, label="scale_confidence  (current gate > 0.90)",
              hist_lo=0.80, hist_hi=1.00, hist_bin=0.02)
    return 0


if __name__ == "__main__":
    sys.exit(main())
