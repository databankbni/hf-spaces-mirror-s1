"""Phase 0 deployment feasibility smoke checks.

This module contains NO Gradio code on purpose: everything here must be runnable
from a plain terminal (`python smoke.py --all`) as well as from `app.py`.
That is the same separation the real pipeline will use later
(app.py = UI orchestration, src/ = pipeline).

Each check returns a plain dict so results can be printed, serialised to JSON,
or rendered in a UI without any check ever raising into the caller.
"""

from __future__ import annotations

import io
import json
import os
import platform
import sys
import time
import traceback
from dataclasses import dataclass, field, asdict
from typing import Any, Callable

# --- ZeroGPU environment detection -----------------------------------------
# Two DIFFERENT questions, previously conflated, which caused a real failure:
#
#   1. Is the `spaces` package importable?  -> only tells us the decorator works.
#   2. Are we running on a ZeroGPU Space?   -> SPACES_ZERO_GPU in the environment.
#
# Only (2) may drive CUDA placement. On ZeroGPU the main process has no GPU
# attached; a CUDA emulation layer intercepts `.to("cuda")` **at module startup
# only**. Doing it later (e.g. inside a Gradio request) reaches real
# `torch._C._cuda_init` and raises.


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


ON_ZEROGPU = _env_flag("SPACES_ZERO_GPU")

try:  # pragma: no cover - environment dependent
    import spaces  # type: ignore

    GPU_DECORATOR_AVAILABLE = True

    def gpu(duration: int = 60) -> Callable:
        return spaces.GPU(duration=duration)

except Exception:  # pragma: no cover - environment dependent
    GPU_DECORATOR_AVAILABLE = False

    def gpu(duration: int = 60) -> Callable:
        def _wrap(fn: Callable) -> Callable:
            return fn

        return _wrap


# --- configuration (Phase 0 candidates only, final choice happens in Phase 7)
LLM_MODEL_ID = os.environ.get("GDE_LLM_MODEL_ID", "Qwen/Qwen3-4B-Instruct-2507")
EMBED_MODEL_ID = os.environ.get("GDE_EMBED_MODEL_ID", "BAAI/bge-small-en-v1.5")
RASTER_DPI = int(os.environ.get("GDE_RASTER_DPI", "200"))


@dataclass
class CheckResult:
    name: str
    status: str = "ok"  # ok | error | skipped
    duration_s: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _timed(name: str, fn: Callable[[], dict[str, Any]]) -> CheckResult:
    """Run a check, never raise, always report duration."""
    t0 = time.perf_counter()
    try:
        details = fn()
        return CheckResult(name, "ok", round(time.perf_counter() - t0, 3), details)
    except Exception as exc:  # noqa: BLE001 - deliberate: a failed check is data
        return CheckResult(
            name,
            "error",
            round(time.perf_counter() - t0, 3),
            {"exception_type": type(exc).__name__},
            error=f"{exc}\n{traceback.format_exc(limit=4)}",
        )


# ---------------------------------------------------------------------------
# 1. Runtime report
# ---------------------------------------------------------------------------

SPACE_ENV_VARS = [
    "SPACE_ID",
    "SPACE_AUTHOR_NAME",
    "SPACE_REPO_NAME",
    "SPACE_HOST",
    "SPACE_HARDWARE",
    "SPACES_ZERO_GPU",
    "ZEROGPU",
    "HF_HOME",
    "HF_HUB_CACHE",
    "TRANSFORMERS_CACHE",
]


