#!/usr/bin/env python3
"""Simple web demo for ring-size-cv.

Upload an image, run measurement, and return JSON + debug overlay.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import sys
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from flask import Flask, Response, jsonify, redirect, render_template, request, send_from_directory
from werkzeug.utils import secure_filename

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from measure_finger import measure_finger, measure_multi_finger, apply_calibration
from src.logging_config import configure_logging
from src.ring_size import recommend_ring_size, RING_MODELS, VALID_RING_MODELS, DEFAULT_RING_MODEL
from src.ai_recommendation import ai_explain_recommendation
from src.session_recommendation import (
    image_sha256,
    normalize_session_id,
    update_session_recommendation,
)
from web_demo.supabase_client import (
    upload_file,
    upload_bytes,
    save_measurement,
    save_feedback,
    persistence_enabled,
    update_measurement_feedback,
    FEEDBACK_OK,
    FEEDBACK_NO_ROW,
    FEEDBACK_DISABLED,
    list_measurements,
    count_measurements,
    list_feedback,
    count_feedback,
    list_measurements_for_stats,
    update_ground_truth,
    delete_measurement,
    delete_feedback,
    storage_usage,
)
from src.confidence_constants import (
    CONFIDENCE_LEVEL_HIGH_THRESHOLD,
    CONFIDENCE_LEVEL_MEDIUM_THRESHOLD,
)

configure_logging()

APP_ROOT = Path(__file__).resolve().parent
UPLOAD_DIR = APP_ROOT / "uploads"
RESULTS_DIR = APP_ROOT / "results"
DEFAULT_SAMPLE_PATH = APP_ROOT / "static" / "examples" / "default_sample.jpg"
DEFAULT_SAMPLE_URL = "/static/examples/default_sample.jpg"
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
DEMO_EDGE_METHOD = "mask"
DEMO_CARD_METHOD = "sam"
VALID_CAPTURE_METHODS = {"upload", "camera"}
DEFAULT_CAPTURE_METHOD = "upload"

app = Flask(__name__)

logger = logging.getLogger(__name__)

# Persist to Supabase off the request thread: two storage uploads + a row
# insert add multi-second latency that the user would otherwise stare at
# after the measurement is already done. max_workers=2 is plenty — each
# request queues one task, and we don't need ordering.
_persist_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="supa-persist")

# v7 storage diet: shrink what we store, not what we measure. Measurement
# runs on the full-res in-memory image FIRST; only the stored copies are
# downscaled. The pipeline never sees past ~1024px anyway (SAM downscales
# internally), so a 2048px stored photo reproduces the full-res measurement
# (validated: median 0.07 mm delta, zero new failures at 2048/q80). The
# result overlay is display-only and never re-measured, so it goes smaller.
PHOTO_MAX_SIDE = 2048
RESULT_MAX_SIDE = 1024
STORE_JPEG_QUALITY = 80
SESSION_STATE_MAX_BYTES = 50_000


def _shrink_jpeg(image_path: Path, max_side: int) -> Optional[bytes]:
    """Read an image, downscale to max_side long-edge (never upscale), and
    return JPEG q80 bytes. Returns None on any decode/encode failure so the
    caller can fall back to uploading the original file."""
    try:
        img = cv2.imread(str(image_path))
        if img is None:
            return None
        h, w = img.shape[:2]
        long_side = max(h, w)
        if long_side > max_side:
            scale = max_side / long_side
            img = cv2.resize(img, (int(round(w * scale)), int(round(h * scale))),
                             interpolation=cv2.INTER_AREA)
        ok, enc = cv2.imencode(".jpg", img,
                               [cv2.IMWRITE_JPEG_QUALITY, STORE_JPEG_QUALITY])
        if not ok:
            return None
        return enc.tobytes()
    except Exception as exc:  # noqa: BLE001
        logger.warning("shrink failed for %s: %s", image_path, exc)
        return None


def _upload_shrunk(local_path: Path, storage_path: str, max_side: int) -> Optional[str]:
    """Upload a downscaled JPEG copy of local_path. Falls back to uploading
    the original file if shrink fails, so a recompress hiccup never drops the
    image entirely."""
    data = _shrink_jpeg(local_path, max_side)
    if data is not None:
        return upload_bytes(data, storage_path, "image/jpeg")
    return upload_file(str(local_path), storage_path)


def _persist_measurement_async(
    *,
    upload_path: Optional[Path],
    upload_name: str,
    result_png_path: Path,
    result_png_name: str,
    record: Dict[str, Any],
) -> None:
    """Upload the photo + result PNG to Supabase Storage and insert the
    measurement row. Designed to run in a worker thread — takes no request
    state and logs (rather than raises) on failure so a broken Supabase
    connection never poisons the measurement the user just saw.
    """
    def _task() -> None:
        try:
            photo_url = None
            result_url = None
            if upload_path and upload_path.exists():
                photo_url = _upload_shrunk(
                    upload_path, f"photos/{upload_name}", PHOTO_MAX_SIDE)
            if result_png_path.exists():
                # Keep the historical `_result.png` object name (DB result_url
                # points at it) but store JPEG bytes — browsers honor the
                # image/jpeg content-type over the .png extension.
                result_url = _upload_shrunk(
                    result_png_path, f"results/{result_png_name}", RESULT_MAX_SIDE)
            record_with_urls = dict(record)
            record_with_urls["photo_url"] = photo_url
            record_with_urls["result_url"] = result_url
            save_measurement(record_with_urls)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Supabase persist failed for run %s: %s",
                             record.get("run_id"), exc)

    _persist_executor.submit(_task)


def _allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name or "").strip("-").lower()
    return slug or "anon"


def _email_local_part(email: str) -> str:
    """Return the part of an email before '@'. Used only for naming the
    stored object — we deliberately keep the full address out of bucket
    paths (it's PII; relevant for EU KOLs)."""
    return (email or "").split("@", 1)[0]


def _make_base_name(kol_email: str) -> Tuple[str, str]:
    """Return (base_name, run_id). base_name = '{slug}_{timestamp}_{shortid}'.

    The slug is derived from the email local-part only — never the full
    address — so stored object paths don't leak the domain/full email."""
    run_id = uuid.uuid4().hex[:8]
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base_name = f"{_slugify(_email_local_part(kol_email))}_{timestamp}_{run_id}"
    return base_name, run_id


def _numpy_safe(obj):
    """Recursively convert numpy types to native Python types.

    Applied to measurement results before they hit either Flask's jsonify
    (which doesn't know about numpy) or the JSON file writer.
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


def _save_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _read_form_settings() -> Dict[str, Any]:
    """Parse the measurement-request form fields shared by /api/measure and
    /api/measure-default."""
    ring_model = request.form.get("ring_model", DEFAULT_RING_MODEL)
    if ring_model not in VALID_RING_MODELS:
        ring_model = DEFAULT_RING_MODEL
    capture_method = request.form.get("capture_method", DEFAULT_CAPTURE_METHOD)
    if capture_method not in VALID_CAPTURE_METHODS:
        capture_method = DEFAULT_CAPTURE_METHOD

    # gate_telemetry is a JSON-encoded blob from the v5 capture coach. Schema
    # is intentionally fluid — server stamps it into result_json verbatim so
    # frontend can evolve the payload without server changes. Hard-cap the
    # raw size at 10 KB so a malicious client can't pad result_json (and
    # Supabase rows) with arbitrary bytes; the legitimate payload is on the
    # order of a few hundred bytes.
    gate_telemetry: Optional[Dict[str, Any]] = None
    raw = request.form.get("gate_telemetry")
    if raw:
        if len(raw) > 10_000:
            logger.warning("dropping oversized gate_telemetry payload (%d bytes)", len(raw))
        else:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    gate_telemetry = parsed
            except json.JSONDecodeError:
                logger.warning("dropping malformed gate_telemetry payload")

    # Session state is returned by this server and carried by the browser to
    # the next measurement. It is still untrusted input: cap its size here and
    # let src/session_recommendation.py validate every nested field.
    session_state: Optional[Dict[str, Any]] = None
    raw_session_state = request.form.get("session_state")
    if raw_session_state:
        if len(raw_session_state) > SESSION_STATE_MAX_BYTES:
            logger.warning(
                "dropping oversized session_state payload (%d bytes)",
                len(raw_session_state),
            )
        else:
            try:
                parsed_state = json.loads(raw_session_state)
                if isinstance(parsed_state, dict):
                    session_state = parsed_state
            except json.JSONDecodeError:
                logger.warning("dropping malformed session_state payload")

    return {
        "finger_index": request.form.get("finger_index", "index"),
        "mode": request.form.get("mode", "single"),
        # Email is the cross-table join key (see doc/v8/PRD.md). Normalize
        # to trim + lowercase so the same address matches across the
        # measurement, feedback, and shipping data sources.
        "kol_email": request.form.get("kol_email", "").strip().lower(),
        "ring_model": ring_model,
        "capture_method": capture_method,
        "gate_telemetry": gate_telemetry,
        "session_id": normalize_session_id(request.form.get("session_id")),
        "session_state": session_state,
    }


def _apply_session_recommendation(
    result: Dict[str, Any],
    *,
    session_id: Optional[str],
    previous_state: Optional[Dict[str, Any]],
    ring_model: str,
    run_id: str,
    image_digest: str,
    mode: str,
    finger_index: str = "index",
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Attach the median recommendation without changing raw shot fields."""
    if session_id is None:
        return None, None
    try:
        state, recommendation = update_session_recommendation(
            previous_state,
            session_id=session_id,
            ring_model=ring_model,
            run_id=run_id,
            image_digest=image_digest,
            result=result,
            mode=mode,
            finger_index=finger_index,
        )
    except (TypeError, ValueError) as exc:
        logger.warning("session aggregation skipped for run %s: %s", run_id, exc)
        return None, None
    if recommendation is not None:
        result["session_recommendation"] = recommendation
    return state, recommendation


# Coarse UA sniff — only used to decide which surface (`index.html` vs
# `mobile.html`) to render at `/`. We deliberately use a simple regex
# rather than a UA-parsing library: false negatives just mean a phone
# user sees the desktop page, which they can recover from with the
# `?desktop=1` override; false positives are harmless because the
# desktop user just sees the mobile page (and can use `?desktop=1`
# from there). Not worth a heavy dependency.
_MOBILE_UA_RE = re.compile(
    r"iphone|ipod|android.+mobile|blackberry|iemobile|opera mini|windows phone",
    re.IGNORECASE,
)


def _is_mobile_ua(user_agent_str: str) -> bool:
    return bool(user_agent_str and _MOBILE_UA_RE.search(user_agent_str))


@app.route("/")
def index():
    # Phone visitors get auto-redirected to the mobile flow unless they
    # opt out with `?desktop=1`. The override lets the dev demo from a
    # phone in desktop mode and lets us share desktop links that hold
    # up regardless of the recipient's device.
    force_desktop = request.args.get("desktop") is not None
    if not force_desktop and _is_mobile_ua(request.headers.get("User-Agent", "")):
        return redirect("/m", code=302)
    return render_template("index.html", default_sample_url=DEFAULT_SAMPLE_URL, dev_mode=False)


@app.route("/m")
def index_mobile():
    return render_template("mobile.html")


@app.route("/dev")
@app.route("/debug")
def index_dev():
    return render_template("index.html", default_sample_url=DEFAULT_SAMPLE_URL, dev_mode=True)


@app.route("/feedback")
def feedback_form():
    """Public post-shipment KOL fit-feedback form (v8). Mobile-first but
    served to all UAs — desktop KOLs must be able to fill it too, so no
    UA redirect here (unlike `/`)."""
    return render_template("feedback.html")


@app.route("/results/<path:filename>")
def serve_result(filename: str):
    return send_from_directory(RESULTS_DIR, filename)


@app.route("/uploads/<path:filename>")
def serve_upload(filename: str):
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/api/measure", methods=["POST"])
def api_measure():
    if "image" not in request.files:
        return jsonify({"success": False, "error": "Missing image file"}), 400

    file = request.files["image"]
    if file.filename == "":
        return jsonify({"success": False, "error": "Empty filename"}), 400

    if not _allowed_file(file.filename):
        return jsonify({"success": False, "error": "Unsupported file type"}), 400

    settings = _read_form_settings()
    base_name, run_id = _make_base_name(settings["kol_email"])
    suffix = Path(secure_filename(file.filename)).suffix.lower() or ".jpg"
    upload_name = f"{base_name}{suffix}"
    upload_path = UPLOAD_DIR / upload_name
    upload_path.parent.mkdir(parents=True, exist_ok=True)
    file.save(upload_path)
    image_digest = image_sha256(upload_path.read_bytes())

    image = cv2.imread(str(upload_path))
    if image is None:
        return jsonify({"success": False, "error": "Failed to load image"}), 400

    common_kwargs = dict(
        image=image,
        input_image_url=f"/uploads/{upload_name}",
        ring_model=settings["ring_model"],
        kol_email=settings["kol_email"],
        capture_method=settings["capture_method"],
        gate_telemetry=settings["gate_telemetry"],
        upload_path=upload_path,
        upload_name=upload_name,
        base_name=base_name,
        run_id=run_id,
        image_digest=image_digest,
        session_id=settings["session_id"],
        session_state=settings["session_state"],
    )
    if settings["mode"] == "multi":
        return _run_multi_measurement(**common_kwargs)
    return _run_measurement(finger_index=settings["finger_index"], **common_kwargs)


@app.route("/api/measure-default", methods=["POST"])
def api_measure_default():
    if not DEFAULT_SAMPLE_PATH.exists():
        return jsonify({"success": False, "error": "Default sample image not found"}), 500

    image = cv2.imread(str(DEFAULT_SAMPLE_PATH))
    if image is None:
        return jsonify({"success": False, "error": "Failed to load default sample image"}), 500

    settings = _read_form_settings()
    base_name, run_id = _make_base_name(settings["kol_email"] or "sample")
    image_digest = image_sha256(DEFAULT_SAMPLE_PATH.read_bytes())

    common_kwargs = dict(
        image=image,
        input_image_url=DEFAULT_SAMPLE_URL,
        ring_model=settings["ring_model"],
        kol_email=settings["kol_email"],
        capture_method=settings["capture_method"],
        gate_telemetry=settings["gate_telemetry"],
        base_name=base_name,
        run_id=run_id,
        image_digest=image_digest,
        session_id=settings["session_id"],
        session_state=settings["session_state"],
    )
    if settings["mode"] == "multi":
        return _run_multi_measurement(**common_kwargs)
    return _run_measurement(finger_index=settings["finger_index"], **common_kwargs)


def _run_measurement(
    image,
    finger_index: str,
    input_image_url: str,
    ring_model: str = DEFAULT_RING_MODEL,
    kol_email: str = "",
    capture_method: str = DEFAULT_CAPTURE_METHOD,
    gate_telemetry: Optional[Dict[str, Any]] = None,
    upload_path: Optional[Path] = None,
    upload_name: str = "",
    base_name: str = "",
    run_id: str = "",
    image_digest: str = "",
    session_id: Optional[str] = None,
    session_state: Optional[Dict[str, Any]] = None,
):
    result_png_name = f"{base_name}_result.png"
    result_png_path = RESULTS_DIR / result_png_name

    result = measure_finger(
        image=image,
        finger_index=finger_index,
        edge_method=DEMO_EDGE_METHOD,
        card_method=DEMO_CARD_METHOD,
        result_png_path=str(result_png_path),
        save_debug=False,
        ring_model=ring_model,
    )

    # Apply calibration
    raw_diameter = result.get("finger_outer_diameter_cm")
    if raw_diameter is not None:
        result["raw_diameter_cm"] = round(raw_diameter, 4)
        calibrated = round(apply_calibration(raw_diameter), 4)
        result["finger_outer_diameter_cm"] = calibrated
        result["calibration_applied"] = True
        rec = recommend_ring_size(calibrated, ring_model=ring_model)
        if rec:
            result["ring_size"] = rec

    result["capture_method"] = capture_method
    if gate_telemetry is not None:
        result["gate_telemetry"] = gate_telemetry
    result = _numpy_safe(result)

    updated_session_state, session_recommendation = _apply_session_recommendation(
        result,
        session_id=session_id,
        previous_state=session_state,
        ring_model=ring_model,
        run_id=run_id,
        image_digest=image_digest,
        mode="single",
        finger_index=finger_index,
    )

    result_json_name = f"{base_name}_result.json"
    result_json_path = RESULTS_DIR / result_json_name
    _save_json(result_json_path, result)

    payload = {
        "success": result.get("fail_reason") is None,
        "result": result,
        "result_image_url": f"/results/{result_png_name}",
        "input_image_url": input_image_url,
        "result_json_url": f"/results/{result_json_name}",
        "run_id": run_id,
        "session_state": updated_session_state,
        "session_recommendation": session_recommendation,
    }

    # Persist to Supabase in the background — do not block the response on
    # storage uploads or DB inserts.
    ring_size = result.get("ring_size", {})
    _persist_measurement_async(
        upload_path=upload_path,
        upload_name=upload_name,
        result_png_path=result_png_path,
        result_png_name=result_png_name,
        record={
            "run_id": run_id,
            # kol_name is left unset for new rows — it is retained on the
            # table only for pre-email historical data. Email is the key.
            "kol_email": kol_email,
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
            "session_id": session_id,
            "session_attempt_index": (
                updated_session_state.get("attempt_count")
                if updated_session_state else None
            ),
            "image_sha256": image_digest,
            "session_recommendation": session_recommendation,
        },
    )

    return jsonify(payload)


def _run_multi_measurement(
    image,
    input_image_url: str,
    ring_model: str = DEFAULT_RING_MODEL,
    kol_email: str = "",
    capture_method: str = DEFAULT_CAPTURE_METHOD,
    gate_telemetry: Optional[Dict[str, Any]] = None,
    upload_path: Optional[Path] = None,
    upload_name: str = "",
    base_name: str = "",
    run_id: str = "",
    image_digest: str = "",
    session_id: Optional[str] = None,
    session_state: Optional[Dict[str, Any]] = None,
):
    """Run multi-finger measurement pipeline."""
    result_png_name = f"{base_name}_result.png"
    result_png_path = RESULTS_DIR / result_png_name

    result = measure_multi_finger(
        image=image,
        edge_method=DEMO_EDGE_METHOD,
        card_method=DEMO_CARD_METHOD,
        result_png_path=str(result_png_path),
        save_debug=False,
        no_calibration=False,
        ring_model=ring_model,
    )

    result["capture_method"] = capture_method
    if gate_telemetry is not None:
        result["gate_telemetry"] = gate_telemetry
    result = _numpy_safe(result)

    updated_session_state, session_recommendation = _apply_session_recommendation(
        result,
        session_id=session_id,
        previous_state=session_state,
        ring_model=ring_model,
        run_id=run_id,
        image_digest=image_digest,
        mode="multi",
    )

    # Collect finger widths for AI recommendation
    recommendation_result = session_recommendation or result
    recommendation_per_finger = recommendation_result.get("per_finger", {})
    raw_per_finger = result.get("per_finger", {})
    finger_widths = {}
    for fn in ("index", "middle", "ring"):
        pf = recommendation_per_finger.get(fn, {})
        if pf.get("status") == "ok" and pf.get("diameter_cm") is not None:
            finger_widths[fn] = pf["diameter_cm"]
        else:
            finger_widths[fn] = None

    ai_reason = None
    ai_explain = request.form.get("ai_explain", "0") == "1"
    if ai_explain and recommendation_result.get("overall_best_size") is not None:
        ai_reason = ai_explain_recommendation(
            finger_widths,
            recommended_size=recommendation_result["overall_best_size"],
            range_min=recommendation_result["overall_range_min"],
            range_max=recommendation_result["overall_range_max"],
            ring_model=ring_model,
        )
    if ai_reason:
        result["ai_explanation"] = ai_reason

    result_json_name = f"{base_name}_result.json"
    result_json_path = RESULTS_DIR / result_json_name
    _save_json(result_json_path, result)

    # Compute overall confidence from per-finger data
    confidences = [
        pf.get("confidence") for pf in raw_per_finger.values()
        if pf.get("status") == "ok" and pf.get("confidence") is not None
    ]
    overall_confidence = min(confidences) if confidences else None

    payload = {
        "success": result.get("fail_reason") is None,
        "mode": "multi",
        "result": result,
        "result_image_url": f"/results/{result_png_name}",
        "input_image_url": input_image_url,
        "result_json_url": f"/results/{result_json_name}",
        "run_id": run_id,
        "session_state": updated_session_state,
        "session_recommendation": session_recommendation,
    }

    # Persist to Supabase in the background.
    _persist_measurement_async(
        upload_path=upload_path,
        upload_name=upload_name,
        result_png_path=result_png_path,
        result_png_name=result_png_name,
        record={
            "run_id": run_id,
            # kol_name left unset for new rows (see _run_measurement).
            "kol_email": kol_email,
            "mode": "multi",
            "ring_model": ring_model,
            "overall_best_size": result.get("overall_best_size"),
            "overall_range_min": result.get("overall_range_min"),
            "overall_range_max": result.get("overall_range_max"),
            "per_finger": raw_per_finger,
            "confidence": overall_confidence,
            "result_json": result,
            "fail_reason": result.get("fail_reason"),
            "session_id": session_id,
            "session_attempt_index": (
                updated_session_state.get("attempt_count")
                if updated_session_state else None
            ),
            "image_sha256": image_digest,
            "session_recommendation": session_recommendation,
        },
    )

    return jsonify(payload)


FEEDBACK_MAX_MESSAGE_LEN = 4000
# The measurement row is persisted asynchronously (storage uploads + insert
# take ~1–5 s on a healthy connection), so a fast-finger user can submit
# feedback before the row exists. Retry briefly to absorb that race before
# returning an error.
FEEDBACK_RETRY_ATTEMPTS = 6
FEEDBACK_RETRY_DELAY_S = 0.5


@app.route("/api/feedback", methods=["POST"])
def api_feedback():
    data = request.get_json(silent=True) or request.form
    run_id = (data.get("run_id") or "").strip()
    if not run_id:
        return jsonify({"success": False, "error": "run_id is required"}), 400

    rating_raw = data.get("rating")
    rating: Optional[int] = None
    if rating_raw not in (None, ""):
        # Reject booleans (True/False are int subclasses in Python) and
        # floats (a malicious or buggy client sending 4.9 would otherwise
        # round-trip as 4 after int()). Accept int and str shapes only.
        if isinstance(rating_raw, bool) or isinstance(rating_raw, float):
            return jsonify({"success": False, "error": "rating must be an integer 1–5"}), 400
        try:
            rating = int(rating_raw)
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "rating must be an integer 1–5"}), 400
        if rating < 1 or rating > 5:
            return jsonify({"success": False, "error": "rating must be between 1 and 5"}), 400

    message = (data.get("message") or "").strip()[:FEEDBACK_MAX_MESSAGE_LEN] or None

    if rating is None and not message:
        return jsonify({"success": False, "error": "Provide a rating or a message"}), 400

    # Only patch the columns the user actually provided — sending
    # {feedback_rating: rating, feedback_message: message} unconditionally
    # would NULL out the other column on a follow-up partial submission.
    updates: Dict[str, Any] = {}
    if rating is not None:
        updates["feedback_rating"] = rating
    if message is not None:
        updates["feedback_message"] = message

    status = update_measurement_feedback(run_id, updates)
    if status == FEEDBACK_NO_ROW:
        # Race with the async measurement insert: row may not exist yet.
        # Bounded retry; if still missing afterwards, surface a real error.
        for _ in range(FEEDBACK_RETRY_ATTEMPTS - 1):
            time.sleep(FEEDBACK_RETRY_DELAY_S)
            status = update_measurement_feedback(run_id, updates)
            if status != FEEDBACK_NO_ROW:
                break

    if status == FEEDBACK_OK or status == FEEDBACK_DISABLED:
        # DISABLED means RING_DISABLE_SUPABASE is set (local dev) — treat
        # as success since the user-facing action did what it could.
        return jsonify({"success": True})

    if status == FEEDBACK_NO_ROW:
        logger.warning("Feedback not attached: no row for run %s", run_id)
        return jsonify({"success": False, "error": "Measurement not found"}), 404

    # FEEDBACK_ERROR — Supabase raised; supabase_client already logged it.
    return jsonify({"success": False, "error": "Could not save feedback, please retry"}), 500


