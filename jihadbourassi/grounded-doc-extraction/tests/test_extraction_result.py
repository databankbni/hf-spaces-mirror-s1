"""Tests for the extraction output contract.

Pure data: no OCR, no PDFs, no models.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.extraction_result import (  # noqa: E402
    EvidenceRef,
    ExtractionCandidate,
    ExtractionResult,
    FieldExtraction,
    SourceEvidence,
    are_regions_traceable,
    evidence_matches_source,
    is_value_grounded,
    source_text_for,
)


def ev(region_id="p1-r1", text="E335244.0", page=1, conf=0.98):
    return EvidenceRef(region_id=region_id, page_number=page, bbox=[1.0, 2.0, 3.0, 4.0],
                       text=text, confidence=conf)


def cand(value=335244.0, value_text="335244.0", provenance="document_body",
         region_id="p1-r1", text="E335244.0", rule="labelled_in_region", score=3.0):
    return ExtractionCandidate(
        value_text=value_text,
        value=value,
        evidence=[ev(region_id=region_id, text=text)],
        provenance=provenance,
        match_rule=rule,
        score=score,
    )


def accepted_field(**overrides):
    c = overrides.pop("candidate", cand())
    kwargs = dict(
        name="easting",
        raw_value=c.value,
        accepted_value=c.value,
        status="accepted",
        reason=None,
        evidence=c.evidence,
        evidence_traceable=True,
        value_grounded=True,
        validation="passed",
        provenance=c.provenance,
        candidates=[c],
    )
    kwargs.update(overrides)
    return FieldExtraction(**kwargs)


# --- grounding semantics ---------------------------------------------------


def source(region_id="p1-r1", text="E335244.0", page=1, bbox=(1.0, 2.0, 3.0, 4.0)):
    return SourceEvidence(region_id=region_id, page_number=page, bbox=tuple(bbox), text=text)


def lookup(*sources):
    return {s.region_id: s for s in sources}


def test_grounding_uses_value_text_not_parsed_number_formatting():
    # OCR says "E335244.0"; value_text is the substring "335244.0".
    assert is_value_grounded("335244.0", "E335244.0") is True
    assert is_value_grounded("15.00", "15.00 END OF BOREHOLE") is True

    # The discriminating case: a value whose parsed form is NOT how OCR wrote it.
    # value_text "1,250" is supported by the evidence; str(1250.0) is not, and
    # grounding must be judged on the OCR text rather than Python's formatting.
    assert is_value_grounded("1,250", "Total Depth: 1,250 m") is True
    assert is_value_grounded(str(1250.0), "Total Depth: 1,250 m") is False
    assert is_value_grounded(str(1250), "Total Depth: 1,250 m") is False


def test_grounding_tolerates_ocr_spacing_but_not_absence():
    assert is_value_grounded("335244.0", "E 335 244.0") is True
    assert is_value_grounded("335244.0", "Northing 858196.0") is False
    assert is_value_grounded("", "anything") is False


def test_traceability_requires_every_cited_region_to_exist():
    src = lookup(source("p1-r1", "E335244.0"), source("p1-r2", "Easting"))
    assert are_regions_traceable([ev("p1-r1", "E335244.0"), ev("p1-r2", "Easting")], src) is True
    assert are_regions_traceable([ev("p9-r9", "invented")], src) is False
    assert are_regions_traceable([], src) is False


def test_traceability_rejects_fabricated_text_on_a_real_region_id():
    """A real id with invented text must not be traceable."""
    src = lookup(source("p1-r1", "E335244.0"))
    forged = ev("p1-r1", "Easting 521334")          # real region, invented contents
    assert evidence_matches_source(forged, src["p1-r1"]) is False
    assert are_regions_traceable([forged], src) is False


def test_traceability_rejects_fabricated_bbox_or_page():
    src = lookup(source("p1-r1", "E335244.0", page=1, bbox=(1.0, 2.0, 3.0, 4.0)))
    moved = EvidenceRef("p1-r1", 1, [10.0, 20.0, 30.0, 40.0], "E335244.0", 0.98)
    other_page = EvidenceRef("p1-r1", 7, [1.0, 2.0, 3.0, 4.0], "E335244.0", 0.98)
    assert are_regions_traceable([moved], src) is False
    assert are_regions_traceable([other_page], src) is False
    # a tight tolerance still admits float noise from serialisation
    jittered = EvidenceRef("p1-r1", 1, [1.0000000001, 2.0, 3.0, 4.0], "E335244.0", 0.98)
    assert are_regions_traceable([jittered], src) is True


def test_fabricated_evidence_text_cannot_ground_a_value():
    """The forged copy contains the prediction; the source region does not."""
    src = lookup(source("p1-r1", "Northing 858196.0"))
    forged = ev("p1-r1", "Easting 521334")
    # grounding is judged against the SOURCE text, not the citation's own copy
    assert is_value_grounded("521334", forged.text) is True          # the trap
    assert is_value_grounded("521334", source_text_for(forged, src)) is False
    assert are_regions_traceable([forged], src) is False


# --- closed vocabularies ---------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"status": "ambiguous"},          # not in the closed status vocabulary
        {"validation": "in_range"},       # replaced by passed/failed/not_checked
        {"provenance": "registry"},       # not a valid provenance
    ],
)
def test_invalid_vocabulary_is_rejected(kwargs):
    with pytest.raises(ValueError):
        accepted_field(**kwargs)


def test_invalid_reason_is_rejected():
    with pytest.raises(ValueError):
        FieldExtraction(name="easting", raw_value=None, accepted_value=None,
                        status="not_found", reason="because_i_said_so")


def test_candidate_rejects_bad_rule_provenance_or_missing_evidence():
    with pytest.raises(ValueError):
        ExtractionCandidate("1", 1.0, [ev()], "document_body", "telepathy", 1.0)
    with pytest.raises(ValueError):
        ExtractionCandidate("1", 1.0, [ev()], "registry_value", "labelled_in_region", 1.0)
    with pytest.raises(ValueError):
        ExtractionCandidate("1", 1.0, [], "document_body", "labelled_in_region", 1.0)


# --- accepted-result invariants -------------------------------------------


def test_a_well_formed_accepted_field_is_constructible():
    f = accepted_field()
    assert f.status == "accepted" and f.accepted_value == 335244.0


@pytest.mark.parametrize(
    "overrides",
    [
        {"accepted_value": None},                       # accepted needs a value
        {"accepted_value": 999.0},                      # must equal raw_value
        {"value_grounded": False},                      # must be grounded
        {"evidence_traceable": False},                  # must be traceable
        {"validation": "failed"},                       # must have passed
        {"validation": "not_checked"},
        {"reason": "wrapper_only"},                     # accepted carries no reason
        {"evidence": []},                               # accepted needs evidence
    ],
)
def test_accepted_requires_the_full_set_of_guarantees(overrides):
    with pytest.raises(ValueError):
        accepted_field(**overrides)


def test_only_document_body_provenance_can_be_accepted():
    for provenance in ("bgs_wrapper", "unknown"):
        c = cand(provenance=provenance)
        with pytest.raises(ValueError):
            accepted_field(candidate=c, provenance=provenance)


def test_non_accepted_status_requires_null_value_and_a_reason():
    c = cand()
    with pytest.raises(ValueError):  # value present but not accepted
        FieldExtraction(name="easting", raw_value=c.value, accepted_value=c.value,
                        status="unsupported", reason="wrapper_only",
                        evidence=c.evidence, candidates=[c])
    with pytest.raises(ValueError):  # no reason given
        FieldExtraction(name="easting", raw_value=None, accepted_value=None,
                        status="not_found", reason=None)


# --- one-selected-candidate consistency -----------------------------------


def test_evidence_value_and_provenance_must_describe_one_candidate():
    body = cand(value=335244.0, region_id="p2-r14", text="E335244.0")
    wrapper = cand(value=335240.0, value_text="335240", provenance="bgs_wrapper",
                   region_id="p2-r3", text="British National Grid (27700): 335240,858190",
                   rule="packed_pair", score=1.0)

    # the forbidden mix: wrapper's value with the body candidate's evidence
    with pytest.raises(ValueError, match="one candidate"):
        FieldExtraction(
            name="easting", raw_value=wrapper.value, accepted_value=None,
            status="unsupported", reason="ambiguous_candidates",
            evidence=body.evidence, provenance=body.provenance,
            candidates=[body, wrapper],
        )

    # provenance taken from the other candidate is equally forbidden
    with pytest.raises(ValueError, match="one candidate"):
        FieldExtraction(
            name="easting", raw_value=body.value, accepted_value=None,
            status="unsupported", reason="ambiguous_candidates",
            evidence=body.evidence, provenance="bgs_wrapper",
            candidates=[body, wrapper],
        )

    # swapping only the ANCHOR must also fail: the value would be evidence of
    # something else while claiming the same value region
    anchor_a = ev("p2-r13", "Easting")
    anchor_b = ev("p2-r99", "Northing")
    with_anchor_a = ExtractionCandidate(
        value_text="335244.0", value=335244.0,
        evidence=[ev("p2-r14", "E335244.0"), anchor_a],
        provenance="document_body", match_rule="labelled_neighbour", score=2.5,
    )
    with pytest.raises(ValueError, match="full evidence list"):
        FieldExtraction(
            name="easting", raw_value=335244.0, accepted_value=None,
            status="unsupported", reason="unit_unknown",
            evidence=[ev("p2-r14", "E335244.0"), anchor_b],   # anchor B, not A
            provenance="document_body", candidates=[with_anchor_a],
        )

    # dropping the anchor from the evidence list is equally inconsistent
    with pytest.raises(ValueError, match="full evidence list"):
        FieldExtraction(
            name="easting", raw_value=335244.0, accepted_value=None,
            status="unsupported", reason="unit_unknown",
            evidence=[ev("p2-r14", "E335244.0")],
            provenance="document_body", candidates=[with_anchor_a],
        )

    # the matching full list is accepted
    ok_two = FieldExtraction(
        name="easting", raw_value=335244.0, accepted_value=None,
        status="unsupported", reason="unit_unknown",
        evidence=[ev("p2-r14", "E335244.0"), anchor_a],
        provenance="document_body", candidates=[with_anchor_a],
    )
    assert [e.region_id for e in ok_two.evidence] == ["p2-r14", "p2-r13"]

    # consistent selection is fine
    ok = FieldExtraction(
        name="easting", raw_value=wrapper.value, accepted_value=None,
        status="unsupported", reason="wrapper_only",
        evidence=wrapper.evidence, provenance="bgs_wrapper",
        candidates=[body, wrapper],
    )
    assert ok.raw_value == 335240.0 and ok.evidence[0].region_id == "p2-r3"


# --- serialisation ---------------------------------------------------------


def test_result_json_round_trip_is_lossless():
    result = ExtractionResult(
        document_id="a" * 64,
        source_name="doc.pdf",
        method="expert",
        extractor_version="phase4-v1",
        config_id="b" * 64,
        raster_dpi=200,
        duration_ms=12,
        fields=[accepted_field()],
        error_pages=[4],
        no_text_pages=[2, 3],
    )
    encoded = json.dumps(result.to_dict())
    restored = ExtractionResult.from_dict(json.loads(encoded))
    assert restored.to_dict() == result.to_dict()
    assert restored.field("easting").accepted_value == 335244.0


def test_error_pages_and_no_text_pages_stay_separate():
    result = ExtractionResult(
        document_id="x", source_name="d.pdf", method="expert",
        extractor_version="phase4-v1", config_id="c", raster_dpi=200, duration_ms=1,
        fields=[], error_pages=[4], no_text_pages=[2, 3],
    )
    data = result.to_dict()
    assert data["error_pages"] == [4]
    assert data["no_text_pages"] == [2, 3]
    assert "unreadable_pages" not in data


def test_traceability_rejects_altered_whitespace_in_copied_text():
    src = lookup(source("p1-r1", "Easting  335244.0"))
    altered = ev("p1-r1", "Easting 335244.0")
    assert are_regions_traceable([altered], src) is False


def test_full_evidence_consistency_rejects_altered_whitespace():
    value = ev("p1-r1", "E335244.0")
    anchor = ev("p1-r2", "Easting  label")
    candidate = ExtractionCandidate(
        value_text="335244.0", value=335244.0,
        evidence=[value, anchor], provenance="document_body",
        match_rule="labelled_neighbour", score=2.0,
    )
    altered_anchor = ev("p1-r2", "Easting label")
    with pytest.raises(ValueError, match="full evidence list"):
        FieldExtraction(
            name="easting", raw_value=335244.0, accepted_value=None,
            status="unsupported", reason="ambiguous_candidates",
            evidence=[value, altered_anchor], provenance="document_body",
            candidates=[candidate],
        )
