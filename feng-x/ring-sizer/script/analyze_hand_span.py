#!/usr/bin/env python3
"""Hand-span ratio distribution analysis for the web-preview distance gate.

For each image in `input/kol_total` ∪ `input/kol_success`:
  1. Run MediaPipe Hands once on the original frame; compute
     hand_span_ratio = ||landmark[5] - landmark[17]|| / min(W, H).
  2. Run the full measurement pipeline once (cached) to get the authoritative
     fail_reason. This is the only way to cleanly separate `card_too_small`
     from other failure modes (`hand_not_detected`, `card_not_parallel`, etc.).
  3. Bucket ratios by fail_reason and print percentile stats so we can pick
     the preview "close enough" threshold (target: P10 of the success bucket
     to be conservative for small-handed users).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision

# Landmarks for the palm-MCP span (index MCP and pinky MCP).
LM_INDEX_MCP = 5
LM_PINKY_MCP = 17

IMG_EXTS = {".jpg", ".jpeg", ".png"}

# Reuse the same MediaPipe Tasks model the pipeline already downloads.
MODEL_PATH = (
    Path(__file__).resolve().parent.parent / ".model" / "hand_landmarker.task"
)

_detector = None


def _get_detector():
    global _detector
    if _detector is None:
        if not MODEL_PATH.exists():
            raise FileNotFoundError(
                f"hand_landmarker.task missing at {MODEL_PATH} — run measure_finger.py once to trigger the auto-download."
            )
        opts = mp_vision.HandLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(MODEL_PATH)),
            num_hands=1,
            min_hand_detection_confidence=0.3,
            min_tracking_confidence=0.3,
        )
        _detector = mp_vision.HandLandmarker.create_from_options(opts)
    return _detector


def hand_span_ratio(image_path: Path):
    """Return (ratio, h, w, detected). Try 4 rotations like the pipeline does;
    the ratio is rotation-invariant so we just take whichever rotation detects
    a hand with highest confidence."""
    img = cv2.imread(str(image_path))
    if img is None:
        return None, None, None, False
    h0, w0 = img.shape[:2]

    rotations = [
        (img, 0),
        (cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE), 1),
        (cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE), 3),
        (cv2.rotate(img, cv2.ROTATE_180), 2),
    ]

    detector = _get_detector()
    best_score = -1.0
    best_lm = None
    best_hw = None

    for rotated, _code in rotations:
        rgb = cv2.cvtColor(rotated, cv2.COLOR_BGR2RGB)
        rgb = np.ascontiguousarray(rgb)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        res = detector.detect(mp_image)
        if not res.hand_landmarks:
            continue
        score = res.handedness[0][0].score if res.handedness else 0.0
        if score > best_score:
            best_score = score
            best_lm = res.hand_landmarks[0]
            best_hw = rotated.shape[:2]

    if best_lm is None:
        return None, h0, w0, False

    rh, rw = best_hw
    p5 = np.array([best_lm[LM_INDEX_MCP].x * rw, best_lm[LM_INDEX_MCP].y * rh])
    p17 = np.array([best_lm[LM_PINKY_MCP].x * rw, best_lm[LM_PINKY_MCP].y * rh])
    span_px = float(np.linalg.norm(p5 - p17))
    short_side = min(rh, rw)  # rotation-invariant
    return span_px / short_side, h0, w0, True


def measure_fail_reason(image_path: Path, cache_dir: Path, base: Path) -> dict:
    """Run measure_finger.py once (cached) and return its result dict."""
    out_json = cache_dir / f"{image_path.stem}.json"
    if not out_json.exists():
        cmd = [
            sys.executable, "measure_finger.py",
            "--input", str(image_path),
            "--output", str(out_json),
            "--finger-index", "index",
            "--card-method", "sam",
            "--no-calibration",
        ]
        try:
            subprocess.run(
                cmd, capture_output=True, text=True, timeout=180, cwd=base,
            )
        except subprocess.TimeoutExpired:
            return {"fail_reason": "timeout"}
    if out_json.exists():
        with open(out_json) as f:
            return json.load(f)
    return {"fail_reason": "no_output"}


def percentiles(values, ps=(10, 25, 50, 75, 90)):
    if not values:
        return {p: None for p in ps}
    arr = np.array(values)
    return {p: float(np.percentile(arr, p)) for p in ps}


def main():
    base = Path(__file__).resolve().parent.parent
    os.chdir(base)

    # Union of kol_total and kol_success, dedup by filename.
    by_name = {}
    for d in ("kol_total", "kol_success"):
        folder = base / "input" / d
        if not folder.is_dir():
            continue
        for p in folder.iterdir():
            if p.suffix.lower() in IMG_EXTS:
                by_name.setdefault(p.name, p)
    images = sorted(by_name.values(), key=lambda p: p.name)
    print(f"Found {len(images)} unique images across kol_total ∪ kol_success")

    cache_dir = base / "output" / "hand_span_analysis"
    cache_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for i, img_path in enumerate(images, 1):
        print(f"[{i}/{len(images)}] {img_path.name}", end=" ", flush=True)

        ratio, h, w, detected = hand_span_ratio(img_path)
        meas = measure_fail_reason(img_path, cache_dir, base)
        fail = meas.get("fail_reason")

        results.append({
            "image": img_path.name,
            "h": h, "w": w,
            "hand_detected_mediapipe": detected,
            "hand_span_ratio": ratio,
            "fail_reason": fail,
            "scale_px_per_cm": meas.get("scale_px_per_cm"),
        })
        print(f"ratio={ratio if ratio is None else f'{ratio:.3f}'} fail={fail}")

    out_json = cache_dir / "hand_span_results.json"
    with open(out_json, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved {out_json}")

    # Bucket by fail_reason.
    buckets: dict[str, list[float]] = {}
    for r in results:
        if r["hand_span_ratio"] is None:
            key = "_mediapipe_no_hand"
        else:
            key = r["fail_reason"] or "success"
            buckets.setdefault(key, []).append(r["hand_span_ratio"])

    print("\n=== hand_span_ratio distribution by fail_reason ===")
    print(f"{'bucket':<30} {'n':>4}  {'P10':>6} {'P25':>6} {'P50':>6} {'P75':>6} {'P90':>6}  mean")
    for key in sorted(buckets, key=lambda k: (-len(buckets[k]), k)):
        vals = buckets[key]
        ps = percentiles(vals)
        mean = float(np.mean(vals))
        line = (
            f"{key:<30} {len(vals):>4}  "
            f"{ps[10]:.3f}  {ps[25]:.3f}  {ps[50]:.3f}  {ps[75]:.3f}  {ps[90]:.3f}   {mean:.3f}"
        )
        print(line)

    no_hand = sum(1 for r in results if not r["hand_detected_mediapipe"])
    print(f"\nMediaPipe failed to detect a hand on {no_hand}/{len(results)} images.")

    # Threshold suggestion.
    success = buckets.get("success", [])
    too_small = buckets.get("card_too_small", [])
    if success:
        p10_success = float(np.percentile(success, 10))
        print(f"\nSuggested preview gate: hand_span_ratio >= {p10_success:.3f}")
        print(f"  (P10 of success cohort, conservative for small-handed users)")
        if too_small:
            below = sum(1 for v in too_small if v < p10_success)
            print(f"  {below}/{len(too_small)} card_too_small samples fall below this gate.")
            above = sum(1 for v in success if v >= p10_success)
            print(f"  {above}/{len(success)} success samples pass this gate (= 90% by construction).")


if __name__ == "__main__":
    main()