# Post-shipment fit-feedback (v8). Distinct from /api/feedback above: that
# attaches a post-measurement star rating to a measurements row; this writes
# a standalone row to the decoupled `feedback` table (no run_id, no FK). The
# only link between the two tables is the normalized kol_email. See
# doc/v8/PRD.md.
@app.route("/api/fit-feedback", methods=["POST"])
def api_fit_feedback():
    # Multipart because the photo is optional; non-file fields arrive in
    # request.form regardless.
    kol_email = (request.form.get("kol_email") or "").strip().lower()
    if not kol_email or "@" not in kol_email:
        return jsonify({"success": False, "error": "A valid email is required"}), 400
    # Name is also required: legacy KOLs were measured under the old
    # name-based identity (before the email switch), so their measurements
    # rows have kol_name but no kol_email. Capturing the name here lets their
    # post-shipment feedback join back to those historical rows. See
    # doc/v8/PRD.md.
    kol_name = (request.form.get("kol_name") or "").strip()
    if not kol_name:
        return jsonify({"success": False, "error": "A name is required"}), 400

    def _field(name: str) -> Optional[str]:
        v = (request.form.get(name) or "").strip()
        return v or None

    # Optional photo of the ring on the best-fit finger. Uploaded to the
    # existing bucket under feedback/, slugging the email local-part only
    # (never the full address) so the bucket path doesn't leak PII.
    photo_url = None
    file = request.files.get("photo")
    if file and file.filename:
        if not _allowed_file(file.filename):
            return jsonify({"success": False, "error": "Unsupported photo type"}), 400
        base_name, _ = _make_base_name(kol_email)
        suffix = Path(secure_filename(file.filename)).suffix.lower() or ".jpg"
        photo_name = f"{base_name}{suffix}"
        photo_path = UPLOAD_DIR / photo_name
        file.save(str(photo_path))
        # Synchronous upload (no heavy compute here, unlike /api/measure) so
        # the inserted row already carries photo_url — no follow-up patch.
        photo_url = upload_file(str(photo_path), f"feedback/{photo_name}")

    record = {
        "kol_email": kol_email,
        "kol_name": kol_name,
        "received_size": _field("received_size"),
        "received_model": _field("received_model"),
        "best_fit_finger": _field("best_fit_finger"),
        "fit_quality": _field("fit_quality"),
        "hand": _field("hand"),
        "photo_url": photo_url,
        "notes": _field("notes"),
    }

    row_id = save_feedback(record)
    if row_id is not None:
        return jsonify({"success": True})
    if not persistence_enabled():
        # RING_DISABLE_SUPABASE / unconfigured env (local dev) — the form did
        # what it could; report success rather than a scary error.
        return jsonify({"success": True})
    # Persistence is on but the insert returned nothing / raised.
    return jsonify({"success": False, "error": "Could not save feedback, please retry"}), 500


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "ringsizer2026")

