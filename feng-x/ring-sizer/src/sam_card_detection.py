"""
SAM 2.1-based credit card detection.

Uses Meta's Segment Anything 2.1 (Hiera Tiny) via HuggingFace transformers
to produce a pixel-accurate card mask, then filters candidate masks by area,
rectangularity, and aspect ratio (~1.586) to pick the credit card.

Drop-in replacement for `card_detection.detect_credit_card`: returns a dict
with the same keys so the downstream pipeline is unchanged.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from .card_detection import (
    CARD_ASPECT_RATIO,
    MIN_CARD_AREA_RATIO,
    get_quad_dimensions,
    order_corners,
)
from .sam_backend import INFERENCE_MAX_SIDE as PROMPT_INFERENCE_MAX_SIDE, get_sam2

logger = logging.getLogger(__name__)

# Candidate filtering
MIN_RECTANGULARITY = 0.90  # mask_area / minAreaRect_area; card mask is near-perfect rectangle
ASPECT_RATIO_TOLERANCE = 0.15  # fractional deviation from 1.586
MAX_HAND_OVERLAP_RATIO = 0.20  # reject candidates that swallow the hand (background paper, tabletop)
# Reject candidates whose convex hull is "fattened" by hand-shaped indentations.
# A real card mask is convex, so hull == mask and (hull \ mask) ∩ hand is ~0.
# When SAM segments a chunk of background (e.g. paper towel) bordered by the
# hand, the mask has a hand-shaped notch on one side; the hull closes that
# notch and adds hand pixels. Empirically: real-card winners measure 0.000,
# paper-towel false positives measure ~0.10+.
MAX_HULL_HAND_FILL_RATIO = 0.05
# SAM-specific upper bound on card area. Tighter than the shared
# MAX_CARD_AREA_RATIO (0.5) because SAM happily returns whole-background
# segments (ceilings, walls) as a single rectangular-ish mask when no card
# is actually present — a ~50% half-image mask can pass rectangularity and
# aspect ratio purely by accident. A real credit card held alongside a hand
# is ~5-15% of the frame; 25% is already 2× the realistic maximum.
SAM_MAX_CARD_AREA_RATIO = 0.25
# Reject candidates whose longer side spans more of the image short side
# than any real card photo plausibly would. This catches the distinctive
# SAM failure where a single-prompt mask grabs the entire background paper
# / tabletop: the candidate is long and thin (so its mask area sneaks
# under SAM_MAX_CARD_AREA_RATIO) but its bounding rectangle stretches
# across nearly the full image short side (framing ratio ~0.99). Threshold
# picked from doc/report/framing_ratio_survey.md: max observed in 47 KOL
# successes is 0.532, max in calibration is 0.486; 0.70 leaves ≥30% margin
# above legitimate framing while sitting well below the ~1.0 failure mode.
MAX_CARD_FRAMING_RATIO = 0.70


def _score_card_mask(
    mask: np.ndarray,
    image_area: float,
    hand_mask: Optional[np.ndarray] = None,
    image_short_side: float = 0.0,
    iou_score: float = 0.0,
) -> Optional[Dict[str, Any]]:
    """Score a candidate mask for being a credit card.

    Returns a dict with {corners, width, height, area, aspect_ratio, rectangularity, score}
    or None if the mask is rejected.
    """
    mask_u8 = mask.astype(np.uint8) * 255
    mask_area = float(mask.sum())

    area_ratio = mask_area / image_area
    if area_ratio < MIN_CARD_AREA_RATIO or area_ratio > SAM_MAX_CARD_AREA_RATIO:
        return None

    contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    # Largest external contour is the card body (SAM masks can be slightly disconnected).
    # Take its convex hull before scoring: credit cards are convex, so the hull
    # erases SAM boundary noise that varies with CPU numerics (the same mask on
    # x86 vs Apple Silicon can bump `contour_area / rect_area` below 0.90 purely
    # from Torch CPU activation drift). Non-card shapes stay non-rectangular
    # under their hull, so this does not create false positives.
    largest_contour = max(contours, key=cv2.contourArea)
    contour = cv2.convexHull(largest_contour)
    contour_area = cv2.contourArea(contour)
    if contour_area <= 0:
        return None

    # Replace the raw multi-blob SAM mask with just the largest connected
    # component. The card prompt with multimask_output=True occasionally lassos
    # background paper between fingers as part of the same candidate; those
    # blobs pass scoring (we only check the largest contour) but pollute every
    # downstream consumer of `result["mask"]` (debug overlays, the result PNG).
    clean_mask_u8 = np.zeros_like(mask_u8)
    cv2.drawContours(clean_mask_u8, [largest_contour], -1, 255, thickness=cv2.FILLED)
    mask = clean_mask_u8.astype(bool)

    # Reject candidates whose convex hull engulfs the hand. When SAM is
    # prompted to segment the background paper, it returns the paper mask
    # with the hand carved *out* of it — so raw AND(mask, hand) is ~0
    # even though the hand sits visually on top of the paper. The convex
    # hull closes that hand-shaped hole, exposing the engulfment.
    if hand_mask is not None and mask.shape == hand_mask.shape:
        hand_bool = hand_mask.astype(bool) if hand_mask.dtype != bool else hand_mask
        hand_area = float(hand_bool.sum())
        if hand_area > 0:
            hull_mask = np.zeros(mask.shape, dtype=np.uint8)
            cv2.fillPoly(hull_mask, [contour.astype(np.int32)], 255)
            hull_bool = hull_mask.astype(bool)
            overlap = float(np.logical_and(hull_bool, hand_bool).sum())
            if overlap / hand_area > MAX_HAND_OVERLAP_RATIO:
                return None
            if mask_area > 0 and overlap / mask_area > MAX_HULL_HAND_FILL_RATIO:
                return None

    rect = cv2.minAreaRect(contour)
    box = cv2.boxPoints(rect)
    rect_area = cv2.contourArea(box.astype(np.float32))
    if rect_area <= 0:
        return None

    rectangularity = contour_area / rect_area
    if rectangularity < MIN_RECTANGULARITY:
        return None

    corners = order_corners(box)
    width, height = get_quad_dimensions(corners)
    if width <= 0 or height <= 0:
        return None

    # Reject long-thin SAM false positives that span ~the entire image short
    # side. These slip past SAM_MAX_CARD_AREA_RATIO because their pixel
    # count is modest (the mask is hollow / not solidly filled), but their
    # bounding rectangle gives them away.
    if image_short_side > 0:
        framing_ratio = max(width, height) / image_short_side
        if framing_ratio > MAX_CARD_FRAMING_RATIO:
            return None

    aspect_ratio = max(width, height) / min(width, height)
    ratio_diff = abs(aspect_ratio - CARD_ASPECT_RATIO) / CARD_ASPECT_RATIO
    if ratio_diff > ASPECT_RATIO_TOLERANCE:
        return None

    # Score components — picking weights here is delicate because real
    # photos have *perspective foreshortening* that pulls the apparent card
    # aspect away from the flat-card ideal of 1.586. A mask that bleeds
    # extra background paper onto the short edge can pull aspect *closer*
    # to the ideal than a tight mask, so over-weighting ratio_score selects
    # fattened masks (the Brooklyn Shields case). The current split:
    #   * 0.3 ratio  — kept as a soft preference but no longer dominant
    #   * 0.4 rect   — primary signal; tight cards are near-perfect rectangles,
    #                  fattened SAM masks always lose a little here
    #   * 0.1 area   — small reward for "actually card-sized"
    #   * 0.2 iou    — SAM's own segmentation confidence; stable across
    #                  platforms because it's decoder-internal, not derived
    #                  from per-pixel boundary noise. Acts as a second opinion
    #                  that breaks the tie when geometry is too close to call.
    ratio_score = 1.0 - ratio_diff / ASPECT_RATIO_TOLERANCE
    rect_score = (rectangularity - MIN_RECTANGULARITY) / (1.0 - MIN_RECTANGULARITY)
    area_score = min(area_ratio / 0.1, 1.0)  # caps at 10% of image area
    score = (
        0.3 * ratio_score
        + 0.4 * rect_score
        + 0.1 * area_score
        + 0.2 * iou_score
    )

    return {
        "corners": corners,
        "contour": contour,
        "width": width,
        "height": height,
        "area": mask_area,
        "aspect_ratio": aspect_ratio,
        "rectangularity": rectangularity,
        "score": score,
        "mask": mask,
    }


# ---------------------------------------------------------------------------
# Prompt-based card detection
# ---------------------------------------------------------------------------


def suggest_card_seeds(
    hand_mask: np.ndarray,
    image_shape: Tuple[int, int],
    y_limit: int,
) -> Dict[str, List[Tuple[int, int]]]:
    """Uniform 4x4 grid seeds in the top band of the canonical image.

    In canonical orientation the fingertips point up, so the middle-finger
    MCP is the lowest landmark of the middle finger. Users overwhelmingly
    place the card in the band between the top of the frame and the MCP
    row (beside or above the fingers), so sampling that band catches the
    card with a handful of prompts. The grid excludes a 10% border padding
    on all four sides of the band and drops any seed that lands on the
    hand mask.

    Args:
        hand_mask: SAM hand mask (HxW, bool or uint8).
        image_shape: (H, W) of the canonical image.
        y_limit: Y coordinate of the middle-finger MCP; the grid spans
            [0.1·H, y_limit] vertically.

    Returns:
        Dict with two lists:
            - "kept": seeds that passed the hand-mask filter (sent to SAM).
            - "dropped": seeds whose (x, y) landed inside the hand mask and
              were filtered out. Retained purely for debug visualization.
    """
    h, w = image_shape
    mask_bool = hand_mask.astype(bool) if hand_mask.dtype != bool else hand_mask

    x_min = 0.1 * w
    x_max = 0.9 * w
    y_min = 0.1 * h
    y_max = float(y_limit)
    # Guard against degenerate bands (e.g., MCP above the 10% top padding).
    if y_max <= y_min:
        y_max = y_min + 1.0

    n = 4
    candidates: List[Tuple[int, int]] = []
    for iy in range(n):
        fy = (iy + 0.5) / n
        py = int(round(y_min + fy * (y_max - y_min)))
        for ix in range(n):
            fx = (ix + 0.5) / n
            px = int(round(x_min + fx * (x_max - x_min)))
            candidates.append((px, py))

    kept: List[Tuple[int, int]] = []
    dropped: List[Tuple[int, int]] = []
    seen: set = set()
    for px, py in candidates:
        px = max(0, min(w - 1, px))
        py = max(0, min(h - 1, py))
        if (px, py) in seen:
            continue
        seen.add((px, py))
        if mask_bool[py, px]:
            dropped.append((px, py))
        else:
            kept.append((px, py))
    return {"kept": kept, "dropped": dropped}


def _downscale_prompt(image_bgr: np.ndarray) -> Tuple[np.ndarray, float]:
    """Downscale for prompt inference. Returns (scaled, scale_back)."""
    h, w = image_bgr.shape[:2]
    long_side = max(h, w)
    if long_side <= PROMPT_INFERENCE_MAX_SIDE:
        return image_bgr, 1.0
    scale = PROMPT_INFERENCE_MAX_SIDE / long_side
    new_w = int(round(w * scale))
    new_h = int(round(h * scale))
    scaled = cv2.resize(image_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return scaled, 1.0 / scale


def _save_prompt_debug(
    debug_dir: str,
    image_bgr: np.ndarray,
    seeds: List[Tuple[int, int]],
    negatives: List[Tuple[int, int]],
    candidate_masks: List[np.ndarray],
    scored: List[Dict[str, Any]],
    best: Optional[Dict[str, Any]],
) -> None:
    """Save debug visualizations for prompt-based card detection."""
    from .debug_observer import DebugObserver
    observer = DebugObserver(debug_dir)

    # 01: prompt points on the image
    pts_img = image_bgr.copy()
    for (px, py) in seeds:
        cv2.circle(pts_img, (px, py), 20, (0, 255, 0), -1)
        cv2.circle(pts_img, (px, py), 20, (0, 0, 0), 3)
    for (nx, ny) in negatives:
        cv2.circle(pts_img, (nx, ny), 20, (0, 0, 255), -1)
        cv2.circle(pts_img, (nx, ny), 20, (0, 0, 0), 3)
    observer.save_stage("01_prompt_points", pts_img)

    # 02: all candidate masks overlaid (one color per prompt)
    overlay = image_bgr.copy()
    rng = np.random.default_rng(7)
    for m in candidate_masks:
        if m is None or m.sum() == 0:
            continue
        color = rng.integers(64, 255, size=3).tolist()
        overlay[m] = (0.5 * overlay[m] + 0.5 * np.array(color)).astype(np.uint8)
    observer.save_stage("02_candidate_masks", overlay)

    # 03: scored candidates
    cand_img = image_bgr.copy()
    for s in scored:
        corners = s["corners"].astype(np.int32)
        cv2.polylines(cand_img, [corners], True, (0, 255, 0), 3)
        cv2.putText(
            cand_img,
            f"{s['score']:.2f} ar={s['aspect_ratio']:.3f}",
            tuple(corners[0]),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.2,
            (0, 255, 0),
            3,
            cv2.LINE_AA,
        )
    observer.save_stage("03_scored", cand_img)

    if best is not None:
        final = image_bgr.copy()
        mask_u8 = best["mask"].astype(np.uint8) * 255
        tint = np.zeros_like(final)
        tint[:, :, 1] = mask_u8
        final = cv2.addWeighted(final, 1.0, tint, 0.35, 0)
        corners = best["corners"].astype(np.int32)
        cv2.polylines(final, [corners], True, (0, 255, 0), 4)
        for pt in corners:
            cv2.circle(final, tuple(pt), 10, (0, 0, 255), -1)
        label = (
            f"SAM-prompt card  score={best['score']:.3f}  "
            f"ar={best['aspect_ratio']:.3f}  rect={best['rectangularity']:.3f}"
        )
        cv2.putText(final, label, (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.1,
                    (255, 255, 255), 5, cv2.LINE_AA)
        cv2.putText(final, label, (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.1,
                    (0, 255, 0), 2, cv2.LINE_AA)
        observer.save_stage("04_final_selection", final)


def detect_credit_card_sam_prompt(
    image: np.ndarray,
    seed_points: List[Tuple[int, int]],
    negative_points: Optional[List[Tuple[int, int]]] = None,
    debug_dir: Optional[str] = None,
    hand_mask: Optional[np.ndarray] = None,
) -> Optional[Dict[str, Any]]:
    """Prompt-based SAM 2.1 credit card detection.

    For each seed point, runs a single-point SAM decoder pass with
    `multimask_output=True` and collects all returned masks. Every mask is
    then filtered through `_score_card_mask`; the highest-scoring survivor
    is returned. This is ~20× faster than the AMG path because it runs the
    decoder ~N times (one per seed) instead of 256 times on a dense grid.

    Args:
        image: Full-resolution BGR image (canonical orientation).
        seed_points: List of (x, y) positive-point candidates. Each one is
            tried independently. A few well-placed candidates are enough.
        negative_points: Optional list of (x, y) negative points applied to
            every seed's prompt (e.g., palm center to steer SAM off the hand).
        debug_dir: Optional directory to dump debug visualizations.

    Returns:
        Card dict matching `detect_credit_card`, or None if no seed produced
        a valid card mask.
    """
    import torch
    from PIL import Image as PILImage

    if not seed_points:
        logger.info("SAM-prompt: no seed points provided")
        return None

    h, w = image.shape[:2]
    image_area = float(h * w)

    scaled_bgr, scale_back = _downscale_prompt(image)
    scaled_rgb = cv2.cvtColor(scaled_bgr, cv2.COLOR_BGR2RGB)
    pil = PILImage.fromarray(scaled_rgb)
    scale_down = 1.0 / scale_back  # original → scaled

    def _to_scaled(pts: List[Tuple[int, int]]) -> List[List[int]]:
        return [[int(round(px * scale_down)), int(round(py * scale_down))] for px, py in pts]

    seeds_scaled = _to_scaled(seed_points)
    negatives_scaled = _to_scaled(negative_points) if negative_points else []

    # Build one prompt per seed; each prompt carries (1 positive + all negatives)
    # input_points shape: [batch=1, num_prompts, points_per_prompt, 2]
    # input_labels shape: [batch=1, num_prompts, points_per_prompt]
    points_per_prompt = 1 + len(negatives_scaled)
    input_points = [[[seed] + negatives_scaled for seed in seeds_scaled]]
    input_labels = [[[1] + [0] * len(negatives_scaled) for _ in seeds_scaled]]

    model, processor = get_sam2()

    t0 = time.time()
    inputs = processor(
        images=pil,
        input_points=input_points,
        input_labels=input_labels,
        return_tensors="pt",
    )
    with torch.inference_mode():
        # multimask_output=True gives 3 masks per seed (small / medium / large
        # disambiguation of the prompt). Empirically this matters for card
        # detection: SAM's single-best IoU mask sometimes latches onto a
        # sub-region or a nearby distractor, but one of the other two
        # candidates is the full card. Scoring cost is fine because we score
        # in the scaled 1024-space, not full resolution.
        outputs = model(**inputs, multimask_output=True)

    # Score masks in the scaled 1024-space. Only the single winner is
    # upscaled to full resolution afterward, which avoids O(N) 12 MP resizes.
    scaled_h = inputs["original_sizes"][0][0].item()
    scaled_w = inputs["original_sizes"][0][1].item()
    scaled_area = float(scaled_h * scaled_w)

    masks_list = processor.post_process_masks(
        outputs.pred_masks.cpu(),
        inputs["original_sizes"],
        mask_threshold=0.0,
    )
    masks_tensor = masks_list[0]  # (num_prompts, num_candidates, H_s, W_s)
    iou_scores = outputs.iou_scores.cpu().numpy()[0]
    infer_time = time.time() - t0

    # Resize the hand mask into the same scaled 1024-space the candidate
    # masks live in, so overlap rejection works without upscaling every
    # candidate to full resolution.
    hand_mask_scaled: Optional[np.ndarray] = None
    if hand_mask is not None:
        hand_u8 = (hand_mask.astype(bool).astype(np.uint8) * 255)
        if hand_u8.shape != (scaled_h, scaled_w):
            hand_u8 = cv2.resize(
                hand_u8, (scaled_w, scaled_h),
                interpolation=cv2.INTER_NEAREST,
            )
        hand_mask_scaled = hand_u8.astype(bool)

    scored: List[Dict[str, Any]] = []
    scaled_candidate_masks: List[np.ndarray] = []
    for prompt_idx in range(masks_tensor.shape[0]):
        for cand_idx in range(masks_tensor.shape[1]):
            mask_scaled = masks_tensor[prompt_idx, cand_idx].numpy().astype(bool)
            scaled_candidate_masks.append(mask_scaled)
            iou = float(iou_scores[prompt_idx, cand_idx])
            result = _score_card_mask(
                mask_scaled, scaled_area, hand_mask=hand_mask_scaled,
                image_short_side=float(min(scaled_h, scaled_w)),
                iou_score=iou,
            )
            if result is not None:
                result["seed_idx"] = prompt_idx
                result["cand_idx"] = cand_idx
                result["iou_score"] = iou
                # `result["mask"]` is the cleaned (largest-component) mask;
                # keep that as the scaled-space mask so upscaling and debug
                # rendering both see the cleaned version.
                result["mask_scaled"] = result["mask"]
                scored.append(result)

    scored.sort(key=lambda d: d["score"], reverse=True)
    best = scored[0] if scored else None

    # Upscale only the winning mask + corners to full resolution
    if best is not None:
        mask_scaled_best = best["mask_scaled"]
        if mask_scaled_best.shape != (h, w):
            mask_full = cv2.resize(
                mask_scaled_best.astype(np.uint8), (w, h),
                interpolation=cv2.INTER_NEAREST,
            ).astype(bool)
        else:
            mask_full = mask_scaled_best
        best["mask"] = mask_full
        best["corners"] = best["corners"] * scale_back
        best["width"] = best["width"] * scale_back
        best["height"] = best["height"] * scale_back

    logger.info(
        "SAM-prompt: %d seeds, %d candidates, %d passed filter, inference=%.2fs",
        len(seed_points),
        masks_tensor.shape[0] * masks_tensor.shape[1],
        len(scored), infer_time,
    )

    if debug_dir:
        # Render debug overlays in the downscaled 1024-space. Upscaling
        # ~60 masks to full 12 MP resolution just for PNGs was dominating
        # end-to-end time (8–10s out of ~9s total). The debug images are
        # for human inspection; 1024 is plenty.
        dh, dw = scaled_bgr.shape[:2]
        debug_seeds = [
            (int(round(px / scale_back)), int(round(py / scale_back)))
            for px, py in seed_points
        ]
        debug_negs = [
            (int(round(px / scale_back)), int(round(py / scale_back)))
            for px, py in (negative_points or [])
        ]
        debug_scored_for_viz = []
        for s in scored:
            s_copy = dict(s)
            s_copy["corners"] = s["corners"]  # already scaled-space
            s_copy["mask"] = s["mask_scaled"]
            debug_scored_for_viz.append(s_copy)
        best_for_viz = None
        if best is not None:
            best_for_viz = dict(best)
            best_for_viz["corners"] = best["corners"] / scale_back  # back to scaled
            best_for_viz["mask"] = best["mask_scaled"]
        _save_prompt_debug(
            debug_dir, scaled_bgr, debug_seeds, debug_negs,
            scaled_candidate_masks, debug_scored_for_viz, best_for_viz,
        )

    if best is None:
        return None

    logger.info(
        "SAM-prompt card: score=%.3f, aspect=%.3f, rect=%.3f, %.0fx%.0fpx (seed %d)",
        best["score"], best["aspect_ratio"], best["rectangularity"],
        best["width"], best["height"], best["seed_idx"],
    )

    return {
        "corners": best["corners"],
        "contour": best["corners"],
        "confidence": float(best["score"]),
        "width_px": float(best["width"]),
        "height_px": float(best["height"]),
        "aspect_ratio": float(best["aspect_ratio"]),
        "mask": best["mask"],  # bool HxW, canonical-image coords
        "mask_source": "sam_prompt",
    }
