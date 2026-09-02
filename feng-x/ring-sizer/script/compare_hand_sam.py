"""Compare hand-mask quality across backends on a single image.

Runs MediaPipe (current pipeline), SAM 2.1 tiny, and SAM 2.1 small using
a point prompt at the palm center from MediaPipe landmarks. Saves a 4-panel
side-by-side comparison and also writes each mask's contour + edge crop.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Tuple

import cv2
import numpy as np
from PIL import Image as PILImage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.finger_segmentation import segment_hand  # noqa: E402

IMG_PATH = Path("input/sample-04-12/card_2.jpg")
OUT_DIR = Path("output/hand_sam_compare")

SAM_MODELS = [
    ("sam2.1-tiny", "facebook/sam2.1-hiera-tiny"),
    ("sam2.1-small", "facebook/sam2.1-hiera-small"),
]


def palm_and_card_points(image_bgr: np.ndarray, hand_data: dict) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """Return (palm_center, card_center) pixel coords in the canonical image space.

    Palm center = mean of wrist + MCPs (landmarks 0, 5, 9, 13, 17).
    Card center = a rough point to the left of the hand (negative prompt hint).
    """
    landmarks = hand_data.get("landmarks")
    if landmarks is None:
        raise RuntimeError("MediaPipe returned no landmarks")

    # landmarks is (21, 2 or 3) in pixel coords
    lm = np.asarray(landmarks)[:, :2]
    palm_ids = [0, 5, 9, 13, 17]
    palm_center = tuple(np.round(lm[palm_ids].mean(axis=0)).astype(int).tolist())

    # Card hint: far from hand, toward image left
    h, w = image_bgr.shape[:2]
    hand_x_min = int(lm[:, 0].min())
    card_x = max(50, hand_x_min - 150)
    card_y = h // 2
    return palm_center, (card_x, card_y)


def run_sam(
    model_id: str,
    image_rgb: np.ndarray,
    palm_xy: Tuple[int, int],
    negative_xy: Tuple[int, int],
) -> Tuple[np.ndarray, float, float]:
    """Run SAM 2.1 with palm positive + card negative point. Returns (mask, score, seconds)."""
    import torch
    from transformers import Sam2Model, Sam2Processor

    processor = Sam2Processor.from_pretrained(model_id)
    model = Sam2Model.from_pretrained(model_id).to("cpu").eval()

    pil = PILImage.fromarray(image_rgb)
    input_points = [[[list(palm_xy), list(negative_xy)]]]
    input_labels = [[[1, 0]]]

    t0 = time.time()
    inputs = processor(
        images=pil,
        input_points=input_points,
        input_labels=input_labels,
        return_tensors="pt",
    )
    with torch.inference_mode():
        outputs = model(**inputs, multimask_output=True)

    masks = processor.post_process_masks(
        outputs.pred_masks.cpu(),
        inputs["original_sizes"],
        mask_threshold=0.0,
    )[0][0]  # (num_candidates, H, W) for first image, first prompt set
    scores = outputs.iou_scores.cpu().numpy()[0, 0]

    best_idx = int(np.argmax(scores))
    mask = masks[best_idx].numpy().astype(bool)
    return mask, float(scores[best_idx]), time.time() - t0


def mask_to_overlay(image_bgr: np.ndarray, mask: np.ndarray, color: Tuple[int, int, int]) -> np.ndarray:
    """Return a BGR image with the mask tinted + contour drawn."""
    out = image_bgr.copy()
    tint = np.zeros_like(out)
    tint[mask] = color
    out = cv2.addWeighted(out, 1.0, tint, 0.35, 0)

    contours, _ = cv2.findContours(
        mask.astype(np.uint8) * 255, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
    )
    cv2.drawContours(out, contours, -1, color, 2, cv2.LINE_AA)
    return out


def label_panel(img: np.ndarray, text: str) -> np.ndarray:
    h, w = img.shape[:2]
    cv2.rectangle(img, (0, 0), (w, 60), (0, 0, 0), -1)
    cv2.putText(img, text, (20, 42), cv2.FONT_HERSHEY_SIMPLEX, 1.3,
                (255, 255, 255), 3, cv2.LINE_AA)
    return img


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    image_bgr = cv2.imread(str(IMG_PATH))
    if image_bgr is None:
        print(f"Failed to load {IMG_PATH}")
        return 1

    print(f"Image: {IMG_PATH} {image_bgr.shape}")

    # --- MediaPipe baseline ---
    t0 = time.time()
    hand_data = segment_hand(image_bgr, finger="index")
    mp_time = time.time() - t0
    if hand_data is None:
        print("MediaPipe detected no hand — aborting")
        return 1

    canonical_image = hand_data.get("canonical_image", image_bgr)
    mp_mask = hand_data.get("mask")
    if mp_mask is None:
        print("MediaPipe did not return a hand mask")
        return 1
    mp_mask = mp_mask.astype(bool)
    print(f"MediaPipe: {mp_time:.1f}s  mask_area={mp_mask.sum()}")

    # Work in the canonical image so the comparison is apples-to-apples
    image_for_sam = canonical_image.copy()
    palm_xy, card_xy = palm_and_card_points(image_for_sam, hand_data)
    print(f"Palm prompt: {palm_xy}  Negative hint: {card_xy}")

    image_rgb = cv2.cvtColor(image_for_sam, cv2.COLOR_BGR2RGB)

    # --- SAM models ---
    results = {"mediapipe": (mp_mask, None, mp_time)}
    for name, model_id in SAM_MODELS:
        print(f"\n=== {name} ({model_id}) ===")
        try:
            mask, score, seconds = run_sam(model_id, image_rgb, palm_xy, card_xy)
            # Align shape (should already be canonical)
            if mask.shape != mp_mask.shape:
                mask = cv2.resize(
                    mask.astype(np.uint8),
                    (mp_mask.shape[1], mp_mask.shape[0]),
                    interpolation=cv2.INTER_NEAREST,
                ).astype(bool)
            print(f"  score={score:.3f}  time={seconds:.1f}s  area={mask.sum()}")
            results[name] = (mask, score, seconds)
        except Exception as e:
            print(f"  FAILED: {e!r}")
            import traceback
            traceback.print_exc()

    # --- Render panels ---
    panels = []
    colors = {
        "mediapipe": (0, 165, 255),      # orange
        "sam2.1-tiny": (0, 255, 255),    # yellow
        "sam2.1-small": (0, 255, 0),     # green
    }

    # Panel 0: original with prompt points
    orig = image_for_sam.copy()
    cv2.circle(orig, palm_xy, 18, (0, 255, 0), -1)
    cv2.circle(orig, palm_xy, 18, (0, 0, 0), 3)
    cv2.circle(orig, card_xy, 18, (0, 0, 255), -1)
    cv2.circle(orig, card_xy, 18, (0, 0, 0), 3)
    panels.append(label_panel(orig, "original + prompts"))

    for name in ["mediapipe", "sam2.1-tiny", "sam2.1-small"]:
        if name not in results:
            continue
        mask, score, seconds = results[name]
        panel = mask_to_overlay(image_for_sam, mask, colors[name])
        label = f"{name}  {seconds:.1f}s"
        if score is not None:
            label += f"  score={score:.2f}"
        panels.append(label_panel(panel, label))

    # Save individual panels full-res
    for i, p in enumerate(panels):
        cv2.imwrite(str(OUT_DIR / f"panel_{i}_{['orig','mediapipe','tiny','small'][i]}.png"), p)

    # Build a single side-by-side at a readable size
    def resize_to_height(img: np.ndarray, H: int) -> np.ndarray:
        h, w = img.shape[:2]
        scale = H / h
        return cv2.resize(img, (int(round(w * scale)), H), interpolation=cv2.INTER_AREA)

    target_h = 900
    resized = [resize_to_height(p, target_h) for p in panels]
    combined = np.hstack(resized)
    cv2.imwrite(str(OUT_DIR / "comparison_full.png"), combined)

    # Also zoom-crop around the hand for fine-detail inspection
    ys, xs = np.where(mp_mask)
    if len(xs) > 0:
        pad = 80
        x0, x1 = max(0, xs.min() - pad), min(image_for_sam.shape[1], xs.max() + pad)
        y0, y1 = max(0, ys.min() - pad), min(image_for_sam.shape[0], ys.max() + pad)
        crops = []
        for p in panels:
            crop = p[y0:y1, x0:x1]
            crops.append(resize_to_height(crop, target_h))
        combined_zoom = np.hstack(crops)
        cv2.imwrite(str(OUT_DIR / "comparison_zoom.png"), combined_zoom)

    print(f"\nSaved panels to {OUT_DIR}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