# Max rows the admin list endpoints fetch in one request. The DB may hold
# more; the true total is sent in the X-Total-Count header so the front-end
# can show "newest N of M" instead of silently hiding older rows.
ADMIN_LIST_LIMIT = 500


def _with_total(resp, total: Optional[int]):
    """Attach the full row count as X-Total-Count (skipped when unknown,
    e.g. persistence disabled). Lets the admin UI flag a truncated list."""
    if total is not None:
        resp.headers["X-Total-Count"] = str(total)
    return resp


@app.route("/admin")
def admin_page():
    return render_template("admin.html")


def _check_admin_token():
    token = request.args.get("token") or request.headers.get("X-Admin-Token")
    return token == ADMIN_TOKEN


@app.route("/api/admin/measurements")
def api_admin_measurements():
    if not _check_admin_token():
        return jsonify({"error": "Unauthorized"}), 401
    rows = list_measurements(limit=ADMIN_LIST_LIMIT)
    return _with_total(jsonify(rows), count_measurements())


@app.route("/api/admin/feedback")
def api_admin_feedback():
    if not _check_admin_token():
        return jsonify({"error": "Unauthorized"}), 401
    rows = list_feedback(limit=ADMIN_LIST_LIMIT)
    return _with_total(jsonify(rows), count_feedback())