def check_runtime() -> CheckResult:
    def _run() -> dict[str, Any]:
        info: dict[str, Any] = {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
            "spaces_package": GPU_DECORATOR_AVAILABLE,
            "on_zerogpu": ON_ZEROGPU,
            "llm_ready_from_startup": bool(_LLM),
            "llm_startup_error": _LLM_STARTUP_ERROR,
            "env": {k: os.environ.get(k) for k in SPACE_ENV_VARS if os.environ.get(k)},
        }
        try:
            import psutil  # optional

            info["ram_total_gb"] = round(psutil.virtual_memory().total / 1e9, 1)
        except Exception:
            info["ram_total_gb"] = None

        for pkg in (
            "gradio",
            "torch",
            "transformers",
            "huggingface_hub",
            "onnxruntime",
            "rapidocr_onnxruntime",
            "pypdfium2",
            "numpy",
        ):
            try:
                import importlib.metadata as md

                info[f"version.{pkg}"] = md.version(pkg.replace("_", "-"))
            except Exception:
                info[f"version.{pkg}"] = "not installed"

        try:
            import torch

            info["torch.cuda_available"] = torch.cuda.is_available()
            info["torch.device_count"] = torch.cuda.device_count()
            if torch.cuda.is_available():
                info["torch.device_name"] = torch.cuda.get_device_name(0)
        except Exception as exc:  # torch may be absent locally
            info["torch.cuda_available"] = f"torch unavailable: {exc}"

        # Free disk on the writable working dir (models are cached here).
        try:
            st = os.statvfs(os.environ.get("HF_HOME", "."))
            info["free_disk_gb"] = round(st.f_bavail * st.f_frsize / 1e9, 1)
        except Exception:
            info["free_disk_gb"] = None
        return info

    return _timed("runtime_report", _run)


# ---------------------------------------------------------------------------
# 2. Synthetic document + rasterisation
# ---------------------------------------------------------------------------


def build_synthetic_pdf() -> bytes:
    """A tiny fake borehole-log page, generated in memory.

    Deliberately synthetic: Phase 0 must not depend on any real BGS scan being
    present in the repository, and must not ship client material.
    """
    from PIL import Image, ImageDraw, ImageFont

    def _font(size: int):
        for path in (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
        return ImageFont.load_default()

    width, height = 1240, 1754  # A4 at 150 dpi
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([60, 60, width - 60, 300], outline="black", width=3)
    draw.text((90, 90), "LOG OF BOREHOLE   BH-2024-017", fill="black", font=_font(44))
    draw.text((90, 170), "Easting: 412345.6    Northing: 287654.3", fill="black", font=_font(34))
    draw.text((90, 225), "Final Depth: 25.40 m below ground level", fill="black", font=_font(34))
    draw.text((90, 360), "Description: sandy CLAY, stiff, brown", fill="black", font=_font(30))
    draw.text((90, 410), "Ground level: 12.35 m OD    Diameter: 150 mm", fill="black", font=_font(30))
    buf = io.BytesIO()
    img.save(buf, format="PDF", resolution=150.0)
    return buf.getvalue()


def rasterize_first_page(pdf_bytes: bytes, dpi: int = RASTER_DPI):
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf_bytes)
    page = doc[0]
    pil = page.render(scale=dpi / 72).to_pil().convert("RGB")
    return pil, len(doc)


def check_pdf_raster() -> CheckResult:
    def _run() -> dict[str, Any]:
        pdf_bytes = build_synthetic_pdf()
        t0 = time.perf_counter()
        pil, n_pages = rasterize_first_page(pdf_bytes)
        return {
            "pdf_bytes": len(pdf_bytes),
            "pages": n_pages,
            "raster_dpi": RASTER_DPI,
            "image_size": list(pil.size),
            "raster_s": round(time.perf_counter() - t0, 3),
        }

    return _timed("pdf_rasterization", _run)


# ---------------------------------------------------------------------------
# 3. OCR (CPU)
# ---------------------------------------------------------------------------

_OCR_ENGINE = None


def get_ocr_engine():
    """Load once per process. Timing of the first call = cold model init."""
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR

        _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


def run_ocr(pil_image) -> list[dict[str, Any]]:
    """Return OCR tokens in a shape close to the future OCRToken contract."""
    import numpy as np

    engine = get_ocr_engine()
    result, _elapse = engine(np.array(pil_image))
    tokens = []
    for box, text, score in result or []:
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        tokens.append(
            {
                "text": text,
                "bbox": [min(xs), min(ys), max(xs), max(ys)],
                "confidence": round(float(score), 4),
            }
        )
    return tokens


