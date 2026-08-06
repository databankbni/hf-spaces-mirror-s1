from __future__ import annotations

import base64
import io
import os
import re
import uuid
from collections import defaultdict
from io import BytesIO
from threading import Lock
from typing import Any

import cloudinary
import cloudinary.uploader
import numpy as np
import requests
import torch
from fastapi import FastAPI, HTTPException, Request
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageOps
from pydantic import BaseModel, Field, field_validator
from scipy import ndimage
from transformers import (
    AutoModelForZeroShotObjectDetection,
    AutoProcessor,
    Sam2Model,
    Sam2Processor,
)

app = FastAPI(title="Interior Design Image API", version="2.0.0")


@app.get("/")
def root():
    return {
        "status": "Auto-mask API is running",
        "endpoints": [
            "/auto-mask",
            "/generate-editor-mask",
            "/convert-editor-mask",
            "/apply-fabric",
            "/normalize-furniture-image",
            "/prepare-fabric-tile",
            "/prepare-repeat-tile",
            "/preview-panels",
            "/generate-seam-overlay",
            "/detect-room-objects",
            "/health",
        ],
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "device": DEVICE if "DEVICE" in globals() else "initializing",
        "cuda_available": torch.cuda.is_available(),
        "grounding_dino_model_id": globals().get("GROUNDING_DINO_MODEL_ID"),
        "sam2_model_id": globals().get("SAM2_MODEL_ID"),
    }


# =====================================================================
# Basic image helpers
# =====================================================================


def image_to_base64_data_uri(image: Image.Image) -> str:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    image_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{image_base64}"


def download_image(image_url: str) -> Image.Image:
    response = requests.get(image_url, timeout=30)
    response.raise_for_status()
    return Image.open(BytesIO(response.content)).convert("RGBA")


