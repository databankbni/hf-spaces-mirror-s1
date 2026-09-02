#!/usr/bin/env python3
"""Measure "longer card side / shorter image side" across an image dir.

This metric approximates how large the reference card is in the frame: a
low value means the camera was held far from the table (small card, thin
edges, poorer calibration fit); a high value means close framing. Used to
recommend a minimum framing ratio before the web demo accepts an upload.

Runs the same SAM hand + SAM card pipeline as the web demo. Prints per-image
values and a distribution summary (n, min, p10/25/50/75/90, max, mean, std,
a coarse histogram, and success/failure counts).

Usage:
    source .venv/bin/activate
    python3 script/card_to_image_ratio.py input/calibration_dataset/jpg
    python3 script/card_to_image_ratio.py input/kol_success
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

from src.finger_segmentation import segment_hand  # noqa: E402
from src.sam_card_detection import (  # noqa: E402
    detect_credit_card_sam_prompt,
    suggest_card_seeds,
)

IMG_EXTS = {".jpg", ".jpeg", ".png"}


def _process_image(path: Path) -> Tuple[Optional[float], str]:
    """Return (ratio_or_None, status_tag) for a single image."""
    img = cv2.imread(str(path))
    if img is None:
        return None, "load_failed"

    try:
        hand_data = segment_hand(img)
    except Exception as e:
        return None, f"hand_error:{type(e).__name__}"
    if hand_data is None:
        return None, "hand_not_detected"

    canonical = hand_data.get("canonical_image", img)
    hand_mask = hand_data.get("mask")
    landmarks = hand_data.get("landmarks")
    if hand_mask is None or landmarks is None or len(landmarks) <= 9:
        return None, "no_landmarks"

    y_limit = int(round(landmarks[9, 1]))
    seed_info = suggest_card_seeds(hand_mask, canonical.shape[:2], y_limit)
    seeds = seed_info["kept"]
    if not seeds:
        return None, "no_seeds"

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
        return None, f"card_error:{type(e).__name__}"
    if card is None:
        return None, "card_not_detected"

    longer = max(float(card["width_px"]), float(card["height_px"]))
    shorter_image = float(min(canonical.shape[0], canonical.shape[1]))
    return longer / shorter_image, "ok"


def _describe(values: List[float], label: str) -> None:
    if not values:
        print(f"\n{label}: no successful measurements.")
        return

    values_sorted = sorted(values)
    n = len(values_sorted)

    def pct(p: float) -> float:
        if n == 1:
            return values_sorted[0]
        k = (n - 1) * p
        lo = int(k)
        hi = min(lo + 1, n - 1)
        frac = k - lo
        return values_sorted[lo] * (1 - frac) + values_sorted[hi] * frac

    print(f"\n=== {label} (n={n}) ===")
    print(f"  min    = {min(values_sorted):.3f}")
    print(f"  p10    = {pct(0.10):.3f}")
    print(f"  p25    = {pct(0.25):.3f}")
    print(f"  median = {pct(0.50):.3f}")
    print(f"  p75    = {pct(0.75):.3f}")
    print(f"  p90    = {pct(0.90):.3f}")
    print(f"  max    = {max(values_sorted):.3f}")
    print(f"  mean   = {stats.mean(values_sorted):.3f}")
    if n > 1:
        print(f"  std    = {stats.stdev(values_sorted):.3f}")

    # Coarse histogram, 0.05-wide bins across the realistic range.
    lo_edge = 0.10
    hi_edge = max(0.65, max(values_sorted) + 0.05)
    bin_w = 0.05
    edges = []
    e = lo_edge
    while e <= hi_edge + 1e-9:
        edges.append(round(e, 2))
        e += bin_w
    counts = [0] * (len(edges) - 1)
    under = over = 0
    for v in values_sorted:
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
        print(f"    <{edges[0]:.2f}         : {under}")
    for i, c in enumerate(counts):
        if c == 0:
            continue
        bar = "#" * c
        print(f"    [{edges[i]:.2f},{edges[i+1]:.2f}) : {c:2d}  {bar}")
    if over:
        print(f"    >={edges[-1]:.2f}        : {over}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image_dir", type=Path)
    ap.add_argument("--limit", type=int, default=None,
                    help="optional cap on number of images processed")
    args = ap.parse_args()

    logging.getLogger().setLevel(logging.ERROR)  # silence pipeline chatter

    if not args.image_dir.is_dir():
        print(f"Not a directory: {args.image_dir}")
        return 1

    images = sorted(
        p for p in args.image_dir.iterdir()
        if p.suffix.lower() in IMG_EXTS
    )
    if args.limit:
        images = images[: args.limit]
    if not images:
        print(f"No images found in {args.image_dir}")
        return 1

    print(f"Processing {len(images)} images from {args.image_dir}")
    print(f"{'#':>3}  {'file':<60} {'ratio':>6}  status")

    ratios: List[float] = []
    status_counts = {}
    t_start = time.time()
    for i, path in enumerate(images, 1):
        t0 = time.time()
        ratio, status = _process_image(path)
        dt = time.time() - t0
        status_counts[status] = status_counts.get(status, 0) + 1
        ratio_str = f"{ratio:.3f}" if ratio is not None else "  -  "
        print(f"{i:>3}  {path.name:<60} {ratio_str:>6}  {status}  ({dt:.1f}s)")
        if ratio is not None:
            ratios.append(ratio)

    total_dt = time.time() - t_start
    print(f"\nElapsed: {total_dt:.1f}s ({total_dt / max(1, len(images)):.1f}s/img)")
    print(f"Status summary: {status_counts}")
    _describe(ratios, label=f"ratio = longer_card_px / shorter_image_px  ({args.image_dir})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