def check_ocr() -> CheckResult:
    def _run() -> dict[str, Any]:
        pil, _ = rasterize_first_page(build_synthetic_pdf())

        t0 = time.perf_counter()
        already_loaded = _OCR_ENGINE is not None
        get_ocr_engine()
        init_s = round(time.perf_counter() - t0, 3)

        t0 = time.perf_counter()
        tokens = run_ocr(pil)
        first_s = round(time.perf_counter() - t0, 3)

        t0 = time.perf_counter()
        run_ocr(pil)
        warm_s = round(time.perf_counter() - t0, 3)

        joined = " ".join(t["text"] for t in tokens).lower()
        return {
            "engine": "rapidocr-onnxruntime (PP-OCRv4 det+rec, ONNX, CPU)",
            "engine_was_already_loaded": already_loaded,
            "engine_init_s": init_s,
            "first_page_ocr_s": first_s,
            "warm_page_ocr_s": warm_s,
            "n_tokens": len(tokens),
            "mean_confidence": round(
                sum(t["confidence"] for t in tokens) / max(len(tokens), 1), 3
            ),
            # Sanity signal: did OCR recover the values we planted in the image?
            "found_borehole_id": "bh-2024-017" in joined.replace(" ", "").replace("bh2024017", "bh-2024-017"),
            "found_easting": "412345.6" in joined,
            "found_northing": "287654.3" in joined,
            "found_depth": "25.40" in joined,
            "tokens": tokens[:10],
        }

    return _timed("ocr_cpu", _run)


# ---------------------------------------------------------------------------
# 4. Embedding model
# ---------------------------------------------------------------------------

_EMBEDDER: dict[str, Any] = {}


def check_embeddings() -> CheckResult:
    def _run() -> dict[str, Any]:
        import torch
        from transformers import AutoModel, AutoTokenizer

        t0 = time.perf_counter()
        if not _EMBEDDER:
            _EMBEDDER["tok"] = AutoTokenizer.from_pretrained(EMBED_MODEL_ID)
            _EMBEDDER["model"] = AutoModel.from_pretrained(EMBED_MODEL_ID).eval()
        load_s = round(time.perf_counter() - t0, 3)

        sentences = [
            "Easting: 412345.6 Northing: 287654.3",
            "The final depth of the borehole is 25.40 m.",
            "Description: sandy CLAY, stiff, brown.",
        ]
        t0 = time.perf_counter()
        batch = _EMBEDDER["tok"](sentences, padding=True, truncation=True, return_tensors="pt")
        with torch.no_grad():
            out = _EMBEDDER["model"](**batch).last_hidden_state[:, 0]
        emb = torch.nn.functional.normalize(out, dim=-1)
        encode_s = round(time.perf_counter() - t0, 3)

        return {
            "model_id": EMBED_MODEL_ID,
            "load_s": load_s,
            "encode_s": encode_s,
            "embedding_dim": int(emb.shape[-1]),
            "sim_coords_vs_depth": round(float(emb[0] @ emb[1]), 3),
            "sim_coords_vs_lithology": round(float(emb[0] @ emb[2]), 3),
        }

    return _timed("embeddings", _run)


# ---------------------------------------------------------------------------
# 5. LLM structured extraction
# ---------------------------------------------------------------------------

_LLM: dict[str, Any] = {}
# Set only while the module-tail startup load is running, so the reported
# timings distinguish "loaded during Space boot" from "loaded on demand".
_IN_STARTUP = False
_LLM_STARTUP_ERROR: str | None = None

STRUCTURED_PROMPT = """You extract borehole metadata from OCR text.

OCR TEXT:
---
LOG OF BOREHOLE BH-2024-017
Easting: 412345.6 Northing: 287654.3
Final Depth: 25.40 m below ground level
Description: sandy CLAY, stiff, brown
---

Return ONLY a JSON object with exactly these keys:
"borehole_id" (string), "easting" (number), "northing" (number), "final_depth_m" (number).
No explanation, no markdown fences."""

