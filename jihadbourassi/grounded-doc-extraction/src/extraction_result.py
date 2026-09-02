"""Extraction output contract.

This module is the contract every extraction method must produce, starting with
the Phase 4 expert extractor. It knows nothing about PDFs, OCR engines, BGS, or
any particular extraction strategy — it only fixes the shape of a result and the
invariants that make that result trustworthy.

Two ideas carry most of the weight:

`raw_value` vs `accepted_value`
    `raw_value` is what the method produced. `accepted_value` is what the system
    is willing to propagate downstream. A rejected prediction is preserved for
    analysis, never erased.

One selected candidate
    A FieldExtraction describes exactly ONE candidate. `raw_value`, `evidence`,
    `provenance`, `validation` and `accepted_value` all refer to that same
    candidate. They can never be mixed across candidates — that would make the
    evidence a description of something other than the value. Other candidates
    stay visible in `candidates`, for inspection only.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Literal

EXTRACTOR_VERSION = "phase4-v1"

# --- closed vocabularies ---------------------------------------------------

Provenance = Literal["document_body", "bgs_wrapper", "unknown"]
VALID_PROVENANCES: tuple[str, ...] = ("document_body", "bgs_wrapper", "unknown")

FieldStatus = Literal[
    "accepted",
    "unsupported",
    "out_of_range",
    "not_found",
    "context_limit_exceeded",
    "extraction_error",
]
VALID_STATUSES: tuple[str, ...] = (
    "accepted",
    "unsupported",
    "out_of_range",
    "not_found",
    "context_limit_exceeded",
    "extraction_error",
)

Validation = Literal["passed", "failed", "not_checked"]
VALID_VALIDATIONS: tuple[str, ...] = ("passed", "failed", "not_checked")

# Why a value was not accepted. None only when status == "accepted".
VALID_REASONS: tuple[str, ...] = (
    "no_anchor",
    "no_value_near_anchor",
    "ambiguous_candidates",
    "wrapper_only",
    "provenance_unknown",
    "value_not_in_evidence",
    "evidence_not_traceable",
    "out_of_configured_range",
    "validation_failed",
    "unsupported_unit",
    "unit_unknown",
    "multiple_entities",
    "exception",
)

VALID_MATCH_RULES: tuple[str, ...] = (
    "labelled_in_region",
    "labelled_neighbour",
    "packed_pair",
)

# Tolerance for comparing a copied bbox against the source bbox.
BBOX_TOLERANCE = 1e-6


# ---------------------------------------------------------------------------
# grounding and traceability
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceEvidence:
    """The authoritative contents of one source region.

    A deliberately generic shape so this module stays independent of the OCR
    classes: the caller (the extractor) builds the lookup from whatever document
    representation it holds.
    """

    region_id: str
    page_number: int
    bbox: tuple[float, ...]
    text: str


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def evidence_matches_source(ref: "EvidenceRef", source: SourceEvidence) -> bool:
    """Does a copied EvidenceRef agree with the source region it points at?

    An EvidenceRef carries a *copy* of the region's text and bbox so a result can
    stand alone. That copy is exactly what a fabricated citation would forge, so
    every provenance-critical field is compared back against the source.
    """
    if ref.region_id != source.region_id:
        return False
    if ref.page_number != source.page_number:
        return False
    if ref.text != source.text:
        return False
    if len(ref.bbox) != len(source.bbox):
        return False
    return all(
        math.isclose(a, b, rel_tol=0.0, abs_tol=BBOX_TOLERANCE)
        for a, b in zip(ref.bbox, source.bbox)
    )


def are_regions_traceable(
    evidence: list["EvidenceRef"], source_lookup: dict[str, SourceEvidence]
) -> bool:
    """Every cited region must exist AND its copied contents must match the source.

    Checking only that a region_id exists is too weak: a fabricated citation can
    reuse a real id while inventing the text, and grounding checked against that
    invented text would then pass. Traceability is what makes grounding mean
    something, so it verifies the copy.
    """
    if not evidence:
        return False
    for ref in evidence:
        source = source_lookup.get(ref.region_id)
        if source is None or not evidence_matches_source(ref, source):
            return False
    return True


def source_text_for(
    ref: "EvidenceRef", source_lookup: dict[str, SourceEvidence]
) -> str | None:
    """The authoritative text of a cited region, or None if it does not resolve."""
    source = source_lookup.get(ref.region_id)
    return None if source is None else source.text


def is_value_grounded(value_text: str, source_text: str | None) -> bool:
    """Is the candidate's OCR-supported text present in the SOURCE region text?

    Two deliberate choices:

    * checked against `value_text` — the substring actually taken from OCR — and
      never against str(parsed_value), whose formatting is Python's, not the
      document's;
    * checked against the source region's own text, never against the copy inside
      an EvidenceRef, so a forged copy cannot ground a value.
    """
    if not value_text or source_text is None:
        return False
    haystack, needle = _collapse(source_text), _collapse(value_text)
    if needle in haystack:
        return True
    # OCR frequently inserts spaces inside a number; compare space-free forms too.
    return needle.replace(" ", "") in haystack.replace(" ", "")


# ---------------------------------------------------------------------------
# contract
# ---------------------------------------------------------------------------


@dataclass
class EvidenceRef:
    """A pointer into the normalized OCR document, plus a copy of what it says.

    `region_id` keeps the result re-linkable to the OCRDocument; the copied
    text/bbox make the result self-contained for serialisation and display.
    """

    region_id: str
    page_number: int
    bbox: list[float]
    text: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "region_id": self.region_id,
            "page_number": self.page_number,
            "bbox": [float(v) for v in self.bbox],
            "text": self.text,
            "confidence": float(self.confidence),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceRef":
        return cls(
            region_id=str(data["region_id"]),
            page_number=int(data["page_number"]),
            bbox=[float(v) for v in data["bbox"]],
            text=str(data["text"]),
            confidence=float(data["confidence"]),
        )


@dataclass
class ExtractionCandidate:
    """One thing the extractor thought the field might be, with why it thought so."""

    value_text: str
    value: float | str | None
    evidence: list[EvidenceRef]
    provenance: Provenance
    match_rule: str
    score: float
    score_parts: dict[str, float] = field(default_factory=dict)
    anchor_region_id: str | None = None
    anchor_text: str | None = None
    unit_text: str | None = None
    unit_kind: str = "not_applicable"  # metric | non_metric | unknown | not_applicable

    def __post_init__(self) -> None:
        if self.provenance not in VALID_PROVENANCES:
            raise ValueError(f"invalid provenance {self.provenance!r}")
        if self.match_rule not in VALID_MATCH_RULES:
            raise ValueError(f"invalid match_rule {self.match_rule!r}")
        if not self.evidence:
            raise ValueError("a candidate must cite at least its value region")

    @property
    def value_region_id(self) -> str:
        return self.evidence[0].region_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "value_text": self.value_text,
            "value": self.value,
            "evidence": [e.to_dict() for e in self.evidence],
            "provenance": self.provenance,
            "match_rule": self.match_rule,
            "score": float(self.score),
            "score_parts": {k: float(v) for k, v in self.score_parts.items()},
            "anchor_region_id": self.anchor_region_id,
            "anchor_text": self.anchor_text,
            "unit_text": self.unit_text,
            "unit_kind": self.unit_kind,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExtractionCandidate":
        return cls(
            value_text=str(data["value_text"]),
            value=data["value"],
            evidence=[EvidenceRef.from_dict(e) for e in data["evidence"]],
            provenance=data["provenance"],
            match_rule=str(data["match_rule"]),
            score=float(data["score"]),
            score_parts={k: float(v) for k, v in data.get("score_parts", {}).items()},
            anchor_region_id=data.get("anchor_region_id"),
            anchor_text=data.get("anchor_text"),
            unit_text=data.get("unit_text"),
            unit_kind=data.get("unit_kind", "not_applicable"),
        )


def _evidence_signature(evidence: list["EvidenceRef"]) -> tuple:
    """Identity of an evidence list, over the provenance-critical fields only."""
    return tuple(
        (
            ref.region_id,
            ref.page_number,
            tuple(round(float(v), 6) for v in ref.bbox),
            ref.text,
        )
        for ref in evidence
    )


@dataclass
class FieldExtraction:
    """The outcome for one field, describing exactly one selected candidate."""

    name: str
    raw_value: float | str | None
    accepted_value: float | str | None
    status: FieldStatus
    reason: str | None
    evidence: list[EvidenceRef] = field(default_factory=list)
    evidence_traceable: bool = False
    value_grounded: bool = False
    validation: Validation = "not_checked"
    provenance: Provenance = "unknown"
    candidates: list[ExtractionCandidate] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise ValueError(f"invalid status {self.status!r}")
        if self.validation not in VALID_VALIDATIONS:
            raise ValueError(f"invalid validation {self.validation!r}")
        if self.provenance not in VALID_PROVENANCES:
            raise ValueError(f"invalid provenance {self.provenance!r}")
        if self.reason is not None and self.reason not in VALID_REASONS:
            raise ValueError(f"invalid reason {self.reason!r}")

        if self.status == "accepted":
            if self.accepted_value is None:
                raise ValueError("status='accepted' requires a non-null accepted_value")
            if self.accepted_value != self.raw_value:
                raise ValueError("accepted_value must be the selected candidate's raw_value")
            if self.provenance != "document_body":
                raise ValueError("only document_body evidence may be accepted")
            if not (self.value_grounded and self.evidence_traceable):
                raise ValueError("accepted results must be grounded and traceable")
            if self.validation != "passed":
                raise ValueError("accepted results require validation='passed'")
            if self.reason is not None:
                raise ValueError("accepted results carry no reason")
            if not self.evidence:
                raise ValueError("accepted results require evidence")
        else:
            if self.accepted_value is not None:
                raise ValueError(f"status={self.status!r} requires accepted_value=None")
            if self.reason is None:
                raise ValueError(f"status={self.status!r} requires a reason")

        # One-selected-candidate consistency: the reported value, provenance and
        # the COMPLETE evidence list must all come from a single candidate in
        # `candidates`. Matching only the first region would allow an anchor to be
        # swapped for a different one, silently changing what the value is
        # evidence *of*.
        if self.evidence:
            wanted = _evidence_signature(self.evidence)
            match = [
                c
                for c in self.candidates
                if _evidence_signature(c.evidence) == wanted
                and c.provenance == self.provenance
                and c.value == self.raw_value
            ]
            if not match:
                raise ValueError(
                    "raw_value, provenance and the full evidence list must all describe "
                    "one candidate present in candidates "
                    f"(cited regions {[e.region_id for e in self.evidence]})"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "raw_value": self.raw_value,
            "accepted_value": self.accepted_value,
            "status": self.status,
            "reason": self.reason,
            "evidence": [e.to_dict() for e in self.evidence],
            "evidence_traceable": self.evidence_traceable,
            "value_grounded": self.value_grounded,
            "validation": self.validation,
            "provenance": self.provenance,
            "candidates": [c.to_dict() for c in self.candidates],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FieldExtraction":
        return cls(
            name=str(data["name"]),
            raw_value=data["raw_value"],
            accepted_value=data["accepted_value"],
            status=data["status"],
            reason=data["reason"],
            evidence=[EvidenceRef.from_dict(e) for e in data["evidence"]],
            evidence_traceable=bool(data["evidence_traceable"]),
            value_grounded=bool(data["value_grounded"]),
            validation=data["validation"],
            provenance=data["provenance"],
            candidates=[ExtractionCandidate.from_dict(c) for c in data["candidates"]],
        )


@dataclass
class ExtractionResult:
    """All fields for one document, plus what could not be read.

    `error_pages` and `no_text_pages` stay separate: a page OCR could not read is
    a different claim from a page that genuinely held no text, and collapsing
    them would let "not found" hide a failure.
    """

    document_id: str
    source_name: str
    method: str
    extractor_version: str
    config_id: str
    raster_dpi: int
    duration_ms: int
    fields: list[FieldExtraction] = field(default_factory=list)
    error_pages: list[int] = field(default_factory=list)
    no_text_pages: list[int] = field(default_factory=list)

    def field(self, name: str) -> FieldExtraction:
        for item in self.fields:
            if item.name == name:
                return item
        raise KeyError(name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "source_name": self.source_name,
            "method": self.method,
            "extractor_version": self.extractor_version,
            "config_id": self.config_id,
            "raster_dpi": self.raster_dpi,
            "duration_ms": self.duration_ms,
            "fields": [f.to_dict() for f in self.fields],
            "error_pages": list(self.error_pages),
            "no_text_pages": list(self.no_text_pages),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExtractionResult":
        return cls(
            document_id=str(data["document_id"]),
            source_name=str(data["source_name"]),
            method=str(data["method"]),
            extractor_version=str(data["extractor_version"]),
            config_id=str(data["config_id"]),
            raster_dpi=int(data["raster_dpi"]),
            duration_ms=int(data["duration_ms"]),
            fields=[FieldExtraction.from_dict(f) for f in data["fields"]],
            error_pages=[int(p) for p in data["error_pages"]],
            no_text_pages=[int(p) for p in data["no_text_pages"]],
        )
