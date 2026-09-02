"""Phase 0 tests.

Scope is deliberately narrow: the only behaviour worth testing at this stage is
that the checks report honestly (never raise, always carry a status and a
duration) and that the synthetic-document path works end to end.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import smoke  # noqa: E402


def test_synthetic_pdf_is_a_pdf():
    data = smoke.build_synthetic_pdf()
    assert data.startswith(b"%PDF")
    assert len(data) > 1000


def test_rasterization_produces_expected_geometry():
    pil, n_pages = smoke.rasterize_first_page(smoke.build_synthetic_pdf(), dpi=150)
    assert n_pages == 1
    width, height = pil.size
    assert height > width  # portrait A4
    assert 1000 < width < 1500


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('Sure! Here you go:\n{"a": 1}\nHope that helps.', {"a": 1}),
        ("not json at all", None),
        ('{"a": 1', None),  # truncated generation
        ("[1, 2, 3]", None),  # valid JSON, wrong shape
        ("", None),
    ],
)
def test_parse_json_object_is_tolerant_and_never_raises(raw, expected):
    assert smoke.parse_json_object(raw) == expected


def test_failing_check_is_reported_not_raised():
    def boom():
        raise RuntimeError("simulated model download failure")

    result = smoke._timed("simulated", boom)
    assert result.status == "error"
    assert "simulated model download failure" in result.error
    assert result.duration_s >= 0


def test_gpu_decorator_is_a_noop_off_space():
    @smoke.gpu(duration=5)
    def add(a, b):
        return a + b

    assert add(2, 3) == 5


# --- regression: Phase 0 ZeroGPU deployment failure -------------------------
# The Space crashed with `torch._C._cuda_init` because load_llm() ran from a
# Gradio request and called .to("cuda") outside the startup window. These tests
# pin the two halves of the contract that prevent a repeat.


def test_zerogpu_is_detected_from_environment_not_package(monkeypatch):
    """`spaces` being importable must never imply we are on ZeroGPU."""
    for value, expected in [("1", True), ("true", True), ("ON", True), ("0", False), ("", False)]:
        monkeypatch.setenv("SPACES_ZERO_GPU", value)
        assert smoke._env_flag("SPACES_ZERO_GPU") is expected
    monkeypatch.delenv("SPACES_ZERO_GPU", raising=False)
    assert smoke._env_flag("SPACES_ZERO_GPU") is False


def test_importing_smoke_never_loads_the_model():
    """Constraint: `import smoke` on a laptop must not pull 8 GB of weights."""
    assert smoke.ON_ZEROGPU is False
    assert smoke._LLM == {}


def test_check_llm_on_zerogpu_never_loads_at_request_time(monkeypatch):
    """If startup did not prepare the model, report it — do not load lazily."""
    called = []
    monkeypatch.setattr(smoke, "ON_ZEROGPU", True)
    monkeypatch.setattr(smoke, "_LLM", {})
    monkeypatch.setattr(smoke, "_LLM_STARTUP_ERROR", "OSError: simulated download failure")
    monkeypatch.setattr(smoke, "load_llm", lambda: called.append(1))

    result = smoke.check_llm()

    assert result.status == "error"
    assert "startup" in result.error
    assert "simulated download failure" in result.error
    assert called == [], "load_llm() must not be called from a request on ZeroGPU"


def test_check_llm_on_zerogpu_reuses_the_startup_model(monkeypatch):
    """The happy path: the prepared model is reused, timings are preserved."""
    prepared = {
        "tok": object(),
        "model": object(),
        "load_s": 42.5,
        "loaded_at_startup": True,
        "device": "cuda:0",
    }
    monkeypatch.setattr(smoke, "ON_ZEROGPU", True)
    monkeypatch.setattr(smoke, "_LLM", prepared)
    monkeypatch.setattr(
        smoke,
        "_generate",
        lambda prompt, **kw: {
            "completion": '{"borehole_id": "BH-2024-017", "easting": 412345.6,'
            ' "northing": 287654.3, "final_depth_m": 25.4}',
            "prompt_tokens": 120,
            "generated_tokens": 40,
            "generate_s": 1.2,
            "tokens_per_s": 33.3,
            "peak_vram_gb": 8.6,
            "ran_on": "cuda:0",
        },
    )

    result = smoke.check_llm()

    assert result.status == "ok", result.error
    details = result.details
    assert details["already_loaded"] is True
    assert details["loaded_at_startup"] is True
    assert details["load_s"] == 42.5  # startup timing survives into the report
    assert details["device"] == "cuda:0"
    assert details["json_parse_ok"] and details["all_fields_correct"]


def test_every_check_returns_a_serialisable_contract():
    result = smoke.check_runtime().to_dict()
    assert set(result) == {"name", "status", "duration_s", "details", "error"}
    assert result["status"] in {"ok", "error", "skipped"}


@pytest.mark.slow
def test_ocr_recovers_the_planted_fields():
    result = smoke.check_ocr()
    assert result.status == "ok", result.error
    details = result.details
    assert details["found_easting"] and details["found_northing"] and details["found_depth"]
    assert details["n_tokens"] >= 4
    for token in details["tokens"]:
        x0, y0, x1, y1 = token["bbox"]
        assert x1 > x0 and y1 > y0  # bboxes are well formed
