"""
Experiment: isolate the cause of the 'staircase' edges on our SAM 2.1 hand mask.

Runs five configurations of SAM 2.1 Hiera Small against a single sample image,
seeded by the MediaPipe palm center. All five variants feed the *same* pixel
prompts to the *same* model; only the inference input resolution and the
mask-upscale strategy differ.

Configurations:

    A  baseline   1024-long-side   hard-mask + INTER_NEAREST upscale   (current)
    B  lin_hard   1024-long-side   hard-mask + INTER_LINEAR + rethresh
    C  soft       1024-long-side   raw logits -> bilinear -> threshold full-res
    D  native_nn  native           hard-mask + INTER_NEAREST (no upscale needed)
    E  native_sft native           raw logits -> bilinear -> threshold

For each variant the script saves:
    - full-resolution binary mask PNG
    - hand overlay with yellow mask + green palm prompt dot
    - 600x600 fingertip crop centered on the middle-finger tip (landmark 12)
      so the staircase vs smooth comparison is visible at a glance

It also prints a small table:
    - perimeter (px)           cv2.arcLength of the largest contour
    - iso ratio                perimeter / sqrt(area) -- higher = more jagged
    - rel. to baseline (%)     iso ratio relative to config A

Usage:
    python script/experiment_sam_mask_quality.py \\
        --input input/sample-04-12/card_2.jpg \\
        --output-dir output/sam_mask_quality
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

# Add repo root so we can import src.*
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.finger_segmentation import segment_hand
from src.sam_backend import get_sam2
from src.sam_hand_segmentation import palm_center_from_landmarks


# ----------------------------------------------------------------------------
# SAM inference variants
# ----------------------------------------------------------------------------

def _run_sam(
    image_bgr: np.ndarray,
    palm_xy: Tuple[int, int],
    inference_long_side: Optional[int],
    upscale_mode: str,
) -> Tuple[np.ndarray, float, float]:
    """Run SAM 2.1 with controlled inference resolution and upscale path.

    Args:
        image_bgr: Full-resolution BGR image (canonical orientation).
        palm_xy: (x, y) pixel coords of palm center in the full-res image.
        inference_long_side: If set, downscale so long-side equals this value.
            If None, feed native resolution.
        upscale_mode: One of:
            - "nearest_hard": post_process_masks -> INTER_NEAREST to full res.
            - "linear_hard":  post_process_masks -> INTER_LINEAR -> re-threshold.
            - "soft":         raw pred_masks (256x256) -> bilinear to full res
                              -> threshold at 0.0.

    Returns:
        (mask_full: bool HxW, iou_score: float, infer_seconds: float)
    """
    import torch
    import torch.nn.functional as F
    from PIL import Image as PILImage

    h_full, w_full = image_bgr.shape[:2]
    long_side = max(h_full, w_full)

    if inference_long_side is None or long_side <= inference_long_side:
        scaled_bgr = image_bgr
        scale_back = 1.0
    else:
        s = inference_long_side / long_side
        new_w = int(round(w_full * s))
        new_h = int(round(h_full * s))
        scaled_bgr = cv2.resize(image_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
        scale_back = 1.0 / s

    scaled_rgb = cv2.cvtColor(scaled_bgr, cv2.COLOR_BGR2RGB)
    pil = PILImage.fromarray(scaled_rgb)

    scale_down = 1.0 / scale_back
    palm_scaled = [
        int(round(palm_xy[0] * scale_down)),
        int(round(palm_xy[1] * scale_down)),
    ]

    model, processor = get_sam2()

    t0 = time.time()
    inputs = processor(
        images=pil,
        input_points=[[[palm_scaled]]],
        input_labels=[[[1]]],
        return_tensors="pt",
    )
    with torch.inference_mode():
        outputs = model(**inputs, multimask_output=True)

    pred_masks = outputs.pred_masks.cpu()  # (1, 1, num_cands, H_low, W_low)
    iou_scores = outputs.iou_scores.cpu().numpy()[0, 0]
    best_idx = int(np.argmax(iou_scores))
    best_score = float(iou_scores[best_idx])

    if upscale_mode == "soft":
        logits = pred_masks[0, 0, best_idx].to(torch.float32)  # (H_low, W_low)
        logits_4d = logits.unsqueeze(0).unsqueeze(0)
        upsampled = F.interpolate(
            logits_4d,
            size=(h_full, w_full),
            mode="bilinear",
            align_corners=False,
        )[0, 0].numpy()
        mask_full = upsampled > 0.0
    else:
        masks_scaled = processor.post_process_masks(
            outputs.pred_masks.cpu(),
            inputs["original_sizes"],
            mask_threshold=0.0,
        )[0][0]
        mask_scaled = masks_scaled[best_idx].numpy().astype(np.uint8)  # scaled-res

        if mask_scaled.shape != (h_full, w_full):
            if upscale_mode == "nearest_hard":
                interp = cv2.INTER_NEAREST
            elif upscale_mode == "linear_hard":
                interp = cv2.INTER_LINEAR
            else:
                raise ValueError(f"unknown upscale_mode: {upscale_mode}")
            resized = cv2.resize(mask_scaled, (w_full, h_full), interpolation=interp)
            if upscale_mode == "linear_hard":
                mask_full = resized >= 1  # rethreshold after linear interp
            else:
                mask_full = resized.astype(bool)
        else:
            mask_full = mask_scaled.astype(bool)

    return mask_full, best_score, time.time() - t0


# ----------------------------------------------------------------------------
# Metrics + visualization helpers
# ----------------------------------------------------------------------------

def _roughness_metrics(mask: np.ndarray) -> Dict[str, float]:
    """Perimeter + isoperimetric ratio of the largest contour."""
    mask_u8 = (mask.astype(np.uint8)) * 255
    contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return {"perimeter_px": 0.0, "area_px": 0.0, "iso_ratio": float("nan")}
    largest = max(contours, key=cv2.contourArea)
    perim = float(cv2.arcLength(largest, closed=True))
    area = float(cv2.contourArea(largest))
    iso = perim / (np.sqrt(area) + 1e-9)
    return {"perimeter_px": perim, "area_px": area, "iso_ratio": iso}


def _save_overlay(
    path: Path,
    image_bgr: np.ndarray,
    mask: np.ndarray,
    palm_xy: Tuple[int, int],
    label: str,
) -> None:
    overlay = image_bgr.copy()
    tint = np.zeros_like(overlay)
    tint[mask] = (0, 255, 255)
    overlay = cv2.addWeighted(overlay, 1.0, tint, 0.35, 0)

    contours, _ = cv2.findContours(
        (mask.astype(np.uint8)) * 255, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
    )
    cv2.drawContours(overlay, contours, -1, (0, 255, 255), 2, cv2.LINE_AA)

    cv2.circle(overlay, palm_xy, 18, (0, 255, 0), -1)
    cv2.circle(overlay, palm_xy, 18, (0, 0, 0), 3)

    cv2.putText(overlay, label, (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.1,
                (255, 255, 255), 5, cv2.LINE_AA)
    cv2.putText(overlay, label, (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.1,
                (0, 255, 255), 2, cv2.LINE_AA)
    cv2.imwrite(str(path), overlay)


def _save_fingertip_crop(
    path: Path,
    image_bgr: np.ndarray,
    mask: np.ndarray,
    center_xy: Tuple[int, int],
    crop_half: int = 300,
    label: str = "",
) -> None:
    h, w = image_bgr.shape[:2]
    cx, cy = center_xy
    x0 = max(0, cx - crop_half)
    y0 = max(0, cy - crop_half)
    x1 = min(w, cx + crop_half)
    y1 = min(h, cy + crop_half)

    crop = image_bgr[y0:y1, x0:x1].copy()
    mask_crop = mask[y0:y1, x0:x1]

    tint = np.zeros_like(crop)
    tint[mask_crop] = (0, 255, 255)
    crop = cv2.addWeighted(crop, 1.0, tint, 0.4, 0)

    contours, _ = cv2.findContours(
        (mask_crop.astype(np.uint8)) * 255, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
    )
    cv2.drawContours(crop, contours, -1, (0, 255, 255), 2, cv2.LINE_AA)

    if label:
        cv2.putText(crop, label, (15, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                    (255, 255, 255), 4, cv2.LINE_AA)
        cv2.putText(crop, label, (15, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                    (0, 255, 255), 2, cv2.LINE_AA)

    cv2.imwrite(str(path), crop)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="input/sample-04-12/card_2.jpg")
    parser.add_argument("--output-dir", default="output/sam_mask_quality")
    args = parser.parse_args()

    in_path = Path(args.input)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    image = cv2.imread(str(in_path))
    if image is None:
        print(f"ERROR: could not read {in_path}")
        return 2

    print(f"Input: {in_path}  ({image.shape[1]}x{image.shape[0]})")

    # Get canonical image + landmarks WITHOUT running SAM. Pass a large
    # max_dimension so MediaPipe's internal resize does not happen and the
    # canonical image stays at native resolution.
    hand_data = segment_hand(
        image=image,
        finger="middle",
        max_dimension=3000,
        debug_dir=None,
        use_sam_mask=False,
    )
    if hand_data is None:
        print("ERROR: hand detection failed")
        return 2

    canonical = hand_data["canonical_image"]
    landmarks = hand_data["landmarks"]  # (21, 2) in canonical px coords
    palm_xy = palm_center_from_landmarks(landmarks)
    middle_tip_xy = (int(round(landmarks[12, 0])), int(round(landmarks[12, 1])))

    ch, cw = canonical.shape[:2]
    print(f"Canonical: {cw}x{ch}   palm=({palm_xy[0]},{palm_xy[1]})   "
          f"middle_tip=({middle_tip_xy[0]},{middle_tip_xy[1]})")

    # Save canonical reference image
    cv2.imwrite(str(out_dir / "00_canonical.png"), canonical)

    variants = [
        ("A_baseline_1024_nn",  1024, "nearest_hard"),
        ("B_1024_linear_hard",  1024, "linear_hard"),
        ("C_1024_soft",         1024, "soft"),
        ("D_native_nn",         None, "nearest_hard"),
        ("E_native_soft",       None, "soft"),
    ]

    results = []
    for name, long_side, mode in variants:
        print(f"\n=== {name}  long_side={long_side}  mode={mode} ===")
        mask, score, secs = _run_sam(canonical, palm_xy, long_side, mode)
        m = _roughness_metrics(mask)
        print(f"  iou={score:.3f}  time={secs:.2f}s  "
              f"perim={m['perimeter_px']:.0f}px  iso={m['iso_ratio']:.3f}")

        cv2.imwrite(str(out_dir / f"{name}_mask.png"),
                    (mask.astype(np.uint8)) * 255)
        _save_overlay(
            out_dir / f"{name}_overlay.png",
            canonical, mask, palm_xy,
            label=f"{name}  iou={score:.2f}",
        )
        _save_fingertip_crop(
            out_dir / f"{name}_fingertip.png",
            canonical, mask, middle_tip_xy,
            crop_half=300,
            label=name,
        )

        results.append((name, score, secs, m["perimeter_px"], m["iso_ratio"]))

    # Summary table
    print("\n")
    print("=" * 78)
    print(f"{'variant':<22}{'iou':>8}{'time(s)':>10}"
          f"{'perim(px)':>14}{'iso':>10}{'vs A (%)':>12}")
    print("-" * 78)
    iso_base = results[0][4]
    for name, score, secs, perim, iso in results:
        rel = (iso / iso_base - 1.0) * 100.0 if iso_base else float("nan")
        print(f"{name:<22}{score:>8.3f}{secs:>10.2f}"
              f"{perim:>14.0f}{iso:>10.3f}{rel:>11.1f}%")
    print("=" * 78)

    # Side-by-side fingertip comparison
    crops = [cv2.imread(str(out_dir / f"{name}_fingertip.png")) for name, *_ in results]
    if all(c is not None for c in crops):
        panel = np.hstack(crops)
        cv2.imwrite(str(out_dir / "fingertip_comparison.png"), panel)
        print(f"\nFingertip comparison strip: {out_dir / 'fingertip_comparison.png'}")

    print(f"\nAll outputs saved to: {out_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