def load_image_from_url(url: str) -> Image.Image:
    try:
        return download_image(url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not load image: {str(e)}")


def _as_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ["false", "0", "no", "off", ""]


# =====================================================================
# Mask helpers
# =====================================================================


def create_alpha_mask_from_transparency(image: Image.Image, alpha_threshold: int = 10) -> Image.Image:
    image = image.convert("RGBA")
    alpha = np.array(image.getchannel("A"))

    out = np.zeros((image.height, image.width, 4), dtype=np.uint8)
    visible = alpha > alpha_threshold
    out[visible] = (255, 255, 255, 255)

    return Image.fromarray(out, "RGBA")


def create_green_editor_mask_from_transparency(
    image: Image.Image,
    alpha_threshold: int = 10,
) -> Image.Image:
    """
    Creates the initial green upholstery editor mask at the SAME size
    as the input furniture image. No forced 600x600 / 1024x1024 resize.
    """
    image = image.convert("RGBA")
    alpha = np.array(image.getchannel("A"))

    out = np.zeros((image.height, image.width, 4), dtype=np.uint8)
    visible = alpha > alpha_threshold
    out[visible] = (0, 200, 83, 110)

    return Image.fromarray(out, "RGBA")


def convert_green_eraser_mask_to_bw_with_original_alpha(
    editor_image: Image.Image,
    original_image: Image.Image,
    alpha_threshold: int = 10,
) -> Image.Image:
    """
    Converts a green/transparent editor mask into a clean black/white mask.
    Original transparent pixels are always black in the final mask.
    """
    editor_image = editor_image.convert("RGBA")
    original_image = original_image.convert("RGBA")

    if editor_image.size != original_image.size:
        editor_image = editor_image.resize(original_image.size, Image.LANCZOS)

    editor = np.array(editor_image).astype(np.int32)
    original_alpha = np.array(original_image.getchannel("A"))

    er = editor[:, :, 0]
    eg = editor[:, :, 1]
    eb = editor[:, :, 2]
    ea = editor[:, :, 3]

    is_green = (
        (ea > 20)
        & (eg > 100)
        & (eg * 4 > er * 5)
        & (eg * 4 > eb * 5)
    )

    inside_furniture = original_alpha > alpha_threshold

    out = np.zeros((*original_alpha.shape, 4), dtype=np.uint8)
    out[:, :, 3] = 255
    white = is_green & inside_furniture
    out[white] = (255, 255, 255, 255)

    return Image.fromarray(out, "RGBA")


# =====================================================================
# Furniture normalization
# =====================================================================


def normalize_furniture_image(
    image: Image.Image,
    canvas_width: int = 1200,
    canvas_height: int = 800,
    padding_percent: float = 8,
) -> Image.Image:
    """
    Places a transparent furniture PNG onto a fixed-size transparent canvas.
    Preserves aspect ratio, centers furniture, and adds padding.
    """
    image = image.convert("RGBA")
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()

    if bbox is None:
        return Image.new("RGBA", (canvas_width, canvas_height), (0, 0, 0, 0))

    cropped = image.crop(bbox)
    crop_width, crop_height = cropped.size

    padding_x = int(canvas_width * (padding_percent / 100))
    padding_y = int(canvas_height * (padding_percent / 100))

    max_width = canvas_width - (padding_x * 2)
    max_height = canvas_height - (padding_y * 2)

    scale = min(max_width / crop_width, max_height / crop_height)

    new_width = max(1, int(crop_width * scale))
    new_height = max(1, int(crop_height * scale))

    resized = cropped.resize((new_width, new_height), Image.LANCZOS)

    canvas = Image.new("RGBA", (canvas_width, canvas_height), (0, 0, 0, 0))

    paste_x = int((canvas_width - new_width) / 2)
    paste_y = int((canvas_height - new_height) / 2)

    canvas.alpha_composite(resized, (paste_x, paste_y))
    return canvas


# =====================================================================
# Repeat detection — FFT autocorrelation
# =====================================================================


def _normalized_autocorrelation(gray: np.ndarray) -> np.ndarray:
    """
    Linear zero-padded autocorrelation of a mean-subtracted grayscale image.
    Result index [dy, dx] = how well the image matches itself shifted by (dx, dy).
    """
    h, w = gray.shape
    g = gray - gray.mean()

    fh, fw = 2 * h, 2 * w
    F = np.fft.rfft2(g, s=(fh, fw))
    ac = np.fft.irfft2(F * np.conj(F), s=(fh, fw))
    ac = ac[:h, :w]

    counts = np.outer(
        np.arange(h, 0, -1, dtype=np.float64),
        np.arange(w, 0, -1, dtype=np.float64),
    )

    var = g.var()
    if var <= 1e-9:
        return np.zeros_like(ac)

    return ac / (counts * var)


def _find_axis_period(
    profile: np.ndarray,
    min_lag: int,
    min_corr: float = 0.22,
    assume_repeat: bool = True,
):
    """
    Given a 1D autocorrelation profile, find the fundamental repeat period.
    Returns (period, confidence) or (None, 0.0).
    """
    n = len(profile)
    max_lag = int(n * 0.72)

    if max_lag <= max(min_lag, 4) + 2:
        return None, 0.0

    prof = np.clip(profile, -1.0, 1.0)
    kernel = np.array([0.25, 0.5, 0.25])
    sm = np.convolve(prof, kernel, mode="same")

    low = max(min_lag, 4)
    candidates = [
        lag
        for lag in range(low, max_lag)
        if sm[lag] >= min_corr and sm[lag] >= sm[lag - 1] and sm[lag] >= sm[lag + 1]
    ]

    if not candidates:
        if assume_repeat:
            search = sm[low:max_lag]
            lag = int(np.argmax(search)) + low
            return lag, float(max(0.0, sm[lag]))
        return None, 0.0

    def harmonic_score(p):
        vals = []
        m = p
        while m < max_lag:
            lo, hi = max(0, m - 2), min(n, m + 3)
            vals.append(sm[lo:hi].max())
            m += p
        return float(np.mean(vals)) if vals else 0.0

    best_p, best_s = None, 0.0
    for p in candidates:
        s = harmonic_score(p)
        # Candidates ascend, so on near-ties the smallest fundamental wins.
        if s > best_s + 0.03:
            best_p, best_s = p, s

    if best_p is None and candidates:
        best_p = candidates[0]
        best_s = harmonic_score(best_p)

    return best_p, best_s


def _edge_mismatch(gray: np.ndarray, left: int, top: int, pw: int, ph: int, strip: int = 4) -> float:
    tile = gray[top:top + ph, left:left + pw]
    s = max(1, min(strip, pw // 6, ph // 6))
    lr = np.mean(np.abs(tile[:, :s] - tile[:, -s:]))
    tb = np.mean(np.abs(tile[:s, :] - tile[-s:, :]))
    return float(lr + tb)


def _wrap_mismatch(gray: np.ndarray, left: int, top: int, pw: int, ph: int) -> float:
    """
    How well the crop matches the source image one period away.
    Uses partial overlap because swatches may show only ~1.5 repeats.
    """
    h, w = gray.shape
    scores = []

    ox = min(pw, w - (left + pw))
    if ox >= max(6, int(pw * 0.12)):
        a = gray[top:top + ph, left:left + ox]
        b = gray[top:top + ph, left + pw:left + pw + ox]
        scores.append(np.mean(np.abs(a - b)))

    oy = min(ph, h - (top + ph))
    if oy >= max(6, int(ph * 0.12)):
        a = gray[top:top + oy, left:left + pw]
        b = gray[top + ph:top + ph + oy, left:left + pw]
        scores.append(np.mean(np.abs(a - b)))

    return float(np.mean(scores)) if scores else 255.0


def find_repeat_cell(
    fabric_image: Image.Image,
    analysis_max_size: int = 512,
    margin_percent: float = 2.0,
    min_period_pct: float = 8.0,
    min_confidence: float = 0.25,
    assume_repeat: bool = True,
):
    """
    Detects the fabric's repeat cell via FFT autocorrelation.

    Returns a dict:
      box         -- (left, top, right, bottom) on the ORIGINAL image
      confidence  -- 0..1 autocorrelation strength of the detected period
      period      -- (period_w, period_h) on the original image
      mode        -- auto_fft | auto_fft_low_confidence | uniform | none
    """
    original = fabric_image.convert("RGB")
    ow, oh = original.size

    mx, my = int(ow * margin_percent / 100), int(oh * margin_percent / 100)
    right_margin = max(mx, 0)
    bottom_margin = max(my, 0)
    if ow - right_margin <= mx or oh - bottom_margin <= my:
        mx, my = 0, 0
        right_margin, bottom_margin = 0, 0

    work = original.crop((mx, my, ow - right_margin, oh - bottom_margin))
    ww, wh = work.size

    scale = min(1.0, analysis_max_size / max(ww, wh))
    aw, ah = max(16, int(ww * scale)), max(16, int(wh * scale))
    small = work.resize((aw, ah), Image.LANCZOS)
    gray_small = np.array(small.convert("L")).astype(np.float64)

    if float(gray_small.std()) < 2.5:
        cw4, ch4 = ww // 4, wh // 4
        box = (mx + cw4, my + ch4, mx + ww - cw4, my + wh - ch4)
        return {
            "box": box,
            "confidence": 1.0,
            "period": (ww - 2 * cw4, wh - 2 * ch4),
            "mode": "uniform",
            "quality_ratio": 0.0,
        }

    ac = _normalized_autocorrelation(gray_small)

    band = 2
    profile_x = ac[0:band + 1, :].max(axis=0)
    profile_y = ac[:, 0:band + 1].max(axis=1)

    min_lag_x = max(4, int(aw * min_period_pct / 100))
    min_lag_y = max(4, int(ah * min_period_pct / 100))

    px, cx = _find_axis_period(profile_x, min_lag_x, assume_repeat=assume_repeat)
    py, cy = _find_axis_period(profile_y, min_lag_y, assume_repeat=assume_repeat)

    if px is None and py is None:
        return {"box": None, "confidence": 0.0, "period": None, "mode": "none", "quality_ratio": None}

    confidence_values = [c for c in (cx, cy) if c > 0]
    confidence = float(np.mean(confidence_values)) if confidence_values else 0.0
    if confidence < min_confidence and not assume_repeat:
        return {"box": None, "confidence": confidence, "period": None, "mode": "none", "quality_ratio": None}

    detection_mode = "auto_fft" if confidence >= min_confidence else "auto_fft_low_confidence"

    px_s = px if px is not None else aw
    py_s = py if py is not None else ah

    gray_raw = np.array(work.convert("L")).astype(np.float64)

    pw0 = int(round(px_s / scale)) if px is not None else ww
    ph0 = int(round(py_s / scale)) if py is not None else wh
    pw0 = max(8, min(pw0, ww))
    ph0 = max(8, min(ph0, wh))

    blur_r = max(31, int(max(pw0, ph0) * 0.75))
    lowpass = np.array(
        Image.fromarray(np.clip(gray_raw, 0, 255).astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(radius=blur_r)
        )
    ).astype(np.float64)
    gray_full = gray_raw - lowpass + lowpass.mean()

    def refine(p0, limit, axis):
        if (axis == "x" and px is None) or (axis == "y" and py is None):
            return p0
        best_p, best_v = p0, float("inf")
        delta = max(2, int(limit * 0.01))
        for p in range(max(8, p0 - delta), min(limit, p0 + delta) + 1):
            w_ = p if axis == "x" else min(pw0, ww)
            h_ = p if axis == "y" else min(ph0, wh)
            if w_ > ww or h_ > wh:
                continue
            v = _wrap_mismatch(gray_full, 0, 0, w_, h_)
            if v < best_v:
                best_v, best_p = v, p
        return best_p

    pw = min(refine(pw0, ww, "x"), ww)
    ph = min(refine(ph0, wh, "y"), wh)

    steps = 12
    best = (0, 0)
    best_v = float("inf")
    if pw < ww:
        x_range = range(0, max(1, min(pw, ww - pw) + 1), max(1, pw // steps))
    else:
        x_range = [0]
    if ph < wh:
        y_range = range(0, max(1, min(ph, wh - ph) + 1), max(1, ph // steps))
    else:
        y_range = [0]

    for top in y_range:
        for left in x_range:
            v = _wrap_mismatch(gray_full, left, top, pw, ph) + 0.5 * _edge_mismatch(gray_full, left, top, pw, ph)
            if v < best_v:
                best_v, best = v, (left, top)

    left, top = best
    box = (left + mx, top + my, left + mx + pw, top + my + ph)

    tile_gray = gray_full[top:top + ph, left:left + pw]
    interior_detail = 0.5 * (
        np.mean(np.abs(np.diff(tile_gray, axis=0))) +
        np.mean(np.abs(np.diff(tile_gray, axis=1)))
    )
    wrap_err = _wrap_mismatch(gray_full, left, top, pw, ph)
    quality_ratio = float(wrap_err / max(interior_detail, 1e-3))

    return {
        "box": box,
        "confidence": round(confidence, 3),
        "period": (pw, ph),
        "mode": detection_mode,
        "quality_ratio": round(quality_ratio, 3),
    }


def flatten_illumination(image: Image.Image, blur_radius: int) -> Image.Image:
    """
    Removes low-frequency lighting gradients so repeated tiles don't carry
    brightness ramps that show up as seams.
    """
    rgb = image.convert("RGB")
    arr = np.array(rgb).astype(np.float64)
    lowpass = np.array(rgb.filter(ImageFilter.GaussianBlur(radius=blur_radius))).astype(np.float64)
    lowpass = np.maximum(lowpass, 1.0)
    mean_per_channel = lowpass.reshape(-1, 3).mean(axis=0)
    corrected = arr / lowpass * mean_per_channel[None, None, :]
    return Image.fromarray(np.clip(corrected, 0, 255).astype(np.uint8))


def extract_seamless_tile(
    original: Image.Image,
    box,
    period,
    flatten: bool = True,
    edge_blend_px: int = None,
) -> Image.Image:
    """
    Crops the repeat cell and makes it production-ready.
    """
    src = original.convert("RGB")
    if flatten and period is not None:
        radius = max(31, int(max(period) * 0.75))
        src = flatten_illumination(src, radius)

    tile = np.array(src.crop(box)).astype(np.float64)
    th, tw, _ = tile.shape
    if edge_blend_px is None:
        edge_blend_px = max(2, int(min(tw, th) * 0.02))
    b = max(0, min(edge_blend_px, tw // 8, th // 8))

    if b > 0:
        orig = tile.copy()
        for i in range(b):
            w = (b - i) / b * 0.5
            tile[:, tw - 1 - i, :] = orig[:, tw - 1 - i, :] * (1 - w) + orig[:, i, :] * w
            tile[:, i, :] = orig[:, i, :] * (1 - w) + orig[:, tw - 1 - i, :] * w

        orig = tile.copy()
        for i in range(b):
            w = (b - i) / b * 0.5
            tile[th - 1 - i, :, :] = orig[th - 1 - i, :, :] * (1 - w) + orig[i, :, :] * w
            tile[i, :, :] = orig[i, :, :] * (1 - w) + orig[th - 1 - i, :, :] * w

    return Image.fromarray(np.clip(tile, 0, 255).astype(np.uint8)).convert("RGBA")


def extract_repeat_tile_manual(
    fabric_image: Image.Image,
    repeat_left_percent: float = 0,
    repeat_top_percent: float = 0,
    repeat_width_percent: float = 33,
    repeat_height_percent: float = 33,
    output_tile_width: int = 800,
    output_tile_height: int = 800,
) -> Image.Image:
    """Manual crop fallback for extracting a repeat cell by percentages."""
    fabric_image = fabric_image.convert("RGBA")
    source_width, source_height = fabric_image.size

    repeat_left_percent = max(0, min(float(repeat_left_percent), 100))
    repeat_top_percent = max(0, min(float(repeat_top_percent), 100))
    repeat_width_percent = max(1, min(float(repeat_width_percent), 100))
    repeat_height_percent = max(1, min(float(repeat_height_percent), 100))

    left = int(source_width * (repeat_left_percent / 100))
    top = int(source_height * (repeat_top_percent / 100))
    crop_width = int(source_width * (repeat_width_percent / 100))
    crop_height = int(source_height * (repeat_height_percent / 100))

    right = min(source_width, left + crop_width)
    bottom = min(source_height, top + crop_height)

    if right <= left or bottom <= top:
        left, top, right, bottom = 0, 0, source_width, source_height

    repeat_tile = fabric_image.crop((left, top, right, bottom))
    repeat_tile = repeat_tile.resize((int(output_tile_width), int(output_tile_height)), Image.LANCZOS)
    return repeat_tile


def build_repeat_preview(tile_image: Image.Image, cols: int = 3, rows: int = 3) -> Image.Image:
    tile_image = tile_image.convert("RGBA")
    tw, th = tile_image.size
    preview = Image.new("RGBA", (tw * cols, th * rows), (255, 255, 255, 255))

    for row in range(rows):
        for col in range(cols):
            preview.alpha_composite(tile_image, (col * tw, row * th))

    return preview


# =====================================================================
# Legacy fabric tile endpoint helpers
# =====================================================================


def crop_to_aspect_ratio(image: Image.Image, target_width: int, target_height: int) -> Image.Image:
    image = image.convert("RGBA")
    source_width, source_height = image.size
    target_ratio = target_width / target_height
    source_ratio = source_width / source_height

    if source_ratio > target_ratio:
        new_width = int(source_height * target_ratio)
        left = int((source_width - new_width) / 2)
        box = (left, 0, left + new_width, source_height)
    else:
        new_height = int(source_width / target_ratio)
        top = int((source_height - new_height) / 2)
        box = (0, top, source_width, top + new_height)

    return image.crop(box)


def repair_center_seams(
    tile: Image.Image,
    seam_percent: float = 8,
    blur_radius: float = 6,
) -> Image.Image:
    """Legacy helper for /prepare-fabric-tile."""
    tile = tile.convert("RGBA")
    width, height = tile.size

    seam_w = max(2, int(width * (seam_percent / 100)))
    seam_h = max(2, int(height * (seam_percent / 100)))

    blurred = tile.filter(ImageFilter.GaussianBlur(radius=blur_radius))

    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)

    center_x = width // 2
    center_y = height // 2

    draw.rectangle((center_x - seam_w // 2, 0, center_x + seam_w // 2, height), fill=180)
    draw.rectangle((0, center_y - seam_h // 2, width, center_y + seam_h // 2), fill=180)

    mask = mask.filter(ImageFilter.GaussianBlur(radius=max(2, int(seam_w * 0.4))))
    repaired = Image.composite(blurred, tile, mask)
    return repaired


def prepare_fabric_tile_image(
    fabric_image: Image.Image,
    tile_width: int = 800,
    tile_height: int = 800,
    seam_percent: float = 8,
    blur_radius: float = 6,
) -> Image.Image:
    """
    Legacy fabric tile prep endpoint. Kept for backwards compatibility.
    Prefer /prepare-repeat-tile for the new workflow.
    """
    fabric_image = fabric_image.convert("RGBA")
    cropped = crop_to_aspect_ratio(fabric_image, tile_width, tile_height)
    tile = cropped.resize((tile_width, tile_height), Image.LANCZOS)
    offset_tile = ImageChops.offset(tile, tile_width // 2, tile_height // 2)

    repaired = repair_center_seams(
        offset_tile,
        seam_percent=seam_percent,
        blur_radius=blur_radius,
    )

    rgb = repaired.convert("RGB")
    rgb = ImageEnhance.Contrast(rgb).enhance(1.03)
    return rgb.convert("RGBA")


# =====================================================================
# Fabric tiling and upholstery rendering
# =====================================================================


def tile_fabric_to_size(
    fabric_image: Image.Image,
    target_size,
    pattern_scale_percent: float = 20,
    pattern_offset_x: float = 0,
    pattern_offset_y: float = 0,
) -> Image.Image:
    """
    Repeats the prepared Repeat Tile across the target canvas.

    No mirroring. No blending. No overlap.
    This assumes fabric_image is already the repeat cell / repeat_tile_url.
    """
    fabric_image = fabric_image.convert("RGBA")
    target_width, target_height = target_size

    try:
        pattern_scale_percent = float(pattern_scale_percent)
    except Exception:
        pattern_scale_percent = 20

    try:
        pattern_offset_x = int(float(pattern_offset_x))
    except Exception:
        pattern_offset_x = 0

    try:
        pattern_offset_y = int(float(pattern_offset_y))
    except Exception:
        pattern_offset_y = 0

    pattern_scale_percent = max(2, min(pattern_scale_percent, 200))

    tile_width = int(target_width * (pattern_scale_percent / 100))
    tile_width = max(10, tile_width)

    aspect_ratio = fabric_image.height / fabric_image.width
    tile_height = int(tile_width * aspect_ratio)
    tile_height = max(10, tile_height)

    fabric_tile = fabric_image.resize((tile_width, tile_height), Image.LANCZOS)
    tiled = Image.new("RGBA", target_size, (0, 0, 0, 0))

    start_x = pattern_offset_x % tile_width - tile_width
    start_y = pattern_offset_y % tile_height - tile_height

    y = start_y
    while y < target_height:
        x = start_x
        while x < target_width:
            tiled.alpha_composite(fabric_tile, (x, y))
            x += tile_width
        y += tile_height

    return tiled


def segment_mask_into_panels(
    furniture_image: Image.Image,
    mask_image: Image.Image,
    edge_threshold: int = 26,
    min_panel_area_percent: float = 1.0,
) -> np.ndarray:
    """
    Splits the upholstery mask into fabric panels using the furniture's seam lines.
    Returns an int label array, 0 = outside mask, 1..N = panel id.
    """
    furniture_image = furniture_image.convert("RGBA")
    mask_image = mask_image.convert("L")

    if mask_image.size != furniture_image.size:
        mask_image = mask_image.resize(furniture_image.size, Image.LANCZOS)

    mask_np = np.array(mask_image) > 40
    if not mask_np.any():
        return np.zeros(mask_np.shape, dtype=np.int32)

    gray = ImageOps.grayscale(furniture_image)
    gray = ImageEnhance.Contrast(gray).enhance(1.6)
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edges = ImageEnhance.Contrast(edges).enhance(4.0)
    edges_np = np.array(edges) > edge_threshold
    edges_np = ndimage.binary_dilation(edges_np, iterations=2)

    interior = mask_np & ~edges_np

    h, w = mask_np.shape
    erode_iters = max(2, int(min(w, h) * 0.008))
    cores = ndimage.binary_erosion(interior, iterations=erode_iters)
    labels, count = ndimage.label(cores)

    if count == 0:
        return mask_np.astype(np.int32)

    min_area = mask_np.sum() * (min_panel_area_percent / 100.0)
    sizes = ndimage.sum(cores, labels, range(1, count + 1))
    for i, size in enumerate(sizes, start=1):
        if size < min_area:
            labels[labels == i] = 0

    if not (labels > 0).any():
        return mask_np.astype(np.int32)

    _, (iy, ix) = ndimage.distance_transform_edt(labels == 0, return_indices=True)
    filled = labels[iy, ix]
    filled[~mask_np] = 0

    unique = [u for u in np.unique(filled) if u != 0]
    out = np.zeros_like(filled)
    for new_id, old_id in enumerate(unique, start=1):
        out[filled == old_id] = new_id

    return out.astype(np.int32)


def build_paneled_fabric(
    fabric_image: Image.Image,
    panel_labels: np.ndarray,
    target_size,
    pattern_scale_percent: float = 20,
    pattern_offset_x: float = 0,
    pattern_offset_y: float = 0,
) -> Image.Image:
    """
    Tiles the repeat tile separately for each panel, like individual fabric cuts.
    """
    target_width, target_height = target_size
    result = np.zeros((target_height, target_width, 4), dtype=np.uint8)

    panel_ids = [p for p in np.unique(panel_labels) if p != 0]
    if not panel_ids:
        return tile_fabric_to_size(
            fabric_image,
            target_size,
            pattern_scale_percent,
            pattern_offset_x,
            pattern_offset_y,
        )

    for pid in panel_ids:
        panel = panel_labels == pid
        ys, xs = np.where(panel)
        top, left = int(ys.min()), int(xs.min())

        tiled = tile_fabric_to_size(
            fabric_image=fabric_image,
            target_size=target_size,
            pattern_scale_percent=pattern_scale_percent,
            pattern_offset_x=float(pattern_offset_x) + left,
            pattern_offset_y=float(pattern_offset_y) + top,
        )
        tiled_np = np.array(tiled)
        result[panel] = tiled_np[panel]

    return Image.fromarray(result, "RGBA")


def panel_boundary_mask(panel_labels: np.ndarray) -> np.ndarray:
    """
    Float 0..1 map of borders between different panels, softened.
    """
    boundary = np.zeros(panel_labels.shape, dtype=bool)

    diff_x = panel_labels[:, 1:] != panel_labels[:, :-1]
    both_x = (panel_labels[:, 1:] > 0) & (panel_labels[:, :-1] > 0)
    boundary[:, 1:] |= diff_x & both_x

    diff_y = panel_labels[1:, :] != panel_labels[:-1, :]
    both_y = (panel_labels[1:, :] > 0) & (panel_labels[:-1, :] > 0)
    boundary[1:, :] |= diff_y & both_y

    soft = Image.fromarray((boundary * 255).astype(np.uint8), "L")
    soft = soft.filter(ImageFilter.MaxFilter(3))
    soft = soft.filter(ImageFilter.GaussianBlur(radius=0.8))
    return np.array(soft).astype(np.float32) / 255.0


def warp_fabric_to_form(
    tiled_fabric: Image.Image,
    furniture_image: Image.Image,
    mask_image: Image.Image,
    warp_strength: float = 0.04,
) -> Image.Image:
    """
    Approximate 2D warp so repeated fabric bends around rounded forms.
    """
    tiled_fabric = tiled_fabric.convert("RGBA")
    furniture_image = furniture_image.convert("RGBA")
    mask_image = mask_image.convert("L")

    width, height = furniture_image.size

    if tiled_fabric.size != furniture_image.size:
        tiled_fabric = tiled_fabric.resize(furniture_image.size, Image.LANCZOS)
    if mask_image.size != furniture_image.size:
        mask_image = mask_image.resize(furniture_image.size, Image.LANCZOS)

    warp_strength = max(0.0, min(float(warp_strength), 0.45))

    smooth_mask = mask_image.filter(ImageFilter.GaussianBlur(radius=6))
    mask_np = np.array(smooth_mask).astype(np.float32) / 255.0

    if np.max(mask_np) <= 0.01:
        return tiled_fabric

    mask_pixels = mask_np > 0.05
    ys, xs = np.where(mask_pixels)
    if len(xs) == 0 or len(ys) == 0:
        return tiled_fabric

    left = float(xs.min())
    right = float(xs.max())
    top = float(ys.min())
    bottom = float(ys.max())

    box_w = max(1.0, right - left)
    box_h = max(1.0, bottom - top)

    y_grid, x_grid = np.meshgrid(
        np.arange(height, dtype=np.float32),
        np.arange(width, dtype=np.float32),
        indexing="ij",
    )

    u = np.clip((x_grid - left) / box_w, 0.0, 1.0)
    v = np.clip((y_grid - top) / box_h, 0.0, 1.0)
    center_x = left + box_w * 0.5

    side_amount = (np.abs(u - 0.5) * 2.0) ** 1.7
    side_amount = side_amount * (np.clip(np.sin(np.pi * v), 0.0, None) ** 0.8)

    bottom_roll = np.exp(-((v - 0.88) ** 2) / 0.006)
    bottom_roll = bottom_roll * np.sin(np.pi * u)

    center_bend = np.exp(-((v - 0.48) ** 2) / 0.018)
    center_bend = center_bend * np.sin(np.pi * u)

    seat_lip = np.exp(-((v - 0.58) ** 2) / 0.0045)
    seat_lip = seat_lip * (np.clip(np.sin(np.pi * u), 0.0, None) ** 1.6)

    gray = furniture_image.convert("L").filter(ImageFilter.GaussianBlur(radius=7))
    light_np = np.array(gray).astype(np.float32) / 255.0
    grad_y, grad_x = np.gradient(light_np)

    dx_side = (x_grid - center_x) * side_amount * warp_strength * 0.75
    dx_light = -grad_x * width * warp_strength * 22.0
    dy_light = -grad_y * height * warp_strength * 18.0
    dy_roll = bottom_roll * height * warp_strength * 0.28
    dy_center = -center_bend * height * warp_strength * 0.10
    dy_seat_lip = seat_lip * height * warp_strength * 0.04

    dx = (dx_side + dx_light) * mask_np
    dy = (dy_light + dy_roll + dy_center + dy_seat_lip) * mask_np

    source_x = np.nan_to_num(x_grid + dx, nan=0.0, posinf=width - 1, neginf=0.0)
    source_y = np.nan_to_num(y_grid + dy, nan=0.0, posinf=height - 1, neginf=0.0)
    source_x = np.clip(source_x, 0, width - 1)
    source_y = np.clip(source_y, 0, height - 1)

    x0 = np.floor(source_x).astype(np.int32)
    y0 = np.floor(source_y).astype(np.int32)
    x0 = np.clip(x0, 0, width - 1)
    y0 = np.clip(y0, 0, height - 1)
    x1 = np.clip(x0 + 1, 0, width - 1)
    y1 = np.clip(y0 + 1, 0, height - 1)

    wx = source_x - x0
    wy = source_y - y0

    src = np.array(tiled_fabric).astype(np.float32)
    top_left = src[y0, x0]
    top_right = src[y0, x1]
    bottom_left = src[y1, x0]
    bottom_right = src[y1, x1]

    top_mix = top_left * (1.0 - wx[..., None]) + top_right * wx[..., None]
    bottom_mix = bottom_left * (1.0 - wx[..., None]) + bottom_right * wx[..., None]
    warped = top_mix * (1.0 - wy[..., None]) + bottom_mix * wy[..., None]
    warped = np.clip(warped, 0, 255).astype(np.uint8)

    return Image.fromarray(warped, "RGBA")


def apply_fabric_to_furniture(
    furniture_image: Image.Image,
    fabric_image: Image.Image,
    mask_image: Image.Image,
    pattern_scale_percent: float = 20,
    pattern_offset_x: float = 0,
    pattern_offset_y: float = 0,
    shading_strength: float = 0.32,
    highlight_strength: float = 0.18,
    detail_strength: float = 0.28,
    fabric_opacity: float = 0.88,
    separate_panels: bool = True,
    panel_edge_threshold: int = 26,
    min_panel_area_percent: float = 1.0,
    panel_seam_darkness: float = 0.35,
):
    """
    Applies a prepared fabric Repeat Tile onto masked upholstery areas
    while preserving furniture depth, highlights, and detail.

    Returns (rendered_image, panels_detected).
    """
    furniture_image = furniture_image.convert("RGBA")
    fabric_image = fabric_image.convert("RGBA")
    mask_image = mask_image.convert("L")

    if mask_image.size != furniture_image.size:
        mask_image = mask_image.resize(furniture_image.size, Image.LANCZOS)

    original_alpha = furniture_image.getchannel("A")
    mask_image = ImageChops.multiply(mask_image, original_alpha)
    feathered_mask = mask_image.filter(ImageFilter.GaussianBlur(radius=1.0))

    panel_labels = None
    panels_detected = 1

    if separate_panels:
        panel_labels = segment_mask_into_panels(
            furniture_image=furniture_image,
            mask_image=mask_image,
            edge_threshold=int(panel_edge_threshold),
            min_panel_area_percent=float(min_panel_area_percent),
        )
        panels_detected = int(panel_labels.max())

    if panel_labels is not None and panels_detected > 1:
        tiled_fabric = build_paneled_fabric(
            fabric_image=fabric_image,
            panel_labels=panel_labels,
            target_size=furniture_image.size,
            pattern_scale_percent=pattern_scale_percent,
            pattern_offset_x=pattern_offset_x,
            pattern_offset_y=pattern_offset_y,
        ).convert("RGBA")
    else:
        tiled_fabric = tile_fabric_to_size(
            fabric_image=fabric_image,
            target_size=furniture_image.size,
            pattern_scale_percent=pattern_scale_percent,
            pattern_offset_x=pattern_offset_x,
            pattern_offset_y=pattern_offset_y,
        ).convert("RGBA")

    warped_fabric = warp_fabric_to_form(
        tiled_fabric=tiled_fabric,
        furniture_image=furniture_image,
        mask_image=mask_image,
        warp_strength=0.035,
    )

    shading_strength = max(0.0, min(float(shading_strength), 1.5))
    highlight_strength = max(0.0, min(float(highlight_strength), 1.0))
    detail_strength = max(0.0, min(float(detail_strength), 1.0))
    fabric_opacity = max(0.0, min(float(fabric_opacity), 1.0))

    furniture_rgb = np.array(furniture_image.convert("RGB")).astype(np.float32) / 255.0
    fabric_rgb = np.array(warped_fabric.convert("RGB")).astype(np.float32) / 255.0
    mask_np = np.array(feathered_mask).astype(np.float32) / 255.0

    gray = furniture_image.convert("L")
    broad_light = gray.filter(ImageFilter.GaussianBlur(radius=8))
    fine_light = gray.filter(ImageFilter.GaussianBlur(radius=1.2))

    broad_np = np.array(broad_light).astype(np.float32) / 255.0
    fine_np = np.array(fine_light).astype(np.float32) / 255.0

    valid = mask_np > 0.05
    light_mid = float(np.mean(broad_np[valid])) if np.any(valid) else 0.5

    form = (broad_np - light_mid) * 2.0
    form_multiplier = 1.0 + (form * shading_strength)
    form_multiplier = np.clip(form_multiplier, 0.45, 1.45)

    highlights = np.maximum(0.0, broad_np - light_mid) * highlight_strength
    detail = (fine_np - broad_np) * detail_strength * 2.0

    rendered_rgb = fabric_rgb * form_multiplier[..., None]
    rendered_rgb = rendered_rgb + highlights[..., None]
    rendered_rgb = rendered_rgb + detail[..., None]
    rendered_rgb = np.clip(rendered_rgb, 0.0, 1.0)

    rendered_rgb = rendered_rgb * fabric_opacity + furniture_rgb * (1.0 - fabric_opacity)
    rendered_rgb = np.clip(rendered_rgb, 0.0, 1.0)

    if panel_labels is not None and panels_detected > 1:
        panel_seam_darkness = max(0.0, min(float(panel_seam_darkness), 1.0))
        if panel_seam_darkness > 0:
            boundary = panel_boundary_mask(panel_labels)
            rendered_rgb = rendered_rgb * (1.0 - (boundary * panel_seam_darkness)[..., None])
            rendered_rgb = np.clip(rendered_rgb, 0.0, 1.0)

    output_rgb = furniture_rgb * (1.0 - mask_np[..., None]) + rendered_rgb * mask_np[..., None]
    output_arr = (np.clip(output_rgb, 0.0, 1.0) * 255).astype(np.uint8)

    output = Image.fromarray(output_arr, "RGB").convert("RGBA")
    output.putalpha(original_alpha)
    return output, panels_detected

# ============================================================
# ROOM OBJECT DETECTION CONFIGURATION
# Grounding DINO finds objects.
# SAM 2 creates precise masks around those objects.
# ============================================================

GROUNDING_DINO_MODEL_ID = os.getenv(
    "GROUNDING_DINO_MODEL_ID",
    "IDEA-Research/grounding-dino-tiny",
)

SAM2_MODEL_ID = os.getenv(
    "SAM2_MODEL_ID",
    "facebook/sam2-hiera-tiny",
)

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
MODEL_DTYPE = torch.float16 if DEVICE == "cuda" else torch.float32
MODEL_INFERENCE_LOCK = Lock()

DEFAULT_ROOM_CATEGORIES = [
    "sofa",
    "sectional sofa",
    "loveseat",
    "chair",
    "armchair",
    "accent chair",
    "dining chair",
    "office chair",
    "stool",
    "bench",
    "ottoman",
    "coffee table",
    "side table",
    "end table",
    "console table",
    "dining table",
    "desk",
    "bed",
    "headboard",
    "nightstand",
    "dresser",
    "wardrobe",
    "cabinet",
    "bookshelf",
    "bookcase",
    "television",
    "floor lamp",
    "table lamp",
    "pendant light",
    "chandelier",
    "ceiling fan",
    "rug",
    "plant",
    "wall art",
    "mirror",
    "curtain",
]


def configure_room_detection_cloudinary() -> None:
    """
    Configure Cloudinary from Hugging Face Space secrets.

    This can safely run even if Cloudinary was configured elsewhere
    in the application.
    """
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
    api_key = os.getenv("CLOUDINARY_API_KEY")
    api_secret = os.getenv("CLOUDINARY_API_SECRET")

    if not all([cloud_name, api_key, api_secret]):
        print(
            "WARNING: Cloudinary room-detection secrets are missing. "
            "The API will load, but mask upload will fail."
        )
        return

    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True,
    )


configure_room_detection_cloudinary()


print(f"Loading room detection models on {DEVICE}...", flush=True)


grounding_dino_processor = AutoProcessor.from_pretrained(
    GROUNDING_DINO_MODEL_ID
)

grounding_dino_model = (
    AutoModelForZeroShotObjectDetection.from_pretrained(
        GROUNDING_DINO_MODEL_ID,
        torch_dtype=MODEL_DTYPE,
    )
    .to(DEVICE)
    .eval()
)


sam2_processor = Sam2Processor.from_pretrained(SAM2_MODEL_ID)

sam2_model = (
    Sam2Model.from_pretrained(
        SAM2_MODEL_ID,
        torch_dtype=MODEL_DTYPE,
    )
    .to(DEVICE)
    .eval()
)


print("Room detection models loaded successfully.", flush=True)

# ============================================================
# REQUEST MODEL
# ============================================================

class DetectRoomObjectsRequest(BaseModel):
    image_url: str

    categories: list[str] = Field(
        default_factory=lambda: DEFAULT_ROOM_CATEGORIES.copy()
    )

    box_threshold: float = Field(default=0.30, ge=0.05, le=0.95)
    text_threshold: float = Field(default=0.25, ge=0.05, le=0.95)

    # Pixels added around the SAM mask.
    mask_padding: int = Field(default=8, ge=0, le=30)

    # Remove duplicate boxes for the same category.
    nms_threshold: float = Field(default=0.55, ge=0.10, le=0.95)

    # Prevent excessive processing in a single request.
    max_detections: int = Field(default=30, ge=1, le=75)

    @field_validator("image_url")
    @classmethod
    def validate_image_url(cls, value: str) -> str:
        value = value.strip()

        if not value.startswith(("https://", "http://")):
            raise ValueError(
                "image_url must begin with https:// or http://"
            )

        return value

    @field_validator("categories")
    @classmethod
    def validate_categories(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()

        for value in values:
            category = value.strip().lower()

            if not category:
                continue

            if category not in seen:
                cleaned.append(category)
                seen.add(category)

        if not cleaned:
            raise ValueError(
                "At least one valid detection category is required."
            )

        if len(cleaned) > 75:
            raise ValueError(
                "A maximum of 75 categories may be submitted."
            )

        return cleaned


# ============================================================
# GENERAL HELPERS
# ============================================================

def move_inputs_to_model(
    inputs: Any,
    device: str,
    floating_dtype: torch.dtype,
) -> Any:
    """
    Move processor tensors to the model device.

    Floating tensors are converted to float16 on GPU and float32
    on CPU. Integer input IDs remain integers.
    """
    for key, value in inputs.items():
        if not isinstance(value, torch.Tensor):
            continue

        if torch.is_floating_point(value):
            inputs[key] = value.to(
                device=device,
                dtype=floating_dtype,
            )
        else:
            inputs[key] = value.to(device=device)

    return inputs


def download_room_image(image_url: str) -> Image.Image:
    """
    Download an image, correct phone-camera EXIF rotation,
    and return an RGB PIL image.
    """
    try:
        response = requests.get(
            image_url,
            timeout=30,
            stream=True,
            headers={
                "User-Agent": "InteriorDesignRoomEditor/1.0"
            },
        )
        response.raise_for_status()

        content_type = response.headers.get(
            "content-type",
            "",
        ).lower()

        if content_type and not content_type.startswith("image/"):
            raise ValueError(
                f"URL did not return an image. "
                f"Content-Type: {content_type}"
            )

        image_bytes = response.content

        if len(image_bytes) > 30 * 1024 * 1024:
            raise ValueError(
                "Room image is larger than the 30 MB limit."
            )

        image = Image.open(io.BytesIO(image_bytes))
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")

        if image.width < 100 or image.height < 100:
            raise ValueError(
                "Room image is too small for object detection."
            )

        return image

    except requests.RequestException as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Unable to download room image: {exc}",
        ) from exc

    except (ValueError, OSError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid room image: {exc}",
        ) from exc


def safe_label_slug(label: str) -> str:
    """
    Convert labels such as 'coffee table' into 'coffee_table'.
    """
    slug = re.sub(
        r"[^a-z0-9]+",
        "_",
        label.lower(),
    ).strip("_")

    return slug or "object"


def clean_detected_label(label: Any) -> str:
    """
    Convert the model's returned label into clean display text.
    """
    if isinstance(label, (list, tuple)):
        label = label[0] if label else "object"

    text = str(label).strip().lower()

    # Remove occasional articles returned by the detector.
    for article in ("a ", "an ", "the "):
        if text.startswith(article):
            text = text[len(article):]

    return text.strip(" .") or "object"


def clamp_box(
    box: list[float],
    image_width: int,
    image_height: int,
) -> list[float]:
    """
    Keep bounding-box coordinates inside the image.
    """
    x1, y1, x2, y2 = box

    x1 = max(0.0, min(float(image_width - 1), float(x1)))
    y1 = max(0.0, min(float(image_height - 1), float(y1)))
    x2 = max(x1 + 1.0, min(float(image_width), float(x2)))
    y2 = max(y1 + 1.0, min(float(image_height), float(y2)))

    return [x1, y1, x2, y2]


def torch_nms(boxes: torch.Tensor, scores: torch.Tensor, iou_threshold: float) -> torch.Tensor:
    """Pure-PyTorch NMS avoids torchvision binary/operator version failures."""
    if boxes.numel() == 0:
        return torch.empty((0,), dtype=torch.long, device=boxes.device)

    boxes = boxes.float()
    scores = scores.float()
    x1, y1, x2, y2 = boxes.unbind(dim=1)
    areas = (x2 - x1).clamp(min=0) * (y2 - y1).clamp(min=0)
    order = scores.argsort(descending=True)
    keep: list[int] = []

    while order.numel() > 0:
        i = int(order[0].item())
        keep.append(i)
        if order.numel() == 1:
            break

        rest = order[1:]
        xx1 = torch.maximum(x1[i], x1[rest])
        yy1 = torch.maximum(y1[i], y1[rest])
        xx2 = torch.minimum(x2[i], x2[rest])
        yy2 = torch.minimum(y2[i], y2[rest])
        inter = (xx2 - xx1).clamp(min=0) * (yy2 - yy1).clamp(min=0)
        union = areas[i] + areas[rest] - inter
        iou = torch.where(union > 0, inter / union, torch.zeros_like(inter))
        order = rest[iou <= iou_threshold]

    return torch.tensor(keep, dtype=torch.long, device=boxes.device)


def remove_duplicate_detections(
    boxes: torch.Tensor,
    scores: torch.Tensor,
    labels: list[str],
    iou_threshold: float,
) -> tuple[torch.Tensor, torch.Tensor, list[str]]:
    """
    Apply non-maximum suppression separately for each label.

    This removes duplicate 'chair' boxes without accidentally
    deleting a table that overlaps a chair.
    """
    if boxes.numel() == 0:
        return boxes, scores, labels

    grouped_indices: dict[str, list[int]] = defaultdict(list)

    for index, label in enumerate(labels):
        grouped_indices[label].append(index)

    kept_indices: list[int] = []

    for _, indices in grouped_indices.items():
        index_tensor = torch.tensor(
            indices,
            dtype=torch.long,
        )

        label_boxes = boxes[index_tensor]
        label_scores = scores[index_tensor]

        kept_for_label = torch_nms(
            label_boxes,
            label_scores,
            iou_threshold,
        )

        kept_indices.extend(
            index_tensor[kept_for_label].tolist()
        )

    kept_indices.sort(
        key=lambda index: float(scores[index]),
        reverse=True,
    )

    final_indices = torch.tensor(
        kept_indices,
        dtype=torch.long,
    )

    return (
        boxes[final_indices],
        scores[final_indices],
        [labels[index] for index in kept_indices],
    )


def expand_binary_mask(
    mask: np.ndarray,
    padding_pixels: int,
) -> np.ndarray:
    """
    Expand a white object mask so thin edges, feet, and nearby
    shadows are less likely to remain after removal.
    """
    binary = np.where(mask > 0, 255, 0).astype(np.uint8)

    if padding_pixels <= 0:
        return binary

    # PIL MaxFilter performs morphological dilation.
    kernel_size = (padding_pixels * 2) + 1
    kernel_size = min(kernel_size, 61)

    mask_image = Image.fromarray(
        binary,
        mode="L",
    )

    expanded = mask_image.filter(
        ImageFilter.MaxFilter(kernel_size)
    )

    return np.array(expanded, dtype=np.uint8)


def upload_room_mask(
    mask: np.ndarray,
    detection_id: str,
) -> str:
    """
    Upload the full-resolution black-and-white mask to Cloudinary.

    White = selected object
    Black = protected background
    """
    if not all(
        [
            os.getenv("CLOUDINARY_CLOUD_NAME"),
            os.getenv("CLOUDINARY_API_KEY"),
            os.getenv("CLOUDINARY_API_SECRET"),
        ]
    ):
        raise HTTPException(
            status_code=500,
            detail=(
                "Cloudinary secrets are missing. Add "
                "CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, "
                "and CLOUDINARY_API_SECRET in Space settings."
            ),
        )

    mask_image = Image.fromarray(
        mask.astype(np.uint8),
        mode="L",
    )

    buffer = io.BytesIO()
    mask_image.save(
        buffer,
        format="PNG",
        optimize=True,
    )
    buffer.seek(0)

    public_id = (
        f"{safe_label_slug(detection_id)}_"
        f"{uuid.uuid4().hex[:12]}"
    )

    try:
        result = cloudinary.uploader.upload(
            buffer,
            folder="room_editor/detection_masks",
            public_id=public_id,
            resource_type="image",
            format="png",
            overwrite=False,
        )

        secure_url = result.get("secure_url")

        if not secure_url:
            raise RuntimeError(
                "Cloudinary did not return secure_url."
            )

        return secure_url

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Unable to upload detection mask: {exc}",
        ) from exc


# =====================================================================
# Seam overlay request model
# =====================================================================


class SeamOverlayRequest(BaseModel):
    furniture_image_url: str
    mask_image_url: str
    edge_strength: float = 0.35
    opacity: float = 0.45


# =====================================================================
# Endpoints
# =====================================================================

# ============================================================
# DETECT ROOM OBJECTS
# ============================================================

@app.post("/detect-room-objects")
def detect_room_objects(
    request: DetectRoomObjectsRequest,
) -> dict[str, Any]:
    """
    Detect furniture and room objects with Grounding DINO,
    trace each object with SAM 2, upload masks to Cloudinary,
    and return normalized positioning data for Bubble.
    """
    try:
        room_image = download_room_image(request.image_url)

        image_width, image_height = room_image.size

        categories = request.categories

        # Grounding DINO accepts category labels as text prompts.
        # The nested list represents one image with many labels.
        text_labels = [categories]

        dino_inputs = grounding_dino_processor(
            images=room_image,
            text=text_labels,
            return_tensors="pt",
        )

        dino_input_ids = dino_inputs["input_ids"].clone()

        dino_inputs = move_inputs_to_model(
            dino_inputs,
            DEVICE,
            MODEL_DTYPE,
        )

        with MODEL_INFERENCE_LOCK, torch.inference_mode():
            if DEVICE == "cuda":
                with torch.autocast(device_type="cuda", dtype=MODEL_DTYPE):
                    dino_outputs = grounding_dino_model(**dino_inputs)
            else:
                dino_outputs = grounding_dino_model(**dino_inputs)

        dino_results = (
            grounding_dino_processor
            .post_process_grounded_object_detection(
                dino_outputs,
                dino_input_ids.to(DEVICE),
                threshold=request.box_threshold,
                text_threshold=request.text_threshold,
                target_sizes=[
                    (image_height, image_width)
                ],
            )
        )

        if not dino_results:
            return {
                "success": True,
                "message": "No room objects were detected.",
                "image_width": image_width,
                "image_height": image_height,
                "device": DEVICE,
                "detection_count": 0,
                "detections": [],
            }

        result = dino_results[0]

        raw_boxes = result["boxes"].detach().cpu()
        raw_scores = result["scores"].detach().cpu()

        raw_labels = [
            clean_detected_label(label)
            for label in result["labels"]
        ]

        if raw_boxes.numel() == 0:
            return {
                "success": True,
                "message": "No room objects were detected.",
                "image_width": image_width,
                "image_height": image_height,
                "device": DEVICE,
                "detection_count": 0,
                "detections": [],
            }

        # Clamp every box inside the room image.
        clamped_boxes = torch.tensor(
            [
                clamp_box(
                    box.tolist(),
                    image_width,
                    image_height,
                )
                for box in raw_boxes
            ],
            dtype=torch.float32,
        )

        boxes, scores, labels = remove_duplicate_detections(
            boxes=clamped_boxes,
            scores=raw_scores.float(),
            labels=raw_labels,
            iou_threshold=request.nms_threshold,
        )

        # Keep the most confident detections.
        boxes = boxes[: request.max_detections]
        scores = scores[: request.max_detections]
        labels = labels[: request.max_detections]

        if boxes.numel() == 0:
            return {
                "success": True,
                "message": "No room objects remained after filtering.",
                "image_width": image_width,
                "image_height": image_height,
                "device": DEVICE,
                "detection_count": 0,
                "detections": [],
            }

        # SAM 2 expects:
        # [
        #   [
        #     [x1, y1, x2, y2],
        #     [x1, y1, x2, y2]
        #   ]
        # ]
        sam_boxes = [
            [
                [float(value) for value in box.tolist()]
                for box in boxes
            ]
        ]

        sam_inputs = sam2_processor(
            images=room_image,
            input_boxes=sam_boxes,
            return_tensors="pt",
        )

        # Keep original sizes on CPU for mask post-processing.
        original_sizes = (
            sam_inputs["original_sizes"]
            .detach()
            .cpu()
        )

        sam_inputs = move_inputs_to_model(
            sam_inputs,
            DEVICE,
            MODEL_DTYPE,
        )

        with MODEL_INFERENCE_LOCK, torch.inference_mode():
            if DEVICE == "cuda":
                with torch.autocast(device_type="cuda", dtype=MODEL_DTYPE):
                    sam_outputs = sam2_model(
                        **sam_inputs,
                        multimask_output=False,
                    )
            else:
                sam_outputs = sam2_model(
                    **sam_inputs,
                    multimask_output=False,
                )

        processed_masks = sam2_processor.post_process_masks(
            sam_outputs.pred_masks.detach().cpu(),
            original_sizes,
        )[0]

        # Expected shape when multimask_output=False:
        # [number_of_objects, 1, image_height, image_width]
        detections: list[dict[str, Any]] = []
        label_counts: dict[str, int] = defaultdict(int)

        for index in range(len(labels)):
            label = labels[index]
            confidence = float(scores[index].item())

            label_counts[label] += 1

            detection_id = (
                f"{safe_label_slug(label)}_"
                f"{label_counts[label]}"
            )

            box = boxes[index].tolist()
            x1, y1, x2, y2 = clamp_box(
                box,
                image_width,
                image_height,
            )

            object_masks = processed_masks[index]

            # With multimask_output=False, select the only mask.
            if object_masks.ndim == 3:
                object_mask = object_masks[0]
            else:
                object_mask = object_masks

            object_mask = object_mask.numpy()

            # SAM outputs mask probabilities/logits depending on
            # model version. A threshold of 0 works for logits;
            # 0.5 works for probabilities.
            if object_mask.min() < 0:
                binary_mask = object_mask > 0
            else:
                binary_mask = object_mask > 0.5

            expanded_mask = expand_binary_mask(
                binary_mask.astype(np.uint8) * 255,
                request.mask_padding,
            )

            # Skip unusably tiny masks.
            mask_pixel_count = int(
                np.count_nonzero(expanded_mask)
            )

            if mask_pixel_count < 25:
                continue

            mask_url = upload_room_mask(
                expanded_mask,
                detection_id,
            )

            box_width = x2 - x1
            box_height = y2 - y1

            detections.append(
                {
                    "detection_id": detection_id,
                    "label": label,
                    "confidence": round(confidence, 4),

                    # Pixel coordinates
                    "pixel_x": round(x1, 2),
                    "pixel_y": round(y1, 2),
                    "pixel_width": round(box_width, 2),
                    "pixel_height": round(box_height, 2),
                    "pixel_x2": round(x2, 2),
                    "pixel_y2": round(y2, 2),

                    # Normalized coordinates for responsive Bubble
                    # positioning on desktop, tablet, and mobile.
                    "x": round(x1 / image_width, 6),
                    "y": round(y1 / image_height, 6),
                    "width": round(
                        box_width / image_width,
                        6,
                    ),
                    "height": round(
                        box_height / image_height,
                        6,
                    ),

                    "mask_url": mask_url,
                    "mask_pixel_count": mask_pixel_count,
                }
            )

        return {
            "success": True,
            "message": (
                f"Detected {len(detections)} room objects."
            ),
            "image_width": image_width,
            "image_height": image_height,
            "device": DEVICE,
            "box_threshold": request.box_threshold,
            "text_threshold": request.text_threshold,
            "mask_padding": request.mask_padding,
            "detection_count": len(detections),
            "detections": detections,
        }

    except HTTPException:
        raise

    except torch.cuda.OutOfMemoryError as exc:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        raise HTTPException(
            status_code=507,
            detail=(
                "The GPU ran out of memory while detecting room "
                "objects. Reduce max_detections or use a larger "
                "Hugging Face GPU."
            ),
        ) from exc

    except Exception as exc:
        print(
            f"/detect-room-objects failed: "
            f"{type(exc).__name__}: {exc}"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                f"Room-object detection failed: "
                f"{type(exc).__name__}: {exc}"
            ),
        ) from exc
        

@app.api_route("/auto-mask", methods=["GET", "POST"])
async def auto_mask(request: Request):
    if request.method == "POST":
        body = await request.json()
        image_url = body.get("image_url")
        alpha_threshold = int(body.get("alpha_threshold", 10))
    else:
        image_url = request.query_params.get("image_url")
        alpha_threshold = int(request.query_params.get("alpha_threshold", 10))

    if not image_url:
        return {
            "error": "Missing image_url",
            "example_post_body": {
                "image_url": "https://example.com/furniture.png",
                "alpha_threshold": 10,
            },
        }

    image = download_image(image_url)
    mask = create_alpha_mask_from_transparency(image, alpha_threshold)

    return {
        "mask_base64": image_to_base64_data_uri(mask),
        "width": mask.size[0],
        "height": mask.size[1],
    }


@app.api_route("/generate-editor-mask", methods=["GET", "POST"])
async def generate_editor_mask(request: Request):
    if request.method == "POST":
        body = await request.json()
        image_url = body.get("image_url")
        alpha_threshold = int(body.get("alpha_threshold", 10))
    else:
        image_url = request.query_params.get("image_url")
        alpha_threshold = int(request.query_params.get("alpha_threshold", 10))

    if not image_url:
        return {
            "error": "Missing image_url",
            "example_post_body": {
                "image_url": "https://example.com/furniture.png",
                "alpha_threshold": 10,
            },
        }

    image = download_image(image_url)
    green_mask = create_green_editor_mask_from_transparency(image, alpha_threshold)

    return {
        "editor_mask_base64": image_to_base64_data_uri(green_mask),
        "width": green_mask.size[0],
        "height": green_mask.size[1],
    }


@app.api_route("/prepare-fabric-tile", methods=["GET", "POST"])
async def prepare_fabric_tile_endpoint(request: Request):
    try:
        if request.method == "POST":
            body = await request.json()
            fabric_image_url = body.get("fabric_image_url")
            tile_width = int(body.get("tile_width", 800))
            tile_height = int(body.get("tile_height", 800))
            seam_percent = float(body.get("seam_percent", 8))
            blur_radius = float(body.get("blur_radius", 6))
        else:
            fabric_image_url = request.query_params.get("fabric_image_url")
            tile_width = int(request.query_params.get("tile_width", 800))
            tile_height = int(request.query_params.get("tile_height", 800))
            seam_percent = float(request.query_params.get("seam_percent", 8))
            blur_radius = float(request.query_params.get("blur_radius", 6))

        if not fabric_image_url:
            return {"error": "Missing fabric_image_url"}

        fabric_image = download_image(fabric_image_url)
        prepared_tile = prepare_fabric_tile_image(
            fabric_image=fabric_image,
            tile_width=tile_width,
            tile_height=tile_height,
            seam_percent=seam_percent,
            blur_radius=blur_radius,
        )

        return {
            "fabric_tile_base64": image_to_base64_data_uri(prepared_tile),
            "width": prepared_tile.size[0],
            "height": prepared_tile.size[1],
        }

    except Exception as e:
        return {"error": "Prepare fabric tile failed", "details": str(e)}


@app.api_route("/prepare-repeat-tile", methods=["GET", "POST"])
async def prepare_repeat_tile(request: Request):
    try:
        if request.method == "POST":
            body = await request.json()
            fabric_image_url = body.get("fabric_image_url")
            output_tile_width = int(body.get("output_tile_width", 800))
            output_tile_height = int(body.get("output_tile_height", 800))
            auto_detect = body.get("auto_detect", True)
            user_repeat_set = body.get("user_repeat_set", False)
            repeat_left_percent = float(body.get("repeat_left_percent", 0))
            repeat_top_percent = float(body.get("repeat_top_percent", 0))
            repeat_width_percent = float(body.get("repeat_width_percent", 33))
            repeat_height_percent = float(body.get("repeat_height_percent", 33))
            min_confidence = float(body.get("min_confidence", 0.25))
            max_quality_ratio = float(body.get("max_quality_ratio", 1.6))
        else:
            fabric_image_url = request.query_params.get("fabric_image_url")
            output_tile_width = int(request.query_params.get("output_tile_width", 800))
            output_tile_height = int(request.query_params.get("output_tile_height", 800))
            auto_detect = request.query_params.get("auto_detect", "true")
            user_repeat_set = request.query_params.get("user_repeat_set", "false")
            repeat_left_percent = float(request.query_params.get("repeat_left_percent", 0))
            repeat_top_percent = float(request.query_params.get("repeat_top_percent", 0))
            repeat_width_percent = float(request.query_params.get("repeat_width_percent", 33))
            repeat_height_percent = float(request.query_params.get("repeat_height_percent", 33))
            min_confidence = float(request.query_params.get("min_confidence", 0.25))
            max_quality_ratio = float(request.query_params.get("max_quality_ratio", 1.6))

        if not fabric_image_url:
            return {"error": "Missing fabric_image_url"}

        fabric_image = download_image(fabric_image_url)
        source_width, source_height = fabric_image.size

        auto_detect = _as_bool(auto_detect, default=True)
        user_repeat_set = _as_bool(user_repeat_set, default=False)

        detection = None
        auto_recommended = False

        if auto_detect:
            detection = find_repeat_cell(fabric_image, min_confidence=min_confidence)
            if detection["box"] is not None:
                if detection["mode"] == "uniform":
                    auto_recommended = True
                else:
                    auto_recommended = (
                        detection["confidence"] >= min_confidence
                        and detection["quality_ratio"] <= max_quality_ratio
                    )

        auto_suggestion = None
        if detection is not None and detection["box"] is not None:
            a_left, a_top, a_right, a_bottom = detection["box"]
            auto_suggestion = {
                "left_percent": (a_left / source_width) * 100,
                "top_percent": (a_top / source_height) * 100,
                "width_percent": ((a_right - a_left) / source_width) * 100,
                "height_percent": ((a_bottom - a_top) / source_height) * 100,
            }

        use_manual = (not auto_recommended and user_repeat_set) or (not auto_detect)

        if not use_manual and detection is not None and detection["box"] is not None:
            box = detection["box"]
            period = detection["period"]
            repeat_detection_mode = detection["mode"]
            repeat_confidence = detection["confidence"]
            quality_ratio = detection["quality_ratio"]
            repeat_left_percent_used = auto_suggestion["left_percent"]
            repeat_top_percent_used = auto_suggestion["top_percent"]
            repeat_width_percent_used = auto_suggestion["width_percent"]
            repeat_height_percent_used = auto_suggestion["height_percent"]
        else:
            left = int(source_width * max(0, min(repeat_left_percent, 100)) / 100)
            top = int(source_height * max(0, min(repeat_top_percent, 100)) / 100)
            right = min(source_width, left + int(source_width * max(1, min(repeat_width_percent, 100)) / 100))
            bottom = min(source_height, top + int(source_height * max(1, min(repeat_height_percent, 100)) / 100))
            if right <= left or bottom <= top:
                left, top, right, bottom = 0, 0, source_width, source_height

            box = (left, top, right, bottom)
            period = (right - left, bottom - top)
            repeat_detection_mode = "manual_user" if user_repeat_set else "manual"
            repeat_confidence = detection["confidence"] if detection is not None else None
            quality_ratio = detection["quality_ratio"] if detection is not None else None
            repeat_left_percent_used = repeat_left_percent
            repeat_top_percent_used = repeat_top_percent
            repeat_width_percent_used = repeat_width_percent
            repeat_height_percent_used = repeat_height_percent

        repeat_tile = extract_seamless_tile(fabric_image, box, period)

        # Preserve cell aspect ratio. output_tile_height is accepted for compatibility,
        # but the actual height is derived from the detected/manual crop.
        cell_w, cell_h = repeat_tile.size
        out_w = int(output_tile_width)
        out_h = max(1, int(round(out_w * cell_h / cell_w)))
        repeat_tile = repeat_tile.resize((out_w, out_h), Image.LANCZOS)
        repeat_preview = build_repeat_preview(repeat_tile, cols=3, rows=3)

        return {
            "repeat_tile_base64": image_to_base64_data_uri(repeat_tile),
            "repeat_preview_base64": image_to_base64_data_uri(repeat_preview),
            "width": repeat_tile.size[0],
            "height": repeat_tile.size[1],
            "preview_width": repeat_preview.size[0],
            "preview_height": repeat_preview.size[1],
            "repeat_detection_mode": repeat_detection_mode,
            "auto_repeat_recommended": auto_recommended,
            "repeat_confidence": repeat_confidence,
            "repeat_quality_ratio": quality_ratio,
            "repeat_period_width_px": period[0],
            "repeat_period_height_px": period[1],
            "repeat_score": repeat_confidence,
            "repeat_left_percent_used": float(repeat_left_percent_used),
            "repeat_top_percent_used": float(repeat_top_percent_used),
            "repeat_width_percent_used": float(repeat_width_percent_used),
            "repeat_height_percent_used": float(repeat_height_percent_used),
            "auto_suggested_left_percent": auto_suggestion["left_percent"] if auto_suggestion else None,
            "auto_suggested_top_percent": auto_suggestion["top_percent"] if auto_suggestion else None,
            "auto_suggested_width_percent": auto_suggestion["width_percent"] if auto_suggestion else None,
            "auto_suggested_height_percent": auto_suggestion["height_percent"] if auto_suggestion else None,
        }

    except Exception as e:
        return {"error": "Prepare repeat tile failed", "details": str(e)}


@app.api_route("/apply-fabric", methods=["GET", "POST"])
async def apply_fabric(request: Request):
    try:
        if request.method == "POST":
            body = await request.json()
            furniture_image_url = body.get("furniture_image_url")
            fabric_image_url = body.get("fabric_image_url")
            mask_image_url = body.get("mask_image_url")
            pattern_scale_percent = body.get("pattern_scale_percent", 20)
            pattern_offset_x = body.get("pattern_offset_x", 0)
            pattern_offset_y = body.get("pattern_offset_y", 0)
            shading_strength = body.get("shading_strength", 0.32)
            highlight_strength = body.get("highlight_strength", 0.18)
            detail_strength = body.get("detail_strength", 0.28)
            fabric_opacity = body.get("fabric_opacity", 0.88)
            separate_panels = body.get("separate_panels", True)
            panel_edge_threshold = body.get("panel_edge_threshold", 26)
            min_panel_area_percent = body.get("min_panel_area_percent", 1.0)
            panel_seam_darkness = body.get("panel_seam_darkness", 0.35)
        else:
            furniture_image_url = request.query_params.get("furniture_image_url")
            fabric_image_url = request.query_params.get("fabric_image_url")
            mask_image_url = request.query_params.get("mask_image_url")
            pattern_scale_percent = request.query_params.get("pattern_scale_percent", 20)
            pattern_offset_x = request.query_params.get("pattern_offset_x", 0)
            pattern_offset_y = request.query_params.get("pattern_offset_y", 0)
            shading_strength = request.query_params.get("shading_strength", 0.32)
            highlight_strength = request.query_params.get("highlight_strength", 0.18)
            detail_strength = request.query_params.get("detail_strength", 0.28)
            fabric_opacity = request.query_params.get("fabric_opacity", 0.88)
            separate_panels = request.query_params.get("separate_panels", "true")
            panel_edge_threshold = request.query_params.get("panel_edge_threshold", 26)
            min_panel_area_percent = request.query_params.get("min_panel_area_percent", 1.0)
            panel_seam_darkness = request.query_params.get("panel_seam_darkness", 0.35)

        def to_float(value, fallback):
            try:
                return float(value)
            except Exception:
                return fallback

        pattern_scale_percent = to_float(pattern_scale_percent, 20.0)
        pattern_offset_x = to_float(pattern_offset_x, 0.0)
        pattern_offset_y = to_float(pattern_offset_y, 0.0)
        shading_strength = to_float(shading_strength, 0.32)
        highlight_strength = to_float(highlight_strength, 0.18)
        detail_strength = to_float(detail_strength, 0.28)
        fabric_opacity = to_float(fabric_opacity, 0.88)
        separate_panels = _as_bool(separate_panels, default=True)

        try:
            panel_edge_threshold = int(float(panel_edge_threshold))
        except Exception:
            panel_edge_threshold = 26
        min_panel_area_percent = to_float(min_panel_area_percent, 1.0)
        panel_seam_darkness = to_float(panel_seam_darkness, 0.35)

        if not furniture_image_url:
            return {"error": "Missing furniture_image_url"}
        if not fabric_image_url:
            return {"error": "Missing fabric_image_url"}
        if not mask_image_url:
            return {"error": "Missing mask_image_url"}

        furniture_image = download_image(furniture_image_url)
        fabric_image = download_image(fabric_image_url)
        mask_image = download_image(mask_image_url)

        rendered, panels_detected = apply_fabric_to_furniture(
            furniture_image=furniture_image,
            fabric_image=fabric_image,
            mask_image=mask_image,
            pattern_scale_percent=pattern_scale_percent,
            pattern_offset_x=pattern_offset_x,
            pattern_offset_y=pattern_offset_y,
            shading_strength=shading_strength,
            highlight_strength=highlight_strength,
            detail_strength=detail_strength,
            fabric_opacity=fabric_opacity,
            separate_panels=separate_panels,
            panel_edge_threshold=panel_edge_threshold,
            min_panel_area_percent=min_panel_area_percent,
            panel_seam_darkness=panel_seam_darkness,
        )

        return {
            "render_base64": image_to_base64_data_uri(rendered),
            "width": rendered.size[0],
            "height": rendered.size[1],
            "panels_detected": panels_detected,
            "separate_panels_used": separate_panels,
            "pattern_scale_percent_used": pattern_scale_percent,
            "pattern_offset_x_used": pattern_offset_x,
            "pattern_offset_y_used": pattern_offset_y,
            "shading_strength_used": shading_strength,
            "highlight_strength_used": highlight_strength,
            "detail_strength_used": detail_strength,
            "fabric_opacity_used": fabric_opacity,
            "debug_furniture_image_url": furniture_image_url,
            "debug_fabric_image_url": fabric_image_url,
            "debug_mask_image_url": mask_image_url,
        }

    except Exception as e:
        return {"error": "Apply fabric failed", "details": str(e)}


@app.api_route("/preview-panels", methods=["GET", "POST"])
async def preview_panels(request: Request):
    """Debug/preview detected fabric panels as colored regions over the furniture."""
    try:
        if request.method == "POST":
            body = await request.json()
            furniture_image_url = body.get("furniture_image_url")
            mask_image_url = body.get("mask_image_url")
            panel_edge_threshold = body.get("panel_edge_threshold", 26)
            min_panel_area_percent = body.get("min_panel_area_percent", 1.0)
        else:
            furniture_image_url = request.query_params.get("furniture_image_url")
            mask_image_url = request.query_params.get("mask_image_url")
            panel_edge_threshold = request.query_params.get("panel_edge_threshold", 26)
            min_panel_area_percent = request.query_params.get("min_panel_area_percent", 1.0)

        try:
            panel_edge_threshold = int(float(panel_edge_threshold))
        except Exception:
            panel_edge_threshold = 26
        try:
            min_panel_area_percent = float(min_panel_area_percent)
        except Exception:
            min_panel_area_percent = 1.0

        if not furniture_image_url:
            return {"error": "Missing furniture_image_url"}
        if not mask_image_url:
            return {"error": "Missing mask_image_url"}

        furniture_image = download_image(furniture_image_url)
        mask_image = download_image(mask_image_url)

        labels = segment_mask_into_panels(
            furniture_image=furniture_image,
            mask_image=mask_image,
            edge_threshold=panel_edge_threshold,
            min_panel_area_percent=min_panel_area_percent,
        )

        panels_detected = int(labels.max())
        palette = [
            (231, 76, 60),
            (52, 152, 219),
            (46, 204, 113),
            (241, 196, 15),
            (155, 89, 182),
            (230, 126, 34),
            (26, 188, 156),
            (236, 64, 122),
            (127, 140, 141),
            (99, 110, 250),
            (144, 202, 60),
            (0, 172, 193),
        ]

        overlay = np.zeros((labels.shape[0], labels.shape[1], 4), dtype=np.uint8)
        for pid in range(1, panels_detected + 1):
            r, g, b = palette[(pid - 1) % len(palette)]
            overlay[labels == pid] = (r, g, b, 140)

        preview = furniture_image.convert("RGBA").copy()
        preview.alpha_composite(Image.fromarray(overlay, "RGBA"))

        return {
            "panels_preview_base64": image_to_base64_data_uri(preview),
            "panels_detected": panels_detected,
            "panel_edge_threshold_used": panel_edge_threshold,
            "width": preview.size[0],
            "height": preview.size[1],
        }

    except Exception as e:
        return {"error": "Preview panels failed", "details": str(e)}


@app.post("/generate-seam-overlay")
def generate_seam_overlay(req: SeamOverlayRequest):
    furniture = load_image_from_url(req.furniture_image_url)
    mask = load_image_from_url(req.mask_image_url)

    width, height = furniture.size
    mask = mask.resize((width, height), Image.LANCZOS).convert("L")
    mask = mask.point(lambda p: 255 if p > 20 else 0)

    gray = ImageOps.grayscale(furniture)
    gray = ImageEnhance.Contrast(gray).enhance(1.6)

    edges = gray.filter(ImageFilter.FIND_EDGES)
    edges = ImageEnhance.Contrast(edges).enhance(4.0)
    edges = edges.point(lambda p: 255 if p > 22 else 0)
    edges = edges.filter(ImageFilter.MaxFilter(3))
    edges = edges.filter(ImageFilter.GaussianBlur(radius=0.45))

    opacity = max(0.0, min(float(req.opacity), 1.0))
    edge_strength = max(0.0, min(float(req.edge_strength), 2.0))

    alpha = edges.point(lambda p: int(max(0, min(255, p * edge_strength * opacity))))
    alpha = ImageChops.multiply(alpha, mask)

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    overlay.putalpha(alpha)

    alpha_data = list(alpha.getdata())
    return {
        "seam_overlay_base64": image_to_base64_data_uri(overlay),
        "width": width,
        "height": height,
        "max_alpha": max(alpha_data) if alpha_data else 0,
        "nontransparent_pixels": sum(1 for p in alpha_data if p > 0),
    }


@app.api_route("/normalize-furniture-image", methods=["GET", "POST"])
async def normalize_furniture_image_endpoint(request: Request):
    try:
        if request.method == "POST":
            body = await request.json()
            image_url = body.get("image_url")
            canvas_width = int(body.get("canvas_width", 1200))
            canvas_height = int(body.get("canvas_height", 800))
            padding_percent = float(body.get("padding_percent", 8))
        else:
            image_url = request.query_params.get("image_url")
            canvas_width = int(request.query_params.get("canvas_width", 1200))
            canvas_height = int(request.query_params.get("canvas_height", 800))
            padding_percent = float(request.query_params.get("padding_percent", 8))

        if not image_url:
            return {"error": "Missing image_url"}

        image = download_image(image_url)
        normalized = normalize_furniture_image(
            image=image,
            canvas_width=canvas_width,
            canvas_height=canvas_height,
            padding_percent=padding_percent,
        )

        return {
            "normalized_base64": image_to_base64_data_uri(normalized),
            "width": normalized.size[0],
            "height": normalized.size[1],
        }

    except Exception as e:
        return {"error": "Normalize furniture image failed", "details": str(e)}


@app.api_route("/convert-editor-mask", methods=["GET", "POST"])
async def convert_editor_mask(request: Request):
    if request.method == "POST":
        body = await request.json()
        editor_mask_url = body.get("editor_mask_url")
        original_image_url = body.get("original_image_url")
        alpha_threshold = int(body.get("alpha_threshold", 10))
    else:
        editor_mask_url = request.query_params.get("editor_mask_url")
        original_image_url = request.query_params.get("original_image_url")
        alpha_threshold = int(request.query_params.get("alpha_threshold", 10))

    if not editor_mask_url:
        return {"error": "Missing editor_mask_url"}
    if not original_image_url:
        return {"error": "Missing original_image_url"}

    editor_image = download_image(editor_mask_url)
    original_image = download_image(original_image_url)

    clean_mask = convert_green_eraser_mask_to_bw_with_original_alpha(
        editor_image,
        original_image,
        alpha_threshold,
    )

    return {
        "clean_mask_base64": image_to_base64_data_uri(clean_mask),
        "width": clean_mask.size[0],
        "height": clean_mask.size[1],
    }

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=7860,
    )