"""Diagnose per-row rejection in mask_only edge detection.

Traces rejection reasons per ROI row by monkey-patching the edge extractor.
"""

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from measure_finger import measure_finger, load_image
from src.edge_refinement import extract_ring_zone_roi
from src.edge_refinement_constants import MIN_FINGER_WIDTH_CM, MAX_FINGER_WIDTH_CM


def diag(image_path: str, finger: str) -> None:
    snapshot = {}

    orig = extract_ring_zone_roi

    def spy(*args, **kwargs):
        roi_data = orig(*args, **kwargs)
        snapshot["roi_data"] = roi_data
        return roi_data

    import src.edge_refinement as er
    er.extract_ring_zone_roi = spy

    image = load_image(image_path)
    result = measure_finger(
        image=image,
        finger_index=finger,
        card_method="sam",
        edge_method="mask",
    )

    print(f"fail_reason: {result.get('fail_reason')}")
    print(f"finger_outer_diameter_cm: {result.get('finger_outer_diameter_cm')}")

    roi = snapshot.get("roi_data")
    if roi is None:
        print("ERROR: ROI not captured")
        return

    roi_mask = roi["roi_mask"]
    axis_center = roi["axis_center_in_roi"]
    axis_direction = roi["axis_direction_in_roi"]
    h, w = roi_mask.shape[:2]
    print(f"\nROI: {w}x{h}  axis_center={axis_center}  axis_direction={axis_direction}")

    px_per_cm = result.get("scale_px_per_cm", 0) or 0
    min_w = MIN_FINGER_WIDTH_CM * px_per_cm
    max_w = MAX_FINGER_WIDTH_CM * px_per_cm
    print(f"scale={px_per_cm:.2f} px/cm   width range: [{min_w:.1f}, {max_w:.1f}] px\n")

    reject_counts = {"no_mask": 0, "axis_off_mask": 0, "bleed_L": 0, "bleed_R": 0,
                     "bleed_both": 0, "width_oor": 0, "valid": 0}
    sample_widths = []

    mask_bool = roi_mask > 0
    max_col = w - 1

    for row in range(h):
        row_mask = mask_bool[row, :]
        if abs(axis_direction[1]) < 1e-6:
            axis_x = axis_center[0]
        else:
            t = (row - axis_center[1]) / axis_direction[1]
            axis_x = axis_center[0] + t * axis_direction[0]
        axis_col = max(0, min(max_col, int(round(axis_x))))

        if not np.any(row_mask):
            reject_counts["no_mask"] += 1
            continue

        if not row_mask[axis_col]:
            reject_counts["axis_off_mask"] += 1
            continue

        left_b = axis_col
        while left_b > 0 and row_mask[left_b - 1]:
            left_b -= 1
        right_b = axis_col
        while right_b < max_col and row_mask[right_b + 1]:
            right_b += 1

        bleed_L = left_b == 0
        bleed_R = right_b == max_col
        if bleed_L and bleed_R:
            reject_counts["bleed_both"] += 1
            continue
        if bleed_L:
            reject_counts["bleed_L"] += 1
            continue
        if bleed_R:
            reject_counts["bleed_R"] += 1
            continue

        width = right_b - left_b
        if not (min_w <= width <= max_w):
            reject_counts["width_oor"] += 1
            continue

        reject_counts["valid"] += 1
        sample_widths.append(width)

    total = sum(reject_counts.values())
    print(f"Totals over {total} rows:")
    for k, v in reject_counts.items():
        pct = 100.0 * v / total if total else 0
        print(f"  {k:<16}: {v:>5}  ({pct:5.1f}%)")

    if sample_widths:
        print(f"\nValid widths: n={len(sample_widths)}, min={min(sample_widths)}, "
              f"max={max(sample_widths)}, median={sorted(sample_widths)[len(sample_widths)//2]}")

    # Dump row profile as CSV
    print("\nrow,n_mask_runs,run_sizes,axis_col,axis_on_mask,left_b,right_b")
    for row in range(0, h, max(1, h // 40)):
        row_mask = mask_bool[row, :]
        # Count runs
        runs = []
        i = 0
        while i < w:
            if row_mask[i]:
                start = i
                while i < w and row_mask[i]:
                    i += 1
                runs.append((start, i - start))
            else:
                i += 1
        if abs(axis_direction[1]) < 1e-6:
            axis_x = axis_center[0]
        else:
            t = (row - axis_center[1]) / axis_direction[1]
            axis_x = axis_center[0] + t * axis_direction[0]
        axis_col = max(0, min(max_col, int(round(axis_x))))
        axis_on = row_mask[axis_col] if axis_col < w else False
        if axis_on:
            left_b = axis_col
            while left_b > 0 and row_mask[left_b - 1]:
                left_b -= 1
            right_b = axis_col
            while right_b < max_col and row_mask[right_b + 1]:
                right_b += 1
        else:
            left_b = right_b = -1
        run_str = ";".join(f"{s}:{l}" for s, l in runs)
        print(f"{row},{len(runs)},{run_str},{axis_col},{axis_on},{left_b},{right_b}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: python script/diag_mask_rows.py <image> <finger>")
        sys.exit(1)
    diag(sys.argv[1], sys.argv[2])