@app.route("/api/admin/measurements/<measurement_id>/ground-truth", methods=["POST"])
def api_admin_update_gt(measurement_id: str):
    if not _check_admin_token():
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    ok = update_ground_truth(measurement_id, data)
    if ok:
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Update failed"}), 400


@app.route("/api/admin/measurements/<measurement_id>", methods=["DELETE"])
def api_admin_delete(measurement_id: str):
    if not _check_admin_token():
        return jsonify({"error": "Unauthorized"}), 401
    ok = delete_measurement(measurement_id)
    if ok:
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Delete failed"}), 400


@app.route("/api/admin/feedback/<feedback_id>", methods=["DELETE"])
def api_admin_delete_feedback(feedback_id: str):
    if not _check_admin_token():
        return jsonify({"error": "Unauthorized"}), 401
    ok = delete_feedback(feedback_id)
    if ok:
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Delete failed"}), 400


def _parse_iso_to_utc_date(iso_str: str) -> Optional[date]:
    """Parse a Supabase `created_at` ISO string to a UTC `date`.

    Supabase returns either '...+00:00' or trailing 'Z'. fromisoformat does
    not accept 'Z' until 3.11, so normalize defensively.
    """
    if not iso_str:
        return None
    try:
        s = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).date()
    except (ValueError, TypeError):
        return None


