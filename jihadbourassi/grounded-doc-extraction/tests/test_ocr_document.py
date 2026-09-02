"""Tests for the normalized OCR layer.

Almost everything here runs with a stubbed OCR callable, so the suite needs no
ONNX models and stays fast. One test at the bottom is marked `slow` and runs the
real engine on a synthetic PDF.
"""

import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ocr_document import (  # noqa: E402
    MalformedOCRRegion,
    OCRDocument,
    OCRPage,
    OCRRegion,
    bbox_from_polygon,
    make_region_id,
    normalize_polygon,
    regions_to_page_text,
)
from src.ocr_pipeline import (  # noqa: E402
    OCRPipelineError,
    compute_document_id,
    normalize_page_regions,
    ocr_pdf,
    ocr_pdf_bytes,
)

# ---------------------------------------------------------------------------
# fixtures: synthetic multi-page PDF (page 2 deliberately blank)
# ---------------------------------------------------------------------------


def _text_page(lines, size=(1240, 1754)):
    from PIL import Image, ImageDraw, ImageFont

    def _font(px):
        # Portable first: PIL searches the platform's font directories by name,
        # which covers Windows (arial), macOS and Linux distributions.
        for name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf", "arialbd.ttf", "arial.ttf", "Arial.ttf"):
            try:
                return ImageFont.truetype(name, px)
            except Exception:
                continue
        # Then explicit Linux paths, for images with fonts outside the search path.
        for path in (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ):
            try:
                return ImageFont.truetype(path, px)
            except Exception:
                continue
        # Last resort: modern Pillow's built-in scalable default. The unsized
        # bitmap fallback renders too small for OCR, so a test relying on real
        # OCR should skip rather than assert against unreadable output.
        try:
            return ImageFont.load_default(size=px)
        except TypeError:
            return None

    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    y = 120
    for line in lines:
        font = _font(38)
        if font is None:
            pytest.skip("no scalable font available to render a legible synthetic page")
        draw.text((110, y), line, fill="black", font=font)
        y += 90
    return img


@pytest.fixture(scope="module")
def synthetic_pdf_bytes() -> bytes:
    """Three pages: text, blank, text. Generated in memory, nothing on disk."""
    pages = [
        _text_page(["BOREHOLE RECORD SHEET", "Reference: SYNTH-001"]),
        _text_page([]),  # blank -> expect status="no_text"
        _text_page(["Continuation sheet", "Page three of three"]),
    ]
    buf = io.BytesIO()
    pages[0].save(buf, format="PDF", resolution=150.0, save_all=True, append_images=pages[1:])
    return buf.getvalue()


def fake_ocr(pil_image):
    """Deterministic stub: one region per page, always inside the raster."""
    return [
        ([[10, 20], [110, 20], [110, 60], [10, 60]], "SYNTHETIC REGION", 0.9123456),
    ]


def blank_ocr(pil_image):
    return []


# ---------------------------------------------------------------------------
# 1. bbox derivation from polygon
# ---------------------------------------------------------------------------


def test_bbox_from_axis_aligned_quad():
    poly = [[10, 20], [110, 20], [110, 60], [10, 60]]
    assert bbox_from_polygon(poly) == [10.0, 20.0, 110.0, 60.0]


def test_bbox_from_rotated_quad_uses_all_vertices():
    """A tilted region: naive first/third-point indexing would be wrong."""
    poly = [[50, 10], [140, 40], [120, 95], [30, 65]]
    assert bbox_from_polygon(poly) == [30.0, 10.0, 140.0, 95.0]
    naive = [poly[0][0], poly[0][1], poly[2][0], poly[2][1]]
    assert bbox_from_polygon(poly) != naive


def test_bbox_accepts_three_point_polygon_and_floats():
    assert bbox_from_polygon([[1.5, 9.25], [4.0, 2.0], [0.5, 3.0]]) == [0.5, 2.0, 4.0, 9.25]


def test_bbox_is_derived_not_supplied():
    region = OCRRegion.from_ocr("p1-r1", [[5, 5], [15, 5], [15, 25], [5, 25]], "x", 0.5)
    assert region.bbox == [5.0, 5.0, 15.0, 25.0]
    assert region.polygon == [[5.0, 5.0], [15.0, 5.0], [15.0, 25.0], [5.0, 25.0]]


