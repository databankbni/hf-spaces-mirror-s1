"""Validate SAM card detection (classic vs prompt) on sample-04-12.

Prompt-based SAM depends on MediaPipe running first to provide a hand mask
for seed derivation, so we run `segment_hand()` on each image before timing
the two detectors.

Outputs per-image rows and a summary with success counts + mean wall time.
Debug overlays saved under `output/sam_val/<stem>/`.
"""
from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.card_detection import compute_scale_factor, detect_credit_card  # noqa: E402
from src.finger_segmentation import segment_hand  # noqa: E402
from src.sam_card_detection import (  # noqa: E402
    detect_credit_card_sam_prompt,
    suggest_card_seeds,
)

SAMPLE_DIR = Path("input/sample-04-12")
OUT_DIR = Path("output/sam_val")


def _negatives_from_landmarks(landmarks: np.ndarray):
    palm_idx = [0, 5, 9, 13, 17]
    c = np.mean(landmarks[palm_idx, :2], axis=0)
    return [(int(round(c[0])), int(round(c[1])))]


def run_one(img_path: Path) -> dict:
    bgr = cv2.imread(str(img_path))
    if bgr is None:
        return {"file": img_path.name, "error": "load_failed"}

    rec = {"file": img_path.name, "shape": bgr.shape[:2]}

    # --- MediaPipe + SAM hand (needed for prompt-SAM seeds) ---
    t0 = time.time()
    try:
        hand_data = segment_hand(bgr, finger="index", use_sam_mask=True)
    except Exception as e:
        hand_data = None
        rec["hand_error"] = repr(e)[:120]
    rec["hand_time_s"] = round(time.time() - t0, 2)

    if hand_data is None:
        rec["hand_detected"] = False
        canonical = bgr
    else:
        rec["hand_detected"] = True
        canonical = hand_data.get("canonical_image", bgr)

    # --- Classic ---
    t0 = time.time()
    try:
        classic = detect_credit_card(canonical)
        if classic is not None:
            px_cm, _ = compute_scale_factor(classic["corners"])
            rec["classic_px_per_cm"] = px_cm
        else:
            rec["classic_px_per_cm"] = None
    except Exception as e:
        rec["classic_error"] = repr(e)[:120]
    rec["classic_time_s"] = round(time.time() - t0, 2)

    # --- SAM prompt ---
    rec["prompt_px_per_cm"] = None
    rec["prompt_time_s"] = None
    if hand_data is not None:
        prompt_debug = OUT_DIR / img_path.stem / "sam_card_prompt"
        landmarks = hand_data.get("landmarks")
        if landmarks is None or len(landmarks) <= 9:
            return rec
        middle_mcp = landmarks[9, :2]
        y_limit = int(round(middle_mcp[1]))
        seed_info = suggest_card_seeds(hand_data["mask"], canonical.shape[:2], y_limit)
        seeds = seed_info["kept"]
        rec["prompt_n_seeds"] = len(seeds)
        negs = _negatives_from_landmarks(hand_data["landmarks"])
        t0 = time.time()
        try:
            pr = detect_credit_card_sam_prompt(
                canonical,
                seed_points=seeds,
                negative_points=negs,
                debug_dir=str(prompt_debug),
                hand_mask=hand_data["mask"],
            )
            if pr is not None:
                px_cm, _ = compute_scale_factor(pr["corners"])
                rec["prompt_px_per_cm"] = px_cm
        except Exception as e:
            rec["prompt_error"] = repr(e)[:120]
            traceback.print_exc()
        rec["prompt_time_s"] = round(time.time() - t0, 2)

    return rec


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    images = sorted(SAMPLE_DIR.glob("*.jpg"))
    if not images:
        print(f"No images found in {SAMPLE_DIR}")
        return 1

    print(f"Validating {len(images)} images from {SAMPLE_DIR}\n")
    results = []
    for img in images:
        print(f"=== {img.name} ===")
        rec = run_one(img)
        results.append(rec)
        print(rec)
        print()

    # --- Summary table ---
    print("\n===== SUMMARY =====")
    header = (
        f"{'file':<18}"
        f"{'classic':>10}{'classicT':>10}"
        f"{'prompt':>10}{'promptT':>10}"
    )
    print(header)
    print("-" * len(header))

    counts = {"classic": 0, "prompt": 0}
    times = {"classic": [], "prompt": []}

    for r in results:
        def _fmt(v, fmt="{:.2f}"):
            return fmt.format(v) if v is not None else "FAIL"
        c = r.get("classic_px_per_cm")
        p = r.get("prompt_px_per_cm")
        ct = r.get("classic_time_s")
        pt = r.get("prompt_time_s")
        print(
            f"{r['file']:<18}"
            f"{_fmt(c):>10}{_fmt(ct):>10}"
            f"{_fmt(p):>10}{_fmt(pt):>10}"
        )
        if c is not None:
            counts["classic"] += 1
            times["classic"].append(ct)
        if p is not None:
            counts["prompt"] += 1
            times["prompt"].append(pt)

    n = len(results)
    print("-" * len(header))
    for k in ("classic", "prompt"):
        ok = counts[k]
        mean_t = (sum(times[k]) / len(times[k])) if times[k] else float("nan")
        print(f"{k:<8}  success: {ok}/{n}   mean_time_s: {mean_t:.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