def _kol_key(identifier: Optional[str]) -> Optional[str]:
    """Normalize a KOL identifier for grouping (trim + lower). Empty → None
    so we don't count anonymous sample runs as a distinct KOL. Callers pass
    the email (the join key) with kol_name as a fallback for legacy rows."""
    if not identifier:
        return None
    s = identifier.strip().lower()
    return s or None


def _compute_stats(rows: List[Dict[str, Any]], days: int = 30) -> Dict[str, Any]:
    """Aggregate measurement rows into dashboard-ready buckets.

    All time-bucketing is in UTC. `days` controls the per-day window; KOL,
    failure, and distribution stats use the entire row set so totals reflect
    everything in the table.
    """
    today = datetime.now(timezone.utc).date()
    window_start = today - timedelta(days=days - 1)

    per_day_photos: Counter = Counter()
    per_day_kols: defaultdict = defaultdict(set)
    per_day_fails: Counter = Counter()

    kol_counts: Counter = Counter()
    kol_counts_window: Counter = Counter()
    kol_last_seen: Dict[str, str] = {}
    kol_display: Dict[str, str] = {}
    fail_counter: Counter = Counter()
    ring_model_counter: Counter = Counter()
    size_counter: Counter = Counter()

    confidence_buckets = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    confidence_sum = 0.0
    confidence_n = 0

    rating_buckets: Counter = Counter()
    rating_sum = 0.0
    rating_n = 0
    comment_count = 0

    success_count = 0
    fail_count = 0

    last_7_count = 0
    prev_7_count = 0
    last_7_start = today - timedelta(days=6)
    prev_7_start = today - timedelta(days=13)

    first_at: Optional[str] = None
    last_at: Optional[str] = None

    for row in rows:
        created_at = row.get("created_at") or ""
        if created_at:
            if last_at is None or created_at > last_at:
                last_at = created_at
            if first_at is None or created_at < first_at:
                first_at = created_at

        d = _parse_iso_to_utc_date(created_at)

        # Prefer email (the join key); fall back to kol_name for rows that
        # predate the email switch.
        kol_ident = row.get("kol_email") or row.get("kol_name")
        kkey = _kol_key(kol_ident)
        in_window = d is not None and window_start <= d <= today
        if kkey:
            kol_counts[kkey] += 1
            if kkey not in kol_display:
                kol_display[kkey] = (kol_ident or "").strip()
            if in_window:
                kol_counts_window[kkey] += 1
                if created_at and (kkey not in kol_last_seen or created_at > kol_last_seen[kkey]):
                    kol_last_seen[kkey] = created_at

        fail_reason = row.get("fail_reason")
        if fail_reason:
            fail_count += 1
            fail_counter[fail_reason] += 1
        else:
            success_count += 1

        rm = row.get("ring_model")
        if rm:
            ring_model_counter[rm] += 1

        # Ring size distribution: index-finger size only, and exclude demo
        # runs (photo_url is null when the user clicks "try with sample" —
        # those measurements aren't the KOL's true size).
        if row.get("photo_url"):
            index_size = None
            if row.get("mode") == "multi":
                pf = (row.get("per_finger") or {}).get("index") or {}
                if pf.get("status") == "ok":
                    index_size = pf.get("best_match")
            elif row.get("finger_index") == "index":
                index_size = row.get("overall_best_size")
            if index_size not in (None, ""):
                size_counter[str(index_size)] += 1

        conf = row.get("confidence")
        if isinstance(conf, (int, float)):
            confidence_sum += float(conf)
            confidence_n += 1
            if conf > CONFIDENCE_LEVEL_HIGH_THRESHOLD:
                confidence_buckets["HIGH"] += 1
            elif conf >= CONFIDENCE_LEVEL_MEDIUM_THRESHOLD:
                confidence_buckets["MEDIUM"] += 1
            else:
                confidence_buckets["LOW"] += 1

        # Only count feedback on successful runs — feedback attached to a
        # failed measurement reflects "the tool didn't work for me," not a
        # rating of the measurement itself, so including it would poison
        # avg_rating. Going forward the UI also hides the panel on failure,
        # but this filter cleans up any pre-existing rows from when it didn't.
        if not fail_reason:
            rating = row.get("feedback_rating")
            if isinstance(rating, int) and 1 <= rating <= 5:
                rating_sum += rating
                rating_n += 1
                rating_buckets[rating] += 1
            if (row.get("feedback_message") or "").strip():
                comment_count += 1

        if d is not None:
            if window_start <= d <= today:
                key = d.isoformat()
                per_day_photos[key] += 1
                if kkey:
                    per_day_kols[key].add(kkey)
                if fail_reason:
                    per_day_fails[key] += 1
            if last_7_start <= d <= today:
                last_7_count += 1
            elif prev_7_start <= d < last_7_start:
                prev_7_count += 1

    per_day_series = []
    for i in range(days):
        d = window_start + timedelta(days=i)
        key = d.isoformat()
        per_day_series.append({
            "date": key,
            "photos": per_day_photos.get(key, 0),
            "unique_kols": len(per_day_kols.get(key, ())),
            "fails": per_day_fails.get(key, 0),
        })

    top_kols = [
        {
            # Display label is the email (the join key) or, for legacy
            # rows, the name — hence kol_ident, not kol_name.
            "kol_ident": kol_display.get(k, k),
            "count": c,
            "last_at": kol_last_seen.get(k),
        }
        for k, c in kol_counts_window.most_common(10)
    ]

    fail_reasons = [
        {"reason": r, "count": c}
        for r, c in fail_counter.most_common()
    ]

    ring_models = [
        {"model": m, "count": c}
        for m, c in ring_model_counter.most_common()
    ]

    def _size_sort_key(item):
        s = item[0]
        try:
            return (0, float(s))
        except (TypeError, ValueError):
            return (1, s)

    size_distribution = [
        {"size": s, "count": c}
        for s, c in sorted(size_counter.items(), key=_size_sort_key)
    ]

    total = len(rows)
    success_rate = (success_count / total) if total else 0.0
    avg_confidence = (confidence_sum / confidence_n) if confidence_n else 0.0
    avg_rating = (rating_sum / rating_n) if rating_n else 0.0

    return {
        "totals": {
            "total_measurements": total,
            "unique_kols": len(kol_counts),
            "success_count": success_count,
            "fail_count": fail_count,
            "success_rate": round(success_rate, 4),
            "avg_confidence": round(avg_confidence, 4),
            "avg_rating": round(avg_rating, 2),
            "rating_count": rating_n,
            "comment_count": comment_count,
            "last_7_days": last_7_count,
            "prev_7_days": prev_7_count,
            "first_measurement_at": first_at,
            "last_measurement_at": last_at,
        },
        "rating_distribution": [
            {"stars": str(n), "count": rating_buckets.get(n, 0)} for n in (1, 2, 3, 4, 5)
        ],
        "window_days": days,
        "per_day": per_day_series,
        "top_kols": top_kols,
        "fail_reasons": fail_reasons,
        "ring_models": ring_models,
        "size_distribution": size_distribution,
        "confidence_buckets": [
            {"bucket": "HIGH (>0.85)", "count": confidence_buckets["HIGH"]},
            {"bucket": "MEDIUM (0.6–0.85)", "count": confidence_buckets["MEDIUM"]},
            {"bucket": "LOW (<0.6)", "count": confidence_buckets["LOW"]},
        ],
    }