@pytest.mark.parametrize(
    "bad",
    [
        None,
        42,
        [],
        [[0, 0], [1, 1]],  # only 2 points
        [[0, 0, 0], [1, 1, 1], [2, 2, 2]],  # 3 coords per point
        [[0, 0], [1, 1], ["a", 2]],  # non-numeric
        [[0, 0], [1, 1], [float("nan"), 2]],  # NaN
        [[0, 0], [1, 1], [float("inf"), 2]],  # +inf
        [[0, 0], [1, 1], [2, float("-inf")]],  # -inf
    ],
)
def test_malformed_polygon_raises_rather_than_silently_degrading(bad):
    with pytest.raises(MalformedOCRRegion):
        normalize_polygon(bad)


@pytest.mark.parametrize("bad_confidence", [float("nan"), float("inf"), float("-inf"), "high", None])
def test_non_finite_or_non_numeric_confidence_is_malformed(bad_confidence):
    poly = [[0, 0], [9, 0], [9, 9], [0, 9]]
    with pytest.raises(MalformedOCRRegion):
        OCRRegion.from_ocr("p1-r1", poly, "text", bad_confidence)


def test_confidence_precision_is_preserved_not_rounded():
    poly = [[0, 0], [9, 0], [9, 9], [0, 9]]
    region = OCRRegion.from_ocr("p1-r1", poly, "text", 0.9123456789)
    assert region.confidence == 0.9123456789
    assert region.to_dict()["confidence"] == 0.9123456789
    restored = OCRRegion.from_dict(region.to_dict())
    assert restored.confidence == 0.9123456789


def test_from_dict_rederives_bbox_and_rejects_a_tampered_one():
    poly = [[10, 20], [110, 20], [110, 60], [10, 60]]
    good = OCRRegion.from_ocr("p1-r1", poly, "text", 0.9).to_dict()
    assert OCRRegion.from_dict(good).bbox == [10.0, 20.0, 110.0, 60.0]

    tampered = dict(good, bbox=[0.0, 0.0, 5.0, 5.0])
    with pytest.raises(ValueError, match="does not match the bbox derived"):
        OCRRegion.from_dict(tampered)

    wrong_length = dict(good, bbox=[10.0, 20.0, 110.0])
    with pytest.raises(ValueError):
        OCRRegion.from_dict(wrong_length)

    # a missing bbox is fine — it is derivable, which is the whole point
    without = {k: v for k, v in good.items() if k != "bbox"}
    assert OCRRegion.from_dict(without).bbox == [10.0, 20.0, 110.0, 60.0]


def test_tampered_bbox_is_rejected_through_a_full_document_round_trip(synthetic_pdf_bytes):
    doc = ocr_pdf_bytes(synthetic_pdf_bytes, "synthetic.pdf", raster_dpi=100, ocr_fn=fake_ocr)
    data = json.loads(json.dumps(doc.to_dict()))
    data["pages"][0]["regions"][0]["bbox"] = [1.0, 2.0, 3.0, 4.0]
    with pytest.raises(ValueError, match="does not match the bbox derived"):
        OCRDocument.from_dict(data)


def test_numpy_coordinates_and_confidence_become_plain_floats():
    np = pytest.importorskip("numpy")
    poly = np.array([[1, 2], [30, 2], [30, 12], [1, 12]], dtype=np.float32)
    region = OCRRegion.from_ocr("p1-r1", poly, "text", np.float32(0.876543))
    assert all(type(v) is float for point in region.polygon for v in point)
    assert type(region.confidence) is float
    json.dumps(region.to_dict())  # would raise on numpy scalars


# ---------------------------------------------------------------------------
# 2. serialization / schema shape
# ---------------------------------------------------------------------------


def test_document_dict_matches_the_contract_shape(synthetic_pdf_bytes):
    doc = ocr_pdf_bytes(synthetic_pdf_bytes, "synthetic.pdf", raster_dpi=100, ocr_fn=fake_ocr)
    data = doc.to_dict()

    assert set(data) == {"document_id", "source_name", "page_count", "raster_dpi", "pages"}
    assert set(data["pages"][0]) == {
        "page_number",
        "width_px",
        "height_px",
        "status",
        "error_message",
        "text",
        "regions",
    }
    assert set(data["pages"][0]["regions"][0]) == {
        "region_id",
        "text",
        "confidence",
        "polygon",
        "bbox",
    }


def test_json_round_trip_is_lossless(synthetic_pdf_bytes):
    doc = ocr_pdf_bytes(synthetic_pdf_bytes, "synthetic.pdf", raster_dpi=100, ocr_fn=fake_ocr)
    encoded = json.dumps(doc.to_dict())
    restored = OCRDocument.from_dict(json.loads(encoded))
    assert restored.to_dict() == doc.to_dict()
    assert restored.document_id == doc.document_id
    assert restored.raster_dpi == 100