EXPECTED = {
    "borehole_id": "BH-2024-017",
    "easting": 412345.6,
    "northing": 287654.3,
    "final_depth_m": 25.4,
}


def load_llm() -> dict[str, Any]:
    """Create the tokenizer/model and place the model on its final device.

    WHERE this runs matters more than what it does.

    On a ZeroGPU Space it must run **at module startup** (see the module tail),
    because that is the only moment the CUDA emulation layer intercepts
    `.to("cuda")` outside a GPU slice. Calling it from a Gradio request handler
    reaches real CUDA init and raises — that was the Phase 0 deployment bug.

    Off ZeroGPU it is called lazily and explicitly (CLI or a UI button), and
    stays on CPU unless a real GPU is present. Importing this module never
    triggers it.
    """
    if _LLM:
        return {
            "load_s": _LLM.get("load_s", 0.0),
            "already_loaded": True,
            "loaded_at_startup": _LLM.get("loaded_at_startup", False),
            "device": _LLM.get("device"),
        }

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    t0 = time.perf_counter()
    tok = AutoTokenizer.from_pretrained(LLM_MODEL_ID)
    kwargs: dict[str, Any] = {"dtype": torch.bfloat16}
    try:
        model = AutoModelForCausalLM.from_pretrained(LLM_MODEL_ID, **kwargs)
    except TypeError:  # older transformers used torch_dtype=
        model = AutoModelForCausalLM.from_pretrained(LLM_MODEL_ID, torch_dtype=torch.bfloat16)

    # ON_ZEROGPU: emulated placement at startup, real GPU attached inside
    # @spaces.GPU. cuda.is_available(): an ordinary machine with a real GPU.
    # Neither: stay on CPU.
    if ON_ZEROGPU or torch.cuda.is_available():
        model = model.to("cuda")
    model.eval()

    _LLM["tok"] = tok
    _LLM["model"] = model
    _LLM["load_s"] = round(time.perf_counter() - t0, 3)
    _LLM["loaded_at_startup"] = _IN_STARTUP
    _LLM["device"] = str(model.device)
    return {
        "load_s": _LLM["load_s"],
        "already_loaded": False,
        "loaded_at_startup": _IN_STARTUP,
        "device": _LLM["device"],
    }


@gpu(duration=60)
def _generate(prompt: str, max_new_tokens: int = 96) -> dict[str, Any]:
    import torch

    tok, model = _LLM["tok"], _LLM["model"]
    text = tok.apply_chat_template(
        [{"role": "user", "content": prompt}], tokenize=False, add_generation_prompt=True
    )
    inputs = tok([text], return_tensors="pt").to(model.device)
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    t0 = time.perf_counter()
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
    gen_s = time.perf_counter() - t0
    new_ids = out[0][inputs["input_ids"].shape[1] :]
    completion = tok.decode(new_ids, skip_special_tokens=True)
    return {
        "completion": completion,
        "prompt_tokens": int(inputs["input_ids"].shape[1]),
        "generated_tokens": int(new_ids.shape[0]),
        "generate_s": round(gen_s, 3),
        "tokens_per_s": round(int(new_ids.shape[0]) / max(gen_s, 1e-6), 1),
        "peak_vram_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2)
        if torch.cuda.is_available()
        else None,
        "ran_on": str(model.device),
    }


