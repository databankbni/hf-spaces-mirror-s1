#!/usr/bin/env python3
"""Batch measurement script for calibration dataset.

Runs measure_finger.py with --no-calibration on all sample images × 3 fingers.
The --no-calibration flag is critical: without it, finger_outer_diameter_cm is
the already-calibrated value, and fitting a regression against it produces
meaningless near-identity coefficients that silently double-stack on the old
calibration. See doc/v2/Progress.md (2026-04-20 entry) for the incident.

As a defence in depth, the script also reads raw_diameter_cm if present and
uses that in preference to finger_outer_diameter_cm.
"""

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

# Finger name mapping (Chinese → CLI arg)
FINGER_MAP = {
    "食指": "index",
    "中指": "middle",
    "无名指": "ring",
}

# People to exclude (no ground truth)
EXCLUDE = {"谢峰", "空白"}


def run_measurement(image_path: str, finger: str, output_json: str) -> dict:
    """Run measure_finger.py and return parsed JSON result."""
    cmd = [
        sys.executable, "measure_finger.py",
        "--input", image_path,
        "--output", output_json,
        "--finger-index", finger,
        "--edge-method", "mask",
        "--no-calibration",
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120
        )
        if os.path.exists(output_json):
            with open(output_json) as f:
                return json.load(f)
        else:
            return {"fail_reason": f"no output file; stderr={proc.stderr[-200:]}"}
    except subprocess.TimeoutExpired:
        return {"fail_reason": "timeout"}
    except Exception as e:
        return {"fail_reason": str(e)}


def load_ground_truth(csv_path: str) -> list[dict]:
    """Load ground truth CSV."""
    rows = []
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def main():
    base_dir = Path(__file__).resolve().parent.parent
    os.chdir(base_dir)

    jpg_dir = base_dir / "input" / "sample-03-05" / "jpg"
    csv_path = base_dir / "input" / "sample-03-05" / "finger-size.csv"
    out_dir = base_dir / "output" / "batch"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load ground truth
    gt_rows = load_ground_truth(str(csv_path))
    print(f"Loaded {len(gt_rows)} ground truth rows")

    # Build name→rows lookup
    gt_by_name = {}
    for row in gt_rows:
        name = row["姓名"]
        if name not in gt_by_name:
            gt_by_name[name] = {}
        finger_cn = row["手指"]
        gt_by_name[name][finger_cn] = row

    # Find all person images (exclude 谢峰, 空白)
    images = sorted([
        f for f in jpg_dir.glob("*.jpg")
        if not any(ex in f.stem for ex in EXCLUDE)
    ])
    print(f"Found {len(images)} images to process")

    all_results = []
    total = len(images) * 3  # 3 fingers per image
    done = 0

    for img_path in images:
        stem = img_path.stem           # e.g. "S01A"
        person = stem[:-1]             # e.g. "S01"
        shot = stem[-1]                # e.g. "A"

        if person not in gt_by_name:
            print(f"  SKIP {stem}: no ground truth for {person}")
            continue

        for finger_cn, finger_en in FINGER_MAP.items():
            done += 1
            gt_row = gt_by_name[person].get(finger_cn)
            gt_diameter = float(gt_row["直径（cm）"]) if gt_row else None
            gt_circumference = float(gt_row["周长（cm）"]) if gt_row else None
            gt_ring_size = gt_row.get("指环尺寸", "") if gt_row else ""

            out_json = str(out_dir / f"{stem}_{finger_en}.json")
            print(f"[{done}/{total}] {stem} / {finger_cn} ({finger_en})...", end=" ", flush=True)

            result = run_measurement(str(img_path), finger_en, out_json)

            # Prefer raw_diameter_cm if present (when calibration was applied upstream);
            # fall back to finger_outer_diameter_cm (which, under --no-calibration, IS raw).
            # This makes the script robust to either invocation — the regression always
            # sees raw CV output, never double-calibrated values.
            raw_diameter = result.get("raw_diameter_cm")
            calibrated_diameter = result.get("finger_outer_diameter_cm")
            calibration_applied = result.get("calibration_applied", False)
            cv_diameter = raw_diameter if raw_diameter is not None else calibrated_diameter
            cv_confidence = result.get("confidence")
            cv_scale = result.get("scale_px_per_cm")
            fail = result.get("fail_reason")

            if cv_diameter and gt_diameter:
                error = cv_diameter - gt_diameter
                pct = error / gt_diameter * 100
                tag = " (raw)" if raw_diameter is not None else ""
                print(f"CV={cv_diameter:.3f}{tag} GT={gt_diameter:.3f} Δ={error:+.3f} ({pct:+.1f}%) scale={cv_scale}")
            elif fail:
                print(f"FAILED: {fail[:80]}")
            else:
                print(f"CV={cv_diameter} (no GT)")

            all_results.append({
                "person": person,
                "shot": shot,
                "finger_cn": finger_cn,
                "finger_en": finger_en,
                "image": img_path.name,
                "gt_diameter_cm": gt_diameter,
                "gt_circumference_cm": gt_circumference,
                "gt_ring_size": gt_ring_size,
                "cv_diameter_cm": cv_diameter,
                "cv_calibrated_cm": calibrated_diameter if calibration_applied else None,
                "calibration_applied_upstream": calibration_applied,
                "cv_confidence": cv_confidence,
                "cv_scale_px_per_cm": cv_scale,
                "fail_reason": fail,
                "edge_method": result.get("edge_method_used"),
            })

    # Save full results JSON
    results_json = str(out_dir / "batch_results.json")
    with open(results_json, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print(f"\nSaved {len(all_results)} results to {results_json}")

    # Save summary CSV
    results_csv = str(out_dir / "batch_results.csv")
    if all_results:
        keys = all_results[0].keys()
        with open(results_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(all_results)
        print(f"Saved CSV to {results_csv}")

    # Quick stats
    valid = [r for r in all_results if r["cv_diameter_cm"] and r["gt_diameter_cm"]]
    failed = [r for r in all_results if r["fail_reason"]]
    if valid:
        errors = [r["cv_diameter_cm"] - r["gt_diameter_cm"] for r in valid]
        mean_err = sum(errors) / len(errors)
        scales = [r["cv_scale_px_per_cm"] for r in valid if r["cv_scale_px_per_cm"]]
        mean_scale = sum(scales) / len(scales) if scales else 0
        print(f"\n--- Quick Stats ---")
        print(f"Valid measurements: {len(valid)}/{len(all_results)}")
        print(f"Failed: {len(failed)}")
        print(f"Mean error (CV - GT): {mean_err:+.4f} cm")
        print(f"Mean scale: {mean_scale:.2f} px/cm")
        print(f"Scale range: {min(scales):.2f} - {max(scales):.2f} px/cm")


if __name__ == "__main__":
    main()
