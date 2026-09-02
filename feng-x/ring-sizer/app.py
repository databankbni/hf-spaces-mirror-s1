#!/usr/bin/env python3
"""Gradio entry point for the Ring Sizer HuggingFace Space (v5).

Public demo flow only: upload → measurement → result image + ring size
summary + raw JSON. The Flask app in `web_demo/` is still used locally for
admin / CSV / ground-truth editing, but HF Spaces now serves this Gradio
app so the measurement call can run on ZeroGPU-backed H200 GPUs.

See `doc/v5/` for the PRD, plan, and progress notes.
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

# `spaces` is a no-op outside HF ZeroGPU, so importing it unconditionally
# keeps the local CPU path working without conditional imports.
import spaces  # type: ignore
import gradio as gr

# --------------------------------------------------------------------------- #
# Monkey-patch for a known Gradio 4.44 / gradio_client bug: when the API-info
# endpoint builds a schema for an output that includes `additionalProperties:
# True` (a bool, not a dict), `gradio_client.utils.get_type()` tries
# `"const" in schema` and raises `TypeError: argument of type 'bool' is not
# iterable`. Our `gr.JSON` output lands in that code path on first page load
# and crashes the whole Space. Wrap `get_type` so any non-dict schema resolves
# to the permissive "Any" type. Has no effect on well-typed schemas.
# --------------------------------------------------------------------------- #
try:
    import gradio_client.utils as _gc_utils  # noqa: E402

    _orig_get_type = _gc_utils.get_type

    def _safe_get_type(schema):  # type: ignore[no-redef]
        if not isinstance(schema, dict):
            return "Any"
        return _orig_get_type(schema)

    _gc_utils.get_type = _safe_get_type  # type: ignore[assignment]

    _orig_json_schema_to_python_type = _gc_utils._json_schema_to_python_type

    def _safe_json_schema_to_python_type(schema, defs=None):  # type: ignore[no-redef]
        if not isinstance(schema, dict):
            return "Any"
        return _orig_json_schema_to_python_type(schema, defs)

    _gc_utils._json_schema_to_python_type = _safe_json_schema_to_python_type  # type: ignore[assignment]
except Exception as _exc:  # noqa: BLE001
    print(f"[v5] gradio_client get_type patch skipped: {_exc}")

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

from measure_finger import (  # noqa: E402
    measure_finger,
    measure_multi_finger,
    apply_calibration,
)
from src.ring_size import (  # noqa: E402
    recommend_ring_size,
    VALID_RING_MODELS,
    DEFAULT_RING_MODEL,
)
from src.ai_recommendation import ai_explain_recommendation  # noqa: E402
from src.sam_backend import get_sam2  # noqa: E402

# HF ZeroGPU docs: "models must be placed on cuda at the root module level"
# (a PyTorch CUDA emulation mode is enabled outside @spaces.GPU functions,
# so this runs cleanly both on ZeroGPU and CPU). Pre-loading here means the
# first request does not pay the weight-to-GPU transfer cost.
try:
    get_sam2()
except Exception as exc:  # noqa: BLE001
    # Don't block app startup if SAM weights are missing — the measurement
    # call will re-attempt and surface a clearer error to the user.
    print(f"[v5] SAM preload skipped: {exc}")

# Supabase persistence piggybacks on the same async executor pattern as the
# Flask app so the GPU slice releases as soon as the measurement returns.
try:
    from web_demo.supabase_client import upload_file, save_measurement  # noqa: E402
    _SUPABASE_AVAILABLE = True
except Exception as exc:  # noqa: BLE001
    print(f"[v5] Supabase client not importable ({exc}) — persistence disabled")
    _SUPABASE_AVAILABLE = False

logger = logging.getLogger(__name__)
_persist_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="supa-persist")

RESULTS_DIR = ROOT_DIR / "web_demo" / "results"
UPLOADS_DIR = ROOT_DIR / "web_demo" / "uploads"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

DEMO_EDGE_METHOD = "mask"
DEMO_CARD_METHOD = "sam"
DEMO_HAND_MASK_METHOD = "sam"

DEFAULT_SAMPLE_PATH = ROOT_DIR / "web_demo" / "static" / "examples" / "default_sample.jpg"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _numpy_safe(obj: Any) -> Any:
    """Recursively convert numpy scalar/array types to native Python types.

    Gradio's JSON component calls `json.dumps` internally, which trips on
    `np.float32`, `np.bool_`, and friends. This mirrors the helper already
    used by the Flask app.
    """
    if isinstance(obj, dict):
        return {k: _numpy_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_numpy_safe(v) for v in obj]
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.generic):
        return obj.item()
    return obj


def _make_base_name(kol_name: str) -> Tuple[str, str]:
    run_id = uuid.uuid4().hex[:8]
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = "".join(c if c.isalnum() else "-" for c in (kol_name or "anon")).strip("-").lower() or "anon"
    return f"{slug}_{timestamp}_{run_id}", run_id


def _persist_async(
    *,
    upload_path: Optional[Path],
    upload_name: str,
    result_png_path: Path,
    result_png_name: str,
    record: Dict[str, Any],
) -> None:
    """Fire-and-forget Supabase persistence (storage uploads + row insert).

    Errors are logged, never raised — a broken Supabase connection must
    never poison the measurement the user just saw.
    """
    if not _SUPABASE_AVAILABLE:
        return

    def _task() -> None:
        try:
            photo_url = None
            result_url = None
            if upload_path is not None and upload_path.exists():
                photo_url = upload_file(str(upload_path), f"photos/{upload_name}")
            if result_png_path.exists():
                result_url = upload_file(str(result_png_path), f"results/{result_png_name}")
            record_with_urls = dict(record)
            record_with_urls["photo_url"] = photo_url
            record_with_urls["result_url"] = result_url
            save_measurement(record_with_urls)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Supabase persist failed for run %s: %s",
                             record.get("run_id"), exc)

    _persist_executor.submit(_task)


def _format_summary(result: Dict[str, Any], mode: str) -> str:
    """Render a human-readable markdown summary above the raw JSON."""
    if result.get("fail_reason"):
        return f"**Measurement failed:** `{result['fail_reason']}`"

    if mode == "multi":
        lines = ["### Multi-finger result"]
        for fn in ("index", "middle", "ring"):
            pf = (result.get("per_finger") or {}).get(fn, {})
            if pf.get("status") == "ok":
                diam = pf.get("diameter_cm")
                best = pf.get("best_match")
                rng = pf.get("range", (None, None))
                lines.append(
                    f"- **{fn.capitalize()}:** {diam:.2f} cm → "
                    f"size **{best}** (range {rng[0]}–{rng[1]})"
                )
            else:
                lines.append(f"- **{fn.capitalize()}:** failed ({pf.get('fail_reason', 'unknown')})")
        if result.get("overall_best_size") is not None:
            lines.append("")
            lines.append(
                f"**Recommended size:** **{result['overall_best_size']}** "
                f"(range {result.get('overall_range_min')}–{result.get('overall_range_max')})"
            )
        if result.get("ai_explanation"):
            lines.append("")
            lines.append(f"**Why:** {result['ai_explanation']}")
        return "\n".join(lines)

    # Single finger
    diam = result.get("finger_outer_diameter_cm")
    conf = result.get("confidence")
    ring = result.get("ring_size") or {}
    lines = ["### Single-finger result"]
    if diam is not None:
        lines.append(f"- **Diameter:** {diam:.2f} cm")
    if result.get("raw_diameter_cm") is not None:
        lines.append(f"- **Raw (uncalibrated):** {result['raw_diameter_cm']:.2f} cm")
    if conf is not None:
        lines.append(f"- **Confidence:** {conf:.2f}")
    if ring:
        lines.append(
            f"- **Ring size:** **{ring.get('best_match')}** "
            f"(range {ring.get('range_min')}–{ring.get('range_max')})"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Measurement handler
# ---------------------------------------------------------------------------

@spaces.GPU(duration=60)
def run_measurement(
    image: Optional[np.ndarray],
    finger_index: str,
    mode: str,
    ring_model: str,
    kol_name: str,
    ai_explain: bool,
) -> Tuple[Optional[np.ndarray], Dict[str, Any], str]:
    """Run the measurement pipeline and return (overlay, json, summary).

    Wrapped in `@spaces.GPU` so HF ZeroGPU allocates an H200 slice per
    request. Outside ZeroGPU the decorator is a no-op and this runs on CPU.
    """
    if image is None:
        return None, {"error": "No image uploaded"}, "**Error:** please upload an image."

    if ring_model not in VALID_RING_MODELS:
        ring_model = DEFAULT_RING_MODEL

    # Gradio gives us an RGB numpy array; the rest of the pipeline expects BGR.
    if image.ndim == 3 and image.shape[2] == 3:
        image_bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    else:
        image_bgr = image

    base_name, run_id = _make_base_name(kol_name)
    result_png_name = f"{base_name}_result.png"
    result_png_path = RESULTS_DIR / result_png_name

    # Also save the raw upload so Supabase persistence has something to push.
    upload_name = f"{base_name}.jpg"
    upload_path = UPLOADS_DIR / upload_name
    cv2.imwrite(str(upload_path), image_bgr)

    if mode == "multi":
        result = measure_multi_finger(
            image=image_bgr,
            edge_method=DEMO_EDGE_METHOD,
            card_method=DEMO_CARD_METHOD,
            hand_mask_method=DEMO_HAND_MASK_METHOD,
            result_png_path=str(result_png_path),
            save_debug=False,
            no_calibration=False,
            ring_model=ring_model,
        )
        result = _numpy_safe(result)

        per_finger = result.get("per_finger", {})
        finger_widths = {
            fn: (pf.get("diameter_cm") if pf.get("status") == "ok" else None)
            for fn, pf in per_finger.items()
        }
        if ai_explain and result.get("overall_best_size") is not None:
            ai_reason = ai_explain_recommendation(
                finger_widths,
                recommended_size=result["overall_best_size"],
                range_min=result["overall_range_min"],
                range_max=result["overall_range_max"],
                ring_model=ring_model,
            )
            if ai_reason:
                result["ai_explanation"] = ai_reason

        # Persist async (release GPU slice first — this runs on CPU after return)
        confidences = [
            pf.get("confidence") for pf in per_finger.values()
            if pf.get("status") == "ok" and pf.get("confidence") is not None
        ]
        overall_confidence = min(confidences) if confidences else None
        _persist_async(
            upload_path=upload_path,
            upload_name=upload_name,
            result_png_path=result_png_path,
            result_png_name=result_png_name,
            record={
                "run_id": run_id,
                "kol_name": kol_name,
                "mode": "multi",
                "ring_model": ring_model,
                "overall_best_size": result.get("overall_best_size"),
                "overall_range_min": result.get("overall_range_min"),
                "overall_range_max": result.get("overall_range_max"),
                "per_finger": per_finger,
                "confidence": overall_confidence,
                "result_json": result,
                "fail_reason": result.get("fail_reason"),
            },
        )
    else:
        result = measure_finger(
            image=image_bgr,
            finger_index=finger_index,
            edge_method=DEMO_EDGE_METHOD,
            card_method=DEMO_CARD_METHOD,
            hand_mask_method=DEMO_HAND_MASK_METHOD,
            result_png_path=str(result_png_path),
            save_debug=False,
            ring_model=ring_model,
        )

        raw_diameter = result.get("finger_outer_diameter_cm")
        if raw_diameter is not None:
            result["raw_diameter_cm"] = round(raw_diameter, 4)
            calibrated = round(apply_calibration(raw_diameter), 4)
            result["finger_outer_diameter_cm"] = calibrated
            result["calibration_applied"] = True
            rec = recommend_ring_size(calibrated, ring_model=ring_model)
            if rec:
                result["ring_size"] = rec

        result = _numpy_safe(result)
        ring_size = result.get("ring_size", {}) or {}
        _persist_async(
            upload_path=upload_path,
            upload_name=upload_name,
            result_png_path=result_png_path,
            result_png_name=result_png_name,
            record={
                "run_id": run_id,
                "kol_name": kol_name,
                "mode": "single",
                "ring_model": ring_model,
                "finger_index": finger_index,
                "diameter_cm": result.get("finger_outer_diameter_cm"),
                "confidence": result.get("confidence"),
                "overall_best_size": ring_size.get("best_match"),
                "overall_range_min": ring_size.get("range_min"),
                "overall_range_max": ring_size.get("range_max"),
                "result_json": result,
                "fail_reason": result.get("fail_reason"),
            },
        )

    # Load the overlay image Gradio will display.
    overlay_rgb: Optional[np.ndarray] = None
    if result_png_path.exists():
        overlay_bgr = cv2.imread(str(result_png_path))
        if overlay_bgr is not None:
            overlay_rgb = cv2.cvtColor(overlay_bgr, cv2.COLOR_BGR2RGB)

    summary = _format_summary(result, mode)
    return overlay_rgb, result, summary


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

_DESCRIPTION = """
Upload a single photo with **one hand and a credit card on the same flat
surface**. The app detects the card (for scale), segments the hand, and
measures the outer diameter of the chosen finger at the ring-wearing zone.
"""

_EXAMPLES: List[List[Any]] = []
if DEFAULT_SAMPLE_PATH.exists():
    _EXAMPLES.append([str(DEFAULT_SAMPLE_PATH), "index", "single", DEFAULT_RING_MODEL, "", False])


def build_demo() -> gr.Blocks:
    with gr.Blocks(title="Ring Sizer") as demo:
        gr.Markdown("# 💍 Ring Sizer")
        gr.Markdown(_DESCRIPTION)

        with gr.Row():
            with gr.Column(scale=1):
                image_in = gr.Image(
                    type="numpy",
                    label="Hand + credit card photo",
                    sources=["upload", "webcam"],
                )
                finger_in = gr.Dropdown(
                    choices=["index", "middle", "ring"],
                    value="index",
                    label="Finger",
                )
                mode_in = gr.Radio(
                    choices=["single", "multi"],
                    value="single",
                    label="Mode",
                    info="`single` measures one finger; `multi` measures index + middle + ring and aggregates.",
                )
                ring_model_in = gr.Dropdown(
                    choices=list(VALID_RING_MODELS),
                    value=DEFAULT_RING_MODEL,
                    label="Ring model",
                )
                kol_name_in = gr.Textbox(label="Name (optional)", placeholder="")
                ai_explain_in = gr.Checkbox(label="Explain recommendation (AI)", value=False)
                run_btn = gr.Button("Measure", variant="primary")

            with gr.Column(scale=1):
                image_out = gr.Image(label="Measurement overlay")
                summary_out = gr.Markdown(label="Summary")
                json_out = gr.JSON(label="Raw result")

        run_btn.click(
            fn=run_measurement,
            inputs=[image_in, finger_in, mode_in, ring_model_in, kol_name_in, ai_explain_in],
            outputs=[image_out, json_out, summary_out],
        )

        if _EXAMPLES:
            gr.Examples(
                examples=_EXAMPLES,
                inputs=[image_in, finger_in, mode_in, ring_model_in, kol_name_in, ai_explain_in],
                label="Try the default sample",
            )

    return demo


demo = build_demo()


if __name__ == "__main__":
    # On HF Gradio Spaces (including ZeroGPU) the platform runs `python app.py`
    # and expects `demo.launch()` with no explicit server_name/port — the
    # `spaces/zero/gradio.py` launch wrapper binds the port itself. Passing
    # `server_name="0.0.0.0"` triggers the "localhost not accessible" self-
    # check inside Gradio and crashes startup. Locally, `demo.launch()` still
    # serves on 127.0.0.1:7860 by default.
    demo.queue().launch(show_api=False)