def parse_json_object(text: str) -> dict[str, Any] | None:
    """Tolerant JSON extraction: models add fences and prose. Never raises."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        cleaned = cleaned[4:] if cleaned.lower().startswith("json") else cleaned
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        obj = json.loads(cleaned[start : end + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def check_llm() -> CheckResult:
    def _run() -> dict[str, Any]:
        if ON_ZEROGPU and not _LLM:
            # Deliberately do NOT load here: on ZeroGPU, request-time CUDA
            # placement is exactly what fails. Report the startup failure.
            raise RuntimeError(
                "model was not prepared at startup on ZeroGPU. "
                f"startup error: {_LLM_STARTUP_ERROR or 'startup load disabled via GDE_DISABLE_STARTUP_LLM'}"
            )
        load_info = load_llm()
        gen = _generate(STRUCTURED_PROMPT)
        parsed = parse_json_object(gen["completion"])
        details: dict[str, Any] = {
            "model_id": LLM_MODEL_ID,
            "on_zerogpu": ON_ZEROGPU,
            "zerogpu_decorator_active": GPU_DECORATOR_AVAILABLE,
            **load_info,
            **gen,
            "parsed_json": parsed,
            "json_parse_ok": parsed is not None,
        }
        if parsed is not None:
            details["fields_correct"] = {
                k: (str(parsed.get(k)).strip().rstrip("0").rstrip(".") == str(v).rstrip("0").rstrip("."))
                for k, v in EXPECTED.items()
            }
            details["all_fields_correct"] = all(details["fields_correct"].values())
        return details

    return _timed("llm_structured_extraction", _run)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

CHECKS: dict[str, Callable[[], CheckResult]] = {
    "runtime": check_runtime,
    "pdf": check_pdf_raster,
    "ocr": check_ocr,
    "embeddings": check_embeddings,
    "llm": check_llm,
}


def run_checks(names: list[str]) -> list[dict[str, Any]]:
    return [CHECKS[n]().to_dict() for n in names if n in CHECKS]


# ---------------------------------------------------------------------------
# ZeroGPU startup load
# ---------------------------------------------------------------------------
# This block is the fix for the Phase 0 deployment failure. It runs at import
# time, i.e. while the Space is starting and before Gradio serves any request,
# which is the only window in which `.to("cuda")` is intercepted by the ZeroGPU
# CUDA emulation layer.
#
# Guarded three ways:
#   - ON_ZEROGPU: a laptop or CI import never downloads 8 GB of weights.
#   - GDE_DISABLE_STARTUP_LLM: escape hatch settable as a Space variable if the
#     download ever threatens the startup timeout — no code change needed.
#   - try/except: a failed load must not prevent the Space from starting. The
#     other four checks stay usable and the error is reported by check_llm().


def _startup_load_llm() -> None:
    global _IN_STARTUP, _LLM_STARTUP_ERROR
    _IN_STARTUP = True
    try:
        info = load_llm()
        print(f"[startup] LLM ready on {info.get('device')} in {info.get('load_s')}s", flush=True)
    except Exception as exc:  # noqa: BLE001 - a failed load is reportable data
        _LLM_STARTUP_ERROR = f"{type(exc).__name__}: {exc}"
        print(f"[startup] LLM load FAILED: {_LLM_STARTUP_ERROR}", flush=True)
        print(traceback.format_exc(limit=6), flush=True)
    finally:
        _IN_STARTUP = False


if ON_ZEROGPU and not _env_flag("GDE_DISABLE_STARTUP_LLM"):  # pragma: no cover
    _startup_load_llm()


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Phase 0 deployment smoke checks")
    ap.add_argument(
        "--checks",
        default="runtime,pdf,ocr",
        help=f"comma-separated subset of: {','.join(CHECKS)} (default excludes the model downloads)",
    )
    ap.add_argument("--all", action="store_true", help="run every check, including model downloads")
    ap.add_argument("--json", action="store_true", help="print raw JSON only")
    args = ap.parse_args()

    names = list(CHECKS) if args.all else [c.strip() for c in args.checks.split(",")]
    results = run_checks(names)

    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        for r in results:
            mark = {"ok": "PASS", "error": "FAIL", "skipped": "SKIP"}[r["status"]]
            print(f"[{mark}] {r['name']} ({r['duration_s']}s)")
            for k, v in r["details"].items():
                if k != "tokens":
                    print(f"        {k}: {v}")
            if r["error"]:
                print(f"        error: {r['error'].splitlines()[0]}")
    return 0 if all(r["status"] == "ok" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
