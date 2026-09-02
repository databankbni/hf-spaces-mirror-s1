"""Expert extractor behaviour tests.

Every fixture is a hand-built OCRDocument. No PDF, no OCR engine, no model:
the whole file should run in well under a second.
"""

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.domain_config import config_from_dict, load_config  # noqa: E402
from src.expert_extractor import extract  # noqa: E402
from src.ocr_document import OCRDocument, OCRPage, OCRRegion, make_region_id  # noqa: E402

PAGE_W, PAGE_H = 1654, 2339


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def region(region_id, text, x0, y0, x1, y1, conf=0.97):
    return OCRRegion.from_ocr(
        region_id=region_id,
        polygon=[[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
        text=text,
        confidence=conf,
    )


def page(specs, page_number=1, status="ok"):
    """specs: list of (text, x0, y0, x1, y1) or (text, x0, y0, x1, y1, conf)."""
    regions = [
        region(make_region_id(page_number, i + 1), *spec)
        for i, spec in enumerate(specs)
    ]
    return OCRPage(
        page_number=page_number,
        width_px=PAGE_W,
        height_px=PAGE_H,
        status=status if regions or status != "ok" else "no_text",
        error_message="simulated failure" if status == "error" else None,
        text="\n".join(r.text for r in regions),
        regions=regions,
    )


def document(pages, name="synthetic.pdf"):
    return OCRDocument(
        document_id="d" * 64,
        source_name=name,
        page_count=len(pages),
        raster_dpi=200,
        pages=pages,
    )


def one_page_doc(specs):
    return document([page(specs)])


# ---------------------------------------------------------------------------
# 1. basic match rules
# ---------------------------------------------------------------------------


def test_label_and_value_in_one_region(cfg):
    doc = one_page_doc([("Easting: 335244.0", 100, 200, 700, 250)])
    field = extract(doc, cfg).field("easting")
    assert field.status == "accepted"
    assert field.accepted_value == 335244.0
    assert field.provenance == "document_body"
    assert field.candidates[0].match_rule == "labelled_in_region"


def test_label_left_value_right(cfg):
    doc = one_page_doc([
        ("Northing", 100, 200, 300, 250),
        ("858196.0", 340, 202, 640, 252),
    ])
    field = extract(doc, cfg).field("northing")
    assert field.status == "accepted" and field.accepted_value == 858196.0
    assert field.evidence[0].region_id == "p1-r2"      # value region cited first
    assert field.evidence[1].region_id == "p1-r1"      # anchor region also cited


def test_label_above_value_below(cfg):
    doc = one_page_doc([
        ("Easting", 100, 200, 300, 250),
        ("335244.0", 105, 270, 400, 320),
    ])
    field = extract(doc, cfg).field("easting")
    assert field.status == "accepted" and field.accepted_value == 335244.0


def test_skewed_lines_still_join_via_overlap(cfg):
    # value baseline offset by 18px against a 50px-tall anchor: still overlapping
    doc = one_page_doc([
        ("Easting", 100, 200, 300, 250),
        ("335244.0", 340, 218, 640, 268),
    ])
    assert extract(doc, cfg).field("easting").status == "accepted"


# ---------------------------------------------------------------------------
# 2. provenance — candidate level, wrapper and body on the SAME page
# ---------------------------------------------------------------------------


def wrapper_and_body_page():
    """The BGS 623562 shape: wrapper metadata and log-body evidence, one page.

    The wrapper coordinate region sits next to an explicit BGS wrapper marker,
    which is what makes it wrapper evidence — naming a CRS is not enough.
    """
    return one_page_doc([
        ("BGSReference:623562", 100, 60, 600, 110),
        ("BritishNationalGrid(27700):335240,858190", 100, 120, 900, 170),
        ("Easting", 120, 900, 320, 950),
        ("E335244.0", 360, 900, 700, 950),
        ("Northing", 120, 980, 320, 1030),
        ("N858196.0", 360, 980, 700, 1030),
    ])


def test_wrapper_and_body_on_the_same_page_select_the_body_value(cfg):
    result = extract(wrapper_and_body_page(), cfg)

    easting = result.field("easting")
    assert easting.status == "accepted"
    assert easting.accepted_value == 335244.0          # body, not 335240
    assert easting.provenance == "document_body"

    provenances = {c.provenance for c in easting.candidates}
    assert "bgs_wrapper" in provenances                # wrapper candidate still visible
    wrapper = [c for c in easting.candidates if c.provenance == "bgs_wrapper"]
    assert any(c.value == 335240.0 for c in wrapper)

    northing = result.field("northing")
    assert northing.accepted_value == 858196.0


def test_selected_candidate_owns_value_evidence_and_provenance(cfg):
    """raw_value, evidence, provenance and accepted_value describe ONE candidate."""
    easting = extract(wrapper_and_body_page(), cfg).field("easting")

    selected = [
        c for c in easting.candidates
        if c.value_region_id == easting.evidence[0].region_id
        and c.value == easting.raw_value
        and c.provenance == easting.provenance
    ]
    assert len(selected) >= 1
    assert easting.raw_value == easting.accepted_value == selected[0].value
    assert easting.evidence[0].text == "E335244.0"      # evidence matches the value
    assert easting.raw_value != 335240.0                # never the wrapper's value


def test_packed_pair_alone_is_not_wrapper_provenance(cfg):
    """Format is a format signal only; provenance needs explicit lexical evidence."""
    doc = one_page_doc([("335240,858190", 100, 120, 600, 170)])
    field = extract(doc, cfg).field("easting")

    packed = [c for c in field.candidates if c.match_rule == "packed_pair"]
    assert packed, "the packed pair should still produce a candidate"
    assert all(c.provenance != "bgs_wrapper" for c in packed)
    assert all(c.provenance == "unknown" for c in packed)
    assert field.status == "unsupported"
    assert field.reason == "provenance_unknown"
    assert field.accepted_value is None
    assert field.raw_value == 335240.0                  # kept for diagnosis


def test_naming_a_crs_alone_does_not_make_a_candidate_wrapper(cfg):
    """A historical log may legitimately name its own grid."""
    doc = one_page_doc([("British National Grid: 335244,858196", 100, 120, 900, 170)])
    field = extract(doc, cfg).field("easting")

    assert field.candidates, "the packed pair should still produce a candidate"
    assert all(c.provenance != "bgs_wrapper" for c in field.candidates)
    assert field.reason == "provenance_unknown"


def test_wrapper_only_evidence_is_never_accepted(cfg):
    doc = one_page_doc([
        ("BGS Reference 623562", 100, 60, 600, 110),
        ("British National Grid (27700): 335240,858190", 100, 120, 900, 170),
    ])
    field = extract(doc, cfg).field("easting")
    assert field.status == "unsupported" and field.reason == "wrapper_only"
    assert field.accepted_value is None
    assert field.raw_value == 335240.0
    assert field.provenance == "bgs_wrapper"


# ---------------------------------------------------------------------------
# 3. weak anchors
# ---------------------------------------------------------------------------


def test_bare_symbol_and_number_are_not_paired_in_phase4(cfg):
    """Weak E/N pairing was removed: a letter beside a number is not evidence."""
    doc = one_page_doc([
        ("E", 100, 200, 140, 250),
        ("335244", 180, 200, 480, 250),
        ("N", 100, 280, 140, 330),
        ("858196", 180, 280, 480, 330),
    ])
    result = extract(doc, cfg)
    for name in ("easting", "northing"):
        field = result.field(name)
        assert field.candidates == []
        assert field.status == "not_found"
        assert field.reason == "no_anchor"
    assert all(
        c.match_rule != "weak_standalone_pair"
        for f in result.fields for c in f.candidates
    )


# ---------------------------------------------------------------------------
# 4. depth: terminator geometry and units
# ---------------------------------------------------------------------------


def test_end_of_borehole_selects_the_value_immediately_above(cfg):
    """Terminator anchor with the value above it; a bigger unrelated number ignored."""
    doc = one_page_doc([
        ("847.50", 1200, 400, 1500, 450),          # unrelated larger number elsewhere
        ("15.00", 130, 1500, 330, 1550),
        ("(m)", 360, 1500, 430, 1550),             # local metric evidence
        ("END OF BOREHOLE", 130, 1570, 700, 1620),
    ])
    field = extract(doc, cfg).field("final_depth")
    assert field.status == "accepted"
    assert field.accepted_value == 15.0
    assert field.evidence[0].text == "15.00"                     # value region
    assert field.evidence[1].text == "END OF BOREHOLE"           # anchor region
    assert field.candidates[0].unit_kind == "metric"
    assert all(c.value != 847.50 for c in field.candidates)      # unanchored number ignored


def test_end_of_borehole_value_selected_but_unit_unknown_without_unit_evidence(cfg):
    """Same geometry, no unit anywhere: the value is found but must not be accepted."""
    doc = one_page_doc([
        ("15.00", 130, 1500, 330, 1550),
        ("END OF BOREHOLE", 130, 1570, 700, 1620),
    ])
    field = extract(doc, cfg).field("final_depth")
    assert field.raw_value == 15.0                    # selection worked
    assert field.status == "unsupported"
    assert field.reason == "unit_unknown"
    assert field.accepted_value is None


def test_real_row_geometry_picks_the_depth_column_not_the_nearer_column(cfg):
    """Shaped like the real 623562 row:

        15.00        ...        END OF BOREHOLE        58.50

    58.50 is geometrically CLOSER to the anchor than 15.00, so a proximity radius
    would pick the wrong one. The `left` relation, bounded by a conservative
    centre-offset tolerance, resolves it. Slight vertical offsets mimic OCR.
    """
    doc = one_page_doc([
        ("Depth (m)", 120, 300, 340, 350),                  # same column as 15.00
        ("15.00", 130, 1502, 330, 1552),
        ("END OF BOREHOLE", 700, 1498, 1150, 1548),
        ("58.50", 1210, 1505, 1410, 1555),                  # nearer, wrong column
    ])
    field = extract(doc, cfg).field("final_depth")

    assert field.status == "accepted"
    assert field.accepted_value == 15.0
    assert field.evidence[0].text == "15.00"
    assert all(c.value != 58.50 for c in field.candidates), "the nearer column must not win"


def test_same_column_unit_header_supplies_metric_evidence(cfg):
    """The (m) header is far above the value but in the same column.

    Euclidean proximity would prefer the (ft) header in the adjacent column, so
    the fallback requires column alignment and searches upwards.
    """
    doc = one_page_doc([
        ("Depth (m)", 120, 300, 340, 350),                  # same column, far above
        ("Level (ft)", 1200, 300, 1420, 350),               # other column, decoy
        ("15.00", 130, 1502, 330, 1552),
        ("END OF BOREHOLE", 700, 1498, 1150, 1548),
    ])
    field = extract(doc, cfg).field("final_depth")

    assert field.status == "accepted"
    assert field.accepted_value == 15.0
    assert field.candidates[0].unit_kind == "metric"
    assert field.candidates[0].unit_text in {"m", "(m)"}


def test_metric_depth_via_suffix_is_accepted(cfg):
    doc = one_page_doc([("Final Depth: 25.40 m", 100, 200, 700, 250)])
    field = extract(doc, cfg).field("final_depth")
    assert field.status == "accepted" and field.accepted_value == 25.40
    assert field.candidates[0].unit_kind == "metric"


def test_explicit_feet_depth_is_rejected_without_conversion(cfg):
    doc = one_page_doc([("Final Depth: 50.00 ft", 100, 200, 700, 250)])
    field = extract(doc, cfg).field("final_depth")
    assert field.status == "unsupported" and field.reason == "unsupported_unit"
    assert field.accepted_value is None
    assert field.raw_value == 50.0            # preserved, never converted
    assert field.candidates[0].unit_text in {"ft", "ft."}


def test_depth_with_no_unit_evidence_is_unit_unknown(cfg):
    doc = one_page_doc([
        ("Final Depth", 100, 200, 400, 250),
        ("25.40", 440, 200, 640, 250),
    ])
    field = extract(doc, cfg).field("final_depth")
    assert field.status == "unsupported" and field.reason == "unit_unknown"
    assert field.accepted_value is None and field.raw_value == 25.40


def test_depth_without_any_anchor_is_not_found(cfg):
    doc = one_page_doc([
        ("Made ground", 100, 200, 400, 250),
        ("3.50", 440, 200, 640, 250),
        ("Stiff brown CLAY", 100, 300, 500, 350),
        ("12.75", 440, 300, 640, 350),
    ])
    field = extract(doc, cfg).field("final_depth")
    assert field.status == "not_found" and field.reason == "no_anchor"


# ---------------------------------------------------------------------------
# 5. validation, ambiguity, entities
# ---------------------------------------------------------------------------


def test_out_of_range_value_is_rejected_but_preserved(cfg):
    doc = one_page_doc([("Easting: 9999999", 100, 200, 700, 250)])
    field = extract(doc, cfg).field("easting")
    assert field.status == "out_of_range"
    assert field.reason == "out_of_configured_range"
    assert field.validation == "failed"
    assert field.accepted_value is None
    assert field.raw_value == 9999999.0


def test_two_close_scoring_distinct_values_abstain_as_ambiguous(cfg):
    doc = one_page_doc([
        ("Easting: 335244.0", 100, 200, 700, 250),
        ("Easting: 412345.6", 100, 300, 700, 350),
    ])
    field = extract(doc, cfg).field("easting")
    assert field.status == "unsupported" and field.reason == "ambiguous_candidates"
    assert field.accepted_value is None
    assert len({c.value for c in field.candidates}) == 2      # both stay visible


def test_borehole_id_is_accepted_verbatim_without_confusable_correction(cfg):
    doc = one_page_doc([("Borehole No: SYNTH-o01", 100, 200, 700, 250)])
    field = extract(doc, cfg).field("borehole_id")
    assert field.status == "accepted"
    assert field.accepted_value == "SYNTH-o01"     # no o -> 0 repair
    assert field.validation == "passed"


def test_exact_anchor_reads_a_bare_borehole_label_without_firing_on_lookalikes(cfg):
    """Real 623562 layout: an exact region "BOREHOLE" with its value nearby.

    Substring matching on a bare "borehole" would also fire on END OF BOREHOLE,
    BOREHOLERECORD and BOREHOLE1, so this anchor is configured match="exact".
    """
    doc = one_page_doc([
        ("BOREHOLE", 200, 300, 460, 350),
        ("129", 380, 338, 450, 370),
        ("BOREHOLERECORD", 200, 1400, 620, 1450),
        ("BOREHOLE1", 200, 1500, 520, 1550),
        ("END OF BOREHOLE", 200, 1900, 640, 1950),
    ])
    field = extract(doc, cfg).field("borehole_id")

    assert field.status == "accepted"
    assert field.accepted_value == "129"
    assert field.provenance == "document_body"
    assert field.evidence[0].text == "129"
    assert field.evidence[1].text == "BOREHOLE"          # the exact-matched anchor


def test_two_distinct_borehole_ids_abstain_as_multiple_entities(cfg):
    doc = one_page_doc([
        ("Borehole No: BH-1", 100, 200, 700, 250),
        ("Borehole No: BH-2", 100, 300, 700, 350),
    ])
    field = extract(doc, cfg).field("borehole_id")
    assert field.status == "unsupported" and field.reason == "multiple_entities"
    assert field.accepted_value is None


# ---------------------------------------------------------------------------
# 6. page statuses, config independence, serialisation
# ---------------------------------------------------------------------------


def test_error_and_no_text_pages_are_reported_separately(cfg):
    pages = [
        page([("Easting: 335244.0", 100, 200, 700, 250)], page_number=1),
        page([], page_number=2, status="no_text"),
        page([], page_number=3, status="error"),
        page([], page_number=4, status="no_text"),
    ]
    result = extract(document(pages), cfg)
    assert result.error_pages == [3]
    assert result.no_text_pages == [2, 4]
    assert result.field("easting").status == "accepted"   # readable page still works


def test_two_configs_with_different_ranges_give_different_results(cfg):
    doc = one_page_doc([("Easting: 335244.0", 100, 200, 700, 250)])
    assert extract(doc, cfg).field("easting").status == "accepted"

    narrowed = copy.deepcopy(cfg.data)
    narrowed["fields"]["easting"]["validation"]["max"] = 1000
    narrow_cfg = config_from_dict(narrowed)

    field = extract(doc, narrow_cfg).field("easting")
    assert field.status == "out_of_range"
    assert field.raw_value == 335244.0
    assert narrow_cfg.config_id != cfg.config_id          # identity tracks content


def test_result_carries_version_identity_and_serialises(cfg):
    result = extract(wrapper_and_body_page(), cfg)
    assert result.method == "expert"
    assert result.extractor_version == "phase4-v1"
    assert result.config_id == cfg.config_id and len(result.config_id) == 64
    assert result.raster_dpi == 200
    data = json.dumps(result.to_dict())
    assert json.loads(data)["fields"][0]["name"] in {
        "borehole_id", "easting", "northing", "final_depth"
    }


def test_every_cited_region_resolves_in_the_source_document(cfg):
    doc = wrapper_and_body_page()
    known = {r.region_id for p in doc.pages for r in p.regions}
    result = extract(doc, cfg)
    for field in result.fields:
        for ref in field.evidence:
            assert ref.region_id in known
        if field.status == "accepted":
            assert field.evidence_traceable and field.value_grounded


def test_exact_borehole_overlap_ignores_sheet_labels_across_pages(cfg):
    doc = document([
        page([
            ("BOREHOLE", 1250, 420, 1355, 448),
            ("129", 1260, 440, 1305, 468),
            ("Sheet1of2", 1260, 475, 1370, 500),
        ], page_number=1),
        page([
            ("BOREHOLE", 1248, 410, 1348, 432),
            ("129", 1255, 426, 1298, 454),
            ("Sheet2of2", 1255, 460, 1360, 485),
        ], page_number=2),
    ])
    field = extract(doc, cfg).field("borehole_id")
    assert field.status == "accepted"
    assert field.accepted_value == "129"
    assert {c.value for c in field.candidates} == {"129"}


def test_in_situ_text_does_not_mean_inches(cfg):
    doc = one_page_doc([
        ("(m)", 120, 300, 250, 340),
        ("in situ tests", 700, 1400, 980, 1450),
        ("15.00", 120, 1500, 300, 1540),
        ("END OF BOREHOLE", 500, 1495, 900, 1545),
    ])
    field = extract(doc, cfg).field("final_depth")
    assert field.status == "accepted"
    assert field.accepted_value == 15.0
    selected = next(c for c in field.candidates if c.value == 15.0 and c.provenance == "document_body")
    assert selected.unit_kind == "metric"
