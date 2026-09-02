"""
SAM 2.1-based hand segmentation.

Produces a pixel-accurate hand mask using Meta's Segment Anything 2.1
(Hiera Tiny) via HuggingFace transformers, seeded by a positive point
prompt at the palm center (derived from MediaPipe landmarks). Optional
negative points can steer SAM away from the credit card.

This replaces the synthetic convex-hull "mask" produced by
`finger_segmentation._create_hand_mask()`, which is built from the
21 hand landmarks and does not follow the true hand contour.

Prompt-based inference: ~0.6s per call on CPU (vs ~18s for AMG).
"""

from __future__ import annotations

import logging
import time
from typing import List, Optional, Tuple

import cv2
import numpy as np

from .debug_observer import DebugObserver
from .sam_backend import INFERENCE_MAX_SIDE, get_sam2

logger = logging.getLogger(__name__)


def _downscale(image_bgr: np.ndarray) -> Tuple[np.ndarray, float]:
    """Downscale so the long side is INFERENCE_MAX_SIDE. Returns (scaled, scale_back).

    `scale_back` is the factor to multiply scaled coords by to get original coords.
    """
    h, w = image_bgr.shape[:2]
    long_side = max(h, w)
    if long_side <= INFERENCE_MAX_SIDE:
        return image_bgr, 1.0
    scale = INFERENCE_MAX_SIDE / long_side
    new_w = int(round(w * scale))
    new_h = int(round(h * scale))
    return cv2.resize(image_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA), 1.0 / scale


def segment_hand_sam(
    image_bgr: np.ndarray,
    palm_xy: Tuple[int, int],
    negative_points: Optional[List[Tuple[int, int]]] = None,
    debug_dir: Optional[str] = None,
) -> Optional[np.ndarray]:
    """Return a pixel-accurate bool hand mask (H x W) via SAM 2.1 Tiny.

    Args:
        image_bgr: Full-resolution BGR image in the canonical orientation.
        palm_xy: (x, y) pixel coordinates of the palm center (positive prompt).
        negative_points: Optional list of (x, y) points to steer SAM away from
            non-hand regions (e.g., credit card center).
        debug_dir: Optional directory to save mask + overlay for inspection.

    Returns:
        Bool mask of the same shape as `image_bgr[:2]`, or None on failure.
    """
    import torch
    import torch.nn.functional as F
    from PIL import Image as PILImage

    h_full, w_full = image_bgr.shape[:2]

    scaled_bgr, scale_back = _downscale(image_bgr)
    scaled_rgb = cv2.cvtColor(scaled_bgr, cv2.COLOR_BGR2RGB)
    pil = PILImage.fromarray(scaled_rgb)

    # Map prompt points into the scaled image space
    scale_down = 1.0 / scale_back  # original -> scaled
    palm_scaled = (int(round(palm_xy[0] * scale_down)), int(round(palm_xy[1] * scale_down)))
    prompt_points = [list(palm_scaled)]
    prompt_labels = [1]
    if negative_points:
        for nx, ny in negative_points:
            prompt_points.append([int(round(nx * scale_down)), int(round(ny * scale_down))])
            prompt_labels.append(0)

    model, processor = get_sam2()

    t0 = time.time()
    inputs = processor(
        images=pil,
        input_points=[[prompt_points]],
        input_labels=[[prompt_labels]],
        return_tensors="pt",
    )
    with torch.inference_mode():
        outputs = model(**inputs, multimask_output=True)

    # Use the raw 256x256 logits and bilinearly upsample them to the full
    # resolution before thresholding. Going through post_process_masks +
    # cv2.INTER_NEAREST binarizes at the scaled resolution and then blows
    # the hard mask up ~4x, which produces visible staircase edges on the
    # finger boundaries (see script/experiment_sam_mask_quality.py).
    pred_masks = outputs.pred_masks.cpu()  # (1, 1, num_cands, H_low, W_low)
    scores = outputs.iou_scores.cpu().numpy()[0, 0]
    best_idx = int(np.argmax(scores))
    best_score = float(scores[best_idx])

    logits_best = pred_masks[0, 0, best_idx].to(torch.float32)
    upsampled = F.interpolate(
        logits_best.unsqueeze(0).unsqueeze(0),
        size=(h_full, w_full),
        mode="bilinear",
        align_corners=False,
    )[0, 0].numpy()
    mask_full = upsampled > 0.0
    infer_time = time.time() - t0

    logger.info(
        "SAM hand mask: score=%.3f time=%.1fs area=%dpx",
        best_score, infer_time, int(mask_full.sum()),
    )

    if debug_dir:
        observer = DebugObserver(debug_dir)
        observer.save_stage("01_sam_hand_mask", mask_full.astype(np.uint8) * 255)

        overlay = image_bgr.copy()
        tint = np.zeros_like(overlay)
        tint[mask_full] = (0, 255, 255)
        overlay = cv2.addWeighted(overlay, 1.0, tint, 0.35, 0)

        contours, _ = cv2.findContours(
            mask_full.astype(np.uint8) * 255, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
        )
        cv2.drawContours(overlay, contours, -1, (0, 255, 255), 3, cv2.LINE_AA)

        cv2.circle(overlay, palm_xy, 20, (0, 255, 0), -1)
        cv2.circle(overlay, palm_xy, 20, (0, 0, 0), 3)
        if negative_points:
            for nx, ny in negative_points:
                cv2.circle(overlay, (int(nx), int(ny)), 20, (0, 0, 255), -1)
                cv2.circle(overlay, (int(nx), int(ny)), 20, (0, 0, 0), 3)

        label = f"SAM hand  score={best_score:.2f}  {infer_time:.1f}s"
        cv2.putText(overlay, label, (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.1,
                    (255, 255, 255), 5, cv2.LINE_AA)
        cv2.putText(overlay, label, (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.1,
                    (0, 255, 255), 2, cv2.LINE_AA)
        observer.save_stage("02_sam_hand_overlay", overlay)

    return mask_full


def palm_center_from_landmarks(landmarks_px: np.ndarray) -> Tuple[int, int]:
    """Return (x, y) pixel coord of the palm center from the 21 MediaPipe landmarks.

    Defined as the mean of wrist (0) + four MCPs (5, 9, 13, 17).
    """
    idx = [0, 5, 9, 13, 17]
    center = np.mean(landmarks_px[idx, :2], axis=0)
    return (int(round(center[0])), int(round(center[1])))