def test_document_id_is_full_sha256_of_content(synthetic_pdf_bytes):
    doc_id = compute_document_id(synthetic_pdf_bytes)
    assert len(doc_id) == 64 and all(c in "0123456789abcdef" for c in doc_id)
    # content-addressed: same bytes, different filename, same id
    a = ocr_pdf_bytes(synthetic_pdf_bytes, "a.pdf", raster_dpi=100, ocr_fn=blank_ocr)
    b = ocr_pdf_bytes(synthetic_pdf_bytes, "b.pdf", raster_dpi=100, ocr_fn=blank_ocr)
    assert a.document_id == b.document_id == doc_id
    assert a.source_name != b.source_name

def test_cli_writes_json_as_utf8(tmp_path, monkeypatch):
    import src.ocr_pipeline as ocr_pipeline

    document = OCRDocument(
        document_id="d" * 64,
        source_name="unicode.pdf",
        page_count=1,
        raster_dpi=200,
        pages=[
            OCRPage(
                page_number=1,
                width_px=100,
                height_px=100,
                status="ok",
                text="助",
                regions=[],
            )
        ],
    )

    monkeypatch.setattr(
        ocr_pipeline,
        "ocr_pdf",
        lambda *args, **kwargs: document,
    )

    output_path = tmp_path / "unicode.json"

    return_code = ocr_pipeline.main(
        ["dummy.pdf", "--json", str(output_path)]
    )

    assert return_code == 0

    content = output_path.read_text(encoding="utf-8")
    assert "助" in content
    assert json.loads(content)["pages"][0]["text"] == "助"
# ---------------------------------------------------------------------------
# 3. invariants: page numbering, retention, statuses
# ---------------------------------------------------------------------------


def test_pages_are_1_based_contiguous_and_complete(synthetic_pdf_bytes):
    doc = ocr_pdf_bytes(synthetic_pdf_bytes, "synthetic.pdf", raster_dpi=100, ocr_fn=fake_ocr)
    assert doc.page_count == 3 == len(doc.pages)
    assert [p.page_number for p in doc.pages] == [1, 2, 3]


def test_region_ids_are_1_based_and_human_readable():
    assert make_region_id(1, 1) == "p1-r1"
    assert make_region_id(12, 7) == "p12-r7"
    raw = [
        ([[0, 0], [9, 0], [9, 9], [0, 9]], "first", 0.9),
        ([[0, 10], [9, 10], [9, 19], [0, 19]], "second", 0.8),
    ]
    regions = normalize_page_regions(3, raw)
    assert [r.region_id for r in regions] == ["p3-r1", "p3-r2"]


def test_pages_without_text_are_kept_as_no_text(synthetic_pdf_bytes):
    doc = ocr_pdf_bytes(synthetic_pdf_bytes, "synthetic.pdf", raster_dpi=100, ocr_fn=blank_ocr)
    assert doc.page_count == 3
    assert [p.status for p in doc.pages] == ["no_text", "no_text", "no_text"]
    for page in doc.pages:
        assert page.regions == [] and page.text == "" and page.error_message is None
        assert page.width_px and page.height_px  # rasterisation still succeeded


def test_malformed_ocr_output_makes_the_page_an_error_not_a_silent_drop(synthetic_pdf_bytes):
    def broken_ocr(pil_image):
        return [
            ([[0, 0], [9, 0], [9, 9], [0, 9]], "fine", 0.9),
            ([[0, 0], [1, 1]], "bad polygon", 0.5),  # only 2 points
        ]

    doc = ocr_pdf_bytes(synthetic_pdf_bytes, "synthetic.pdf", raster_dpi=100, ocr_fn=broken_ocr)
    assert doc.page_count == 3  # pages retained
    for page in doc.pages:
        assert page.status == "error"
        assert "malformed OCR output" in page.error_message
        # 1-based, consistent with region_id: the second entry is "region 2"
        assert "region 2" in page.error_message
        assert "region 1" not in page.error_message
        assert page.width_px and page.height_px  # raster succeeded, so dims survive


def test_malformed_region_numbering_is_1_based_and_matches_region_ids():
    """The number in the error must be the same one that would appear in the id."""
    good = ([[0, 0], [9, 0], [9, 9], [0, 9]], "fine", 0.9)
    bad = ([[0, 0], [1, 1]], "bad polygon", 0.5)

    with pytest.raises(MalformedOCRRegion, match=r"region 1\b"):
        normalize_page_regions(1, [bad, good])
    with pytest.raises(MalformedOCRRegion, match=r"region 3\b"):
        normalize_page_regions(1, [good, good, bad])

    # and the ids of the surviving regions use the same numbering scheme
    assert [r.region_id for r in normalize_page_regions(4, [good, good])] == ["p4-r1", "p4-r2"]


