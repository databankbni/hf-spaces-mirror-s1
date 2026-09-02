#!/usr/bin/env python3
"""Evaluate ring size recommendation effectiveness against ground truth.

Measures return rate: probability that recommended size fits NO finger.
"""
import csv
import sys
import os
import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from measure_finger import measure_multi_finger
from src.ring_size import RING_SIZE_CHART

# --- Load ground truth ---
GT_CSV = ROOT / "input" / "sample" / "finger-size.csv"
IMG_DIR = ROOT / "input" / "sample" / "jpg"

# Name → subject_id mapping (from CSV)
NAME_TO_ID = {}
# subject_id → {finger: {"diameter_mm": float, "gt_size": int}}
GT = {}

FINGER_MAP = {"食指": "index", "中指": "middle", "无名指": "ring"}

with open(GT_CSV, encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    for row in reader:
        sid = row["subject_id"]
        name = row["姓名"]
        finger_cn = row["手指"]
        diameter_cm = float(row["直径（cm）"])
        gt_size_raw = row["指环尺寸"].strip()

        NAME_TO_ID[name] = sid

        if sid not in GT:
            GT[sid] = {}

        finger_en = FINGER_MAP.get(finger_cn)
        if not finger_en:
            continue

        gt_size = int(gt_size_raw) if gt_size_raw.isdigit() else None
        GT[sid][finger_en] = {
            "diameter_mm": diameter_cm * 10,
            "gt_size": gt_size,
        }

# --- Find images per subject ---
# Images named like: 黄漫玉A.jpg, 黄漫玉B.jpg
SUBJECT_IMAGES = {}  # sid → [path, ...]
for img_file in sorted(IMG_DIR.glob("*.jpg")):
    stem = img_file.stem  # e.g. "黄漫玉A"
    if stem == "空白":
        continue
    # Last char is A or B
    name_part = stem[:-1]
    variant = stem[-1]
    sid = NAME_TO_ID.get(name_part)
    if sid is None:
        print(f"  [skip] No ground truth for {name_part}")
        continue
    SUBJECT_IMAGES.setdefault(sid, []).append(img_file)

print(f"Ground truth: {len(GT)} subjects, Images: {len(SUBJECT_IMAGES)} subjects")
print()

# --- Ring size inner diameters ---
SIZE_TO_INNER = RING_SIZE_CHART  # {size: inner_diameter_mm}

# --- Run measurements ---
results = []  # list of dicts

for sid in sorted(GT.keys()):
    images = SUBJECT_IMAGES.get(sid, [])
    if not images:
        print(f"  [skip] {sid}: no images found")
        continue

    gt_fingers = GT[sid]
    gt_sizes = {fn: info["gt_size"] for fn, info in gt_fingers.items() if info["gt_size"] is not None}
    gt_diameters = {fn: info["diameter_mm"] for fn, info in gt_fingers.items()}

    for img_path in images:
        variant = img_path.stem[-1]
        label = f"{sid}-{variant}"
        print(f"Processing {label} ({img_path.name})...", end=" ", flush=True)

        image = cv2.imread(str(img_path))
        if image is None:
            print("FAILED to load")
            continue

        try:
            result = measure_multi_finger(
                image=image,
                edge_method="sobel",
                save_debug=False,
                no_calibration=False,
            )
        except Exception as e:
            print(f"ERROR: {e}")
            continue

        rec_size = result.get("overall_best_size")
        rec_min = result.get("overall_range_min")
        rec_max = result.get("overall_range_max")
        fail = result.get("fail_reason")
        per_finger = result.get("per_finger", {})

        # Per-finger measured diameters
        measured = {}
        for fn in ("index", "middle", "ring"):
            pf = per_finger.get(fn, {})
            if pf.get("status") == "ok" and pf.get("diameter_cm") is not None:
                measured[fn] = pf["diameter_cm"] * 10  # mm
                per_size = pf.get("best_match")
                measured[f"{fn}_size"] = per_size

        if fail or rec_size is None:
            print(f"FAIL ({fail})")
            results.append({
                "label": label, "sid": sid, "variant": variant,
                "rec_size": None, "fail": fail,
                "gt_sizes": gt_sizes, "gt_diameters": gt_diameters,
                "measured": measured,
                "fits_any": False, "return": True,
            })
            continue

        # Check if recommended size fits at least one finger
        rec_inner = SIZE_TO_INNER.get(rec_size, 0)

        fits_any = False
        fit_details = {}
        for fn, gt_sz in gt_sizes.items():
            gt_inner = SIZE_TO_INNER.get(gt_sz, 0)
            gt_diam = gt_diameters.get(fn, 0)

            # "Fits" = ring can go on (rec inner >= finger diameter)
            # AND not absurdly loose (rec size <= gt_size + 2)
            can_go_on = rec_inner >= gt_diam
            not_too_loose = rec_size <= gt_sz + 2
            fits = can_go_on and not_too_loose

            fit_details[fn] = {
                "gt_size": gt_sz,
                "gt_diam_mm": gt_diam,
                "rec_inner_mm": rec_inner,
                "can_go_on": can_go_on,
                "not_too_loose": not_too_loose,
                "fits": fits,
            }
            if fits:
                fits_any = True

        status = "OK" if fits_any else "RETURN"
        print(f"rec={rec_size} ({rec_min}-{rec_max}) → {status}")
        for fn, fd in fit_details.items():
            tag = "✓" if fd["fits"] else "✗"
            print(f"    {fn}: gt_size={fd['gt_size']} gt_diam={fd['gt_diam_mm']:.1f}mm "
                  f"rec_inner={fd['rec_inner_mm']:.1f}mm [{tag}]")

        results.append({
            "label": label, "sid": sid, "variant": variant,
            "rec_size": rec_size, "rec_min": rec_min, "rec_max": rec_max,
            "fail": None,
            "gt_sizes": gt_sizes, "gt_diameters": gt_diameters,
            "measured": measured, "fit_details": fit_details,
            "fits_any": fits_any, "return": not fits_any,
        })

# --- Summary ---
print("\n" + "=" * 70)
print("EVALUATION SUMMARY")
print("=" * 70)

total = len(results)
failed = sum(1 for r in results if r["fail"])
succeeded = total - failed
returns = sum(1 for r in results if r["return"] and not r["fail"])
fits = sum(1 for r in results if r["fits_any"])

print(f"\nTotal images:     {total}")
print(f"Measurement OK:   {succeeded}")
print(f"Measurement FAIL: {failed}")
print()
print(f"Of {succeeded} successful measurements:")
print(f"  Fits ≥1 finger: {fits}  ({fits/succeeded*100:.1f}%)" if succeeded else "")
print(f"  Would RETURN:   {returns}  ({returns/succeeded*100:.1f}%)" if succeeded else "")
print()

# Detailed table
print(f"{'Label':<10} {'Rec':>4} {'Range':>7} {'GT(I)':>6} {'GT(M)':>6} {'GT(R)':>6} {'Result':<8}")
print("-" * 55)
for r in results:
    if r["fail"]:
        print(f"{r['label']:<10} {'FAIL':>4} {'':>7} "
              f"{r['gt_sizes'].get('index',''):>6} "
              f"{r['gt_sizes'].get('middle',''):>6} "
              f"{r['gt_sizes'].get('ring',''):>6} "
              f"{'FAIL':<8}")
        continue
    gt = r["gt_sizes"]
    rng = f"{r['rec_min']}-{r['rec_max']}"
    status = "OK" if r["fits_any"] else "RETURN"
    print(f"{r['label']:<10} {r['rec_size']:>4} {rng:>7} "
          f"{gt.get('index',''):>6} {gt.get('middle',''):>6} {gt.get('ring',''):>6} "
          f"{status:<8}")

# Per-subject analysis (best of A/B)
print("\n\nPER-SUBJECT (best of A/B photos):")
print(f"{'Subject':<8} {'A_rec':>5} {'A_fit':>5} {'B_rec':>5} {'B_fit':>5} {'Best':>5} {'Result':<8}")
print("-" * 52)
for sid in sorted(GT.keys()):
    subj_results = [r for r in results if r["sid"] == sid]
    a_results = [r for r in subj_results if r["variant"] == "A"]
    b_results = [r for r in subj_results if r["variant"] == "B"]

    def fmt(rlist):
        if not rlist:
            return ("—", "—")
        r = rlist[0]
        if r["fail"]:
            return ("FAIL", "—")
        return (str(r["rec_size"]), "✓" if r["fits_any"] else "✗")

    a_rec, a_fit = fmt(a_results)
    b_rec, b_fit = fmt(b_results)
    best = "OK" if any(r["fits_any"] for r in subj_results) else "RETURN"
    print(f"{sid:<8} {a_rec:>5} {a_fit:>5} {b_rec:>5} {b_fit:>5} {'':>5} {best:<8}")

subj_with_any_ok = sum(
    1 for sid in GT
    if any(r["fits_any"] for r in results if r["sid"] == sid)
)
subj_total = len([sid for sid in GT if any(r["sid"] == sid for r in results)])
print(f"\nSubjects with ≥1 fitting result: {subj_with_any_ok}/{subj_total}")
print(f"Effective return rate (per-subject): {(1 - subj_with_any_ok/subj_total)*100:.1f}%" if subj_total else "N/A")

# Size error analysis
print("\n\nSIZE ERROR ANALYSIS (recommended vs closest GT size):")
errors = []
for r in results:
    if r["fail"] or r["rec_size"] is None:
        continue
    gt = r["gt_sizes"]
    gt_vals = [v for v in gt.values() if v is not None]
    if not gt_vals:
        continue
    # Error = rec - closest GT
    closest_gt = min(gt_vals, key=lambda s: abs(s - r["rec_size"]))
    err = r["rec_size"] - closest_gt
    errors.append(err)
    
if errors:
    import statistics
    print(f"  Mean error: {statistics.mean(errors):+.2f} sizes")
    print(f"  Median error: {statistics.median(errors):+.1f} sizes")
    print(f"  Std dev: {statistics.stdev(errors):.2f} sizes")
    print(f"  Range: [{min(errors):+d}, {max(errors):+d}]")
    
    # Distribution
    from collections import Counter
    dist = Counter(errors)
    print(f"\n  Error distribution:")
    for e in sorted(dist.keys()):
        bar = "█" * dist[e]
        print(f"    {e:+d}: {bar} ({dist[e]})")