@app.route("/api/admin/stats")
def api_admin_stats():
    if not _check_admin_token():
        return jsonify({"error": "Unauthorized"}), 401
    try:
        days = max(7, min(int(request.args.get("days", 30)), 180))
    except (TypeError, ValueError):
        days = 30
    rows = list_measurements_for_stats(limit=5000)
    return jsonify(_compute_stats(rows, days=days))


@app.route("/api/admin/storage")
def api_admin_storage():
    if not _check_admin_token():
        return jsonify({"error": "Unauthorized"}), 401
    usage = storage_usage()
    if usage is None:
        return jsonify({"available": False})
    usage["available"] = True
    return jsonify(usage)


_CSV_INJECTION_LEAD = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value: Any) -> str:
    """Defang CSV-injection vectors in user-supplied cell values.

    Excel / Google Sheets treat a leading `=`, `+`, `-`, or `@` as a
    formula trigger. Prefixing a single quote turns the cell into plain
    text without changing how it displays once the user removes the
    quote, so the data round-trips back to whatever shape the user
    expected.
    """
    if value is None:
        return ""
    s = str(value)
    if s and s[0] in _CSV_INJECTION_LEAD:
        return "'" + s
    return s


@app.route("/api/admin/export-csv")
def api_admin_export_csv():
    if not _check_admin_token():
        return jsonify({"error": "Unauthorized"}), 401
    rows = list_measurements(limit=5000)
    output = io.StringIO()
    fieldnames = [
        "kol_email", "kol_name", "created_at", "mode", "ring_model",
        "session_id", "session_attempt_index", "session_hand", "session_successful_shots",
        "overall_best_size", "overall_range_min", "overall_range_max",
        "index_size", "index_diameter", "index_confidence",
        "middle_size", "middle_diameter", "middle_confidence",
        "ring_size", "ring_diameter", "ring_confidence",
        "session_index_size", "session_index_diameter",
        "session_index_decision_mm", "session_index_samples",
        "session_index_spread_mm",
        "session_middle_size", "session_middle_diameter",
        "session_middle_decision_mm", "session_middle_samples",
        "session_middle_spread_mm",
        "session_ring_size", "session_ring_diameter",
        "session_ring_decision_mm", "session_ring_samples",
        "session_ring_spread_mm",
        "confidence", "fail_reason", "ai_explanation",
        "ring_fit", "gt_best_finger", "gt_index_size", "gt_middle_size", "gt_ring_size", "gt_notes",
        "feedback_rating", "feedback_message",
        "photo_url", "result_url", "id",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        flat = {
            "kol_email": _csv_safe(row.get("kol_email", "")),
            "kol_name": _csv_safe(row.get("kol_name", "")),
            "created_at": row.get("created_at", ""),
            "mode": row.get("mode", ""),
            "ring_model": row.get("ring_model", ""),
            "session_id": row.get("session_id", ""),
            "session_attempt_index": row.get("session_attempt_index", ""),
            "overall_best_size": row.get("overall_best_size", ""),
            "overall_range_min": row.get("overall_range_min", ""),
            "overall_range_max": row.get("overall_range_max", ""),
            "confidence": row.get("confidence", ""),
            "fail_reason": row.get("fail_reason", ""),
            "ai_explanation": _csv_safe((row.get("result_json") or {}).get("ai_explanation", "")),
            "ring_fit": _csv_safe(row.get("ring_fit", "")),
            "gt_best_finger": _csv_safe(row.get("gt_best_finger", "")),
            "gt_index_size": row.get("gt_index_size", ""),
            "gt_middle_size": row.get("gt_middle_size", ""),
            "gt_ring_size": row.get("gt_ring_size", ""),
            "gt_notes": _csv_safe(row.get("gt_notes", "")),
            "feedback_rating": row.get("feedback_rating", ""),
            "feedback_message": _csv_safe(row.get("feedback_message", "")),
            "photo_url": row.get("photo_url", ""),
            "result_url": row.get("result_url", ""),
            "id": row.get("id", ""),
        }
        pf = row.get("per_finger") or {}
        session_rec = row.get("session_recommendation") or {}
        session_pf = session_rec.get("per_finger") or {}
        flat["session_hand"] = session_rec.get("handedness", "")
        flat["session_successful_shots"] = session_rec.get("successful_shots", "")
        for finger in ("index", "middle", "ring"):
            fd = pf.get(finger, {})
            flat[f"{finger}_size"] = fd.get("best_match", "")
            flat[f"{finger}_diameter"] = fd.get("diameter_cm", "")
            flat[f"{finger}_confidence"] = fd.get("confidence", "")
            session_fd = session_pf.get(finger, {})
            flat[f"session_{finger}_size"] = session_fd.get("best_match", "")
            flat[f"session_{finger}_diameter"] = session_fd.get("diameter_cm", "")
            flat[f"session_{finger}_decision_mm"] = session_fd.get(
                "decision_diameter_mm", ""
            )
            flat[f"session_{finger}_samples"] = session_fd.get("sample_count", "")
            flat[f"session_{finger}_spread_mm"] = session_fd.get("spread_mm", "")
        writer.writerow(flat)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=kol_measurements.csv"},
    )


if __name__ == "__main__":
    # Local-dev HTTPS via mkcert: set RING_DEV_TLS_CERT and RING_DEV_TLS_KEY
    # to enable HTTPS on the dev server (required for getUserMedia on a
    # phone over LAN). HF Space deploys leave these unset and serve HTTP
    # behind HF's platform-level TLS terminator.
    cert = os.environ.get("RING_DEV_TLS_CERT")
    key = os.environ.get("RING_DEV_TLS_KEY")
    ssl_context = (cert, key) if cert and key else None
    app.run(host="0.0.0.0", port=8000, debug=True, ssl_context=ssl_context)