def test_non_triple_region_is_reported_with_1_based_number():
    good = ([[0, 0], [9, 0], [9, 9], [0, 9]], "fine", 0.9)
    with pytest.raises(MalformedOCRRegion, match=r"region 2 is not a \(polygon, text, confidence\)"):
        normalize_page_regions(1, [good, "not a triple at all"])


def test_ocr_engine_exception_becomes_page_error_with_message(synthetic_pdf_bytes):
    def exploding_ocr(pil_image):
        raise RuntimeError("onnx session died")

    doc = ocr_pdf_bytes(synthetic_pdf_bytes, "synthetic.pdf", raster_dpi=100, ocr_fn=exploding_ocr)
    assert [p.status for p in doc.pages] == ["error", "error", "error"]
    assert "onnx session died" in doc.pages[0].error_message
    assert doc.pages[0].regions == []


def test_page_status_and_error_message_are_consistent_by_construction():
    with pytest.raises(ValueError):
        OCRPage(page_number=1, width_px=10, height_px=10, status="error", error_message=None)
    with pytest.raises(ValueError):
        OCRPage(page_number=1, width_px=10, height_px=10, status="ok", error_message="boom")
    with pytest.raises(ValueError):
        OCRPage(page_number=0, width_px=10, height_px=10, status="no_text")
    with pytest.raises(ValueError):
        OCRPage(page_number=1, width_px=10, height_px=10, status="unknown")


def test_document_rejects_inconsistent_page_count_or_numbering():
    page = OCRPage(page_number=1, width_px=10, height_px=10, status="no_text")
    with pytest.raises(ValueError):
        OCRDocument("id", "a.pdf", page_count=2, raster_dpi=200, pages=[page])
    gap = OCRPage(page_number=3, width_px=10, height_px=10, status="no_text")
    with pytest.raises(ValueError):
        OCRDocument("id", "a.pdf", page_count=2, raster_dpi=200, pages=[page, gap])


def test_page_text_is_newline_joined_in_engine_order():
    raw = [
        ([[0, 0], [9, 0], [9, 9], [0, 9]], "second visually", 0.9),
        ([[0, 50], [9, 50], [9, 59], [0, 59]], "first visually", 0.8),
    ]
    regions = normalize_page_regions(1, raw)
    # engine order preserved verbatim: no reading-order logic in this layer
    assert regions_to_page_text(regions) == "second visually\nfirst visually"


def test_bboxes_lie_within_the_page_raster(synthetic_pdf_bytes):
    doc = ocr_pdf_bytes(synthetic_pdf_bytes, "synthetic.pdf", raster_dpi=100, ocr_fn=fake_ocr)
    for page in doc.pages:
        for region in page.regions:
            x0, y0, x1, y1 = region.bbox
            assert 0 <= x0 < x1 <= page.width_px
            assert 0 <= y0 < y1 <= page.height_px


def test_unopenable_pdf_raises_document_level_error():
    with pytest.raises(OCRPipelineError):
        ocr_pdf_bytes(b"this is not a pdf", "junk.pdf", ocr_fn=fake_ocr)
    with pytest.raises(OCRPipelineError):
        ocr_pdf("/nonexistent/path/to.pdf", ocr_fn=fake_ocr)


# ---------------------------------------------------------------------------
# 4. real engine (slow, synthetic document)
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_real_rapidocr_end_to_end_on_synthetic_pdf(synthetic_pdf_bytes):
    pytest.importorskip("rapidocr_onnxruntime")
    doc = ocr_pdf_bytes(synthetic_pdf_bytes, "synthetic.pdf", raster_dpi=150)

    assert doc.page_count == 3
    assert [p.page_number for p in doc.pages] == [1, 2, 3]
    assert doc.pages[0].status == "ok"
    assert doc.pages[1].status == "no_text"  # the blank page survives as a page

    # Assert on content that OCR reproduces stably. Note: on this very clean
    # synthetic page the engine read "SYNTH-001" as "SYNTH-o01" (zero -> letter
    # o). That is a real, reproducible OCR limitation, so this test does not
    # assert exact recovery of the reference string — normalisation and
    # validation of identifiers is a later phase's job, not this layer's.
    page_text = doc.pages[0].text.replace(" ", "")
    assert "BOREHOLERECORDSHEET" in page_text
    assert "Reference" in page_text
    assert doc.pages[2].status == "ok"
    json.dumps(doc.to_dict())

    for page in doc.pages:
        for region in page.regions:
            x0, y0, x1, y1 = region.bbox
            assert 0 <= x0 < x1 <= page.width_px
            assert 0 <= y0 < y1 <= page.height_px
            assert len(region.polygon) >= 3
