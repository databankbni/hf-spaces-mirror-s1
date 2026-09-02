"""Verify SOBI catalogue values against OCR evidence in a scanned document.

This module solves a different problem from ``expert_extractor``:

    expert extractor:
        document -> infer field values

    document verifier:
        catalogue value -> search for supporting evidence in the document

The verifier is deliberately value-first. It does not require an exhaustive
list of field labels or document templates.

Important provenance rule
-------------------------

BGS/SOBI metadata may itself be printed in a wrapper around the historical
scan. Finding a catalogue value in that wrapper would be circular evidence.

The verifier therefore:

1. identifies OCR regions locally associated with configured BGS wrapper
   markers;
2. excludes those regions from verification;
3. searches the remaining document body for the best match;
4. abstains when the best available candidate is not sufficiently credible.

The output is intentionally independent from ExtractionResult because
"extracted value" and "catalogue verification" are different contracts.
"""

from __future__ import annotations

import math
import re

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Iterable

from .domain_config import DomainConfig
from .ocr_document import OCRDocument, OCRPage, OCRRegion


METHOD_NAME = "catalogue_verifier"
VERIFIER_VERSION = "0.3.0"


# ---------------------------------------------------------------------------
# Public field names
# ---------------------------------------------------------------------------


VERIFY_FIELD_NAMES = (
    "borehole_id",
    "easting",
    "northing",
    "final_depth",
)


CATALOGUE_KEYS = {
    "borehole_id": "reference",
    "easting": "easting",
    "northing": "northing",
    "final_depth": "length_m",
}


# ---------------------------------------------------------------------------
# Conservative matching thresholds
#
# These thresholds decide whether an OCR candidate is credible enough to be
# used as verification evidence. They do NOT decide whether the SOBI value is
# "correct".
# ---------------------------------------------------------------------------


REFERENCE_FUZZY_MIN_SCORE = 85.0

COORDINATE_MIN_SCORE = 70.0
COORDINATE_MAX_RELATIVE_DIFFERENCE = 0.02

DEPTH_MIN_SCORE = 60.0
DEPTH_MAX_RELATIVE_DIFFERENCE = 0.15


# ---------------------------------------------------------------------------
# Result contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerificationEvidence:
    """One authoritative OCR region supporting a verification match."""

    region_id: str
    page_number: int
    bbox: list[float]
    text: str
    confidence: float
    provenance: str = "document_body"

    def to_dict(self) -> dict[str, Any]:
        return {
            "region_id": self.region_id,
            "page_number": self.page_number,
            "bbox": list(self.bbox),
            "text": self.text,
            "confidence": self.confidence,
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class VerificationCandidate:
    """One possible document match for a catalogue value."""

    value: str | float
    value_text: str
    score: float
    difference: float | None
    evidence: VerificationEvidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "value_text": self.value_text,
            "score": self.score,
            "difference": self.difference,
            "evidence": self.evidence.to_dict(),
        }


@dataclass
class FieldVerification:
    """Verification result for one catalogue field."""

    name: str
    catalogue_value: Any
    matched_value: Any = None
    matched_text: str | None = None

    # 0..100 correspondence score.
    # This is NOT an accuracy probability.
    match_score: float | None = None

    # Numeric difference:
    # matched_value - catalogue_value
    difference: float | None = None

    status: str = "not_found"

    evidence: list[VerificationEvidence] = field(
        default_factory=list
    )

    candidates: list[VerificationCandidate] = field(
        default_factory=list
    )

    occurrence_count: int = 0

    ignored_wrapper_matches: int = 0

    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "catalogue_value": self.catalogue_value,
            "matched_value": self.matched_value,
            "matched_text": self.matched_text,
            "match_score": self.match_score,
            "difference": self.difference,
            "status": self.status,
            "evidence": [
                item.to_dict()
                for item in self.evidence
            ],
            "candidates": [
                item.to_dict()
                for item in self.candidates
            ],
            "occurrence_count": self.occurrence_count,
            "ignored_wrapper_matches": self.ignored_wrapper_matches,
            "reason": self.reason,
        }


@dataclass
class DocumentVerification:
    """Complete catalogue-vs-document verification result."""

    document_id: str
    source_name: str
    method: str
    verifier_version: str
    fields: list[FieldVerification]

    wrapper_region_ids: list[str] = field(
        default_factory=list
    )

    def field(
        self,
        name: str,
    ) -> FieldVerification:

        for item in self.fields:

            if item.name == name:
                return item

        raise KeyError(
            name
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "source_name": self.source_name,
            "method": self.method,
            "verifier_version": self.verifier_version,
            "fields": [
                item.to_dict()
                for item in self.fields
            ],
            "wrapper_region_ids": list(
                self.wrapper_region_ids
            ),
        }


# ---------------------------------------------------------------------------
# Internal page context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PageCtx:
    page: OCRPage
    width: float
    height: float

    @property
    def regions(
        self,
    ) -> list[OCRRegion]:
        return self.page.regions


def _iter_page_contexts(
    document: OCRDocument,
) -> Iterable[_PageCtx]:

    for page in document.pages:

        if page.status != "ok":
            continue

        yield _PageCtx(
            page=page,
            width=float(
                page.width_px or 1
            ),
            height=float(
                page.height_px or 1
            ),
        )


# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------


def _norm(
    value: Any,
) -> str:

    if value is None:
        return ""

    text = str(
        value
    ).upper()

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def _compact(
    value: Any,
) -> str:

    return re.sub(
        r"[^A-Z0-9]+",
        "",
        _norm(
            value
        ),
    )


def _similarity(
    left: Any,
    right: Any,
) -> float:

    a = _compact(
        left
    )

    b = _compact(
        right
    )

    if not a or not b:
        return 0.0

    return (
        SequenceMatcher(
            None,
            a,
            b,
        ).ratio()
        * 100.0
    )


# ---------------------------------------------------------------------------
# Geometry / provenance
# ---------------------------------------------------------------------------


def _centre(
    bbox: list[float],
) -> tuple[float, float]:

    return (
        (
            bbox[0]
            + bbox[2]
        )
        / 2,
        (
            bbox[1]
            + bbox[3]
        )
        / 2,
    )


def _normalised_distance(
    first: list[float],
    second: list[float],
    width: float,
    height: float,
) -> float:

    ax, ay = _centre(
        first
    )

    bx, by = _centre(
        second
    )

    dx = (
        (ax - bx)
        / width
        if width
        else 0.0
    )

    dy = (
        (ay - by)
        / height
        if height
        else 0.0
    )

    return math.sqrt(
        dx * dx
        + dy * dy
    )


def _wrapper_context(
    region: OCRRegion,
    ctx: _PageCtx,
    cfg: DomainConfig,
) -> str:

    radius = float(
        cfg.spatial(
            "provenance_neighbour_frac"
        )
    )

    limit = int(
        cfg.spatial(
            "provenance_max_neighbours"
        )
    )

    neighbours = []

    for other in ctx.regions:

        if (
            other.region_id
            == region.region_id
        ):
            continue

        distance = (
            _normalised_distance(
                region.bbox,
                other.bbox,
                ctx.width,
                ctx.height,
            )
        )

        if distance <= radius:

            neighbours.append(
                (
                    distance,
                    other,
                )
            )

    neighbours.sort(
        key=lambda item: item[0]
    )

    texts = [
        region.text
    ]

    texts.extend(
        other.text
        for _, other
        in neighbours[:limit]
    )

    return " ".join(
        _norm(
            text
        ).lower()
        for text in texts
    )


def _is_wrapper_region(
    region: OCRRegion,
    ctx: _PageCtx,
    cfg: DomainConfig,
) -> bool:

    context = (
        _wrapper_context(
            region,
            ctx,
            cfg,
        )
    )

    context_nospace = (
        context.replace(
            " ",
            "",
        )
    )

    for marker in cfg.wrapper_markers:

        marker_norm = (
            _norm(
                marker
            )
            .lower()
        )

        if not marker_norm:
            continue

        if (
            marker_norm
            in context
            or marker_norm.replace(
                " ",
                "",
            )
            in context_nospace
        ):

            return True

    return False


def classify_wrapper_regions(
    document: OCRDocument,
    cfg: DomainConfig,
) -> set[str]:

    wrapper_ids: set[
        str
    ] = set()

    for ctx in _iter_page_contexts(
        document
    ):

        for region in ctx.regions:

            if _is_wrapper_region(
                region,
                ctx,
                cfg,
            ):

                wrapper_ids.add(
                    region.region_id
                )

    return wrapper_ids


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def _evidence(
    page_number: int,
    region: OCRRegion,
    *,
    provenance: str,
) -> VerificationEvidence:

    return VerificationEvidence(
        region_id=region.region_id,
        page_number=page_number,
        bbox=[
            float(value)
            for value in region.bbox
        ],
        text=region.text,
        confidence=float(
            region.confidence
        ),
        provenance=provenance,
    )


# ---------------------------------------------------------------------------
# Numeric parsing
# ---------------------------------------------------------------------------


# A number may be attached to an OCR label:
#
#     E335244.0
#     N858196.0
#
# We therefore prevent only another DIGIT immediately before/after the
# numeric token. A preceding letter is allowed.
NUMERIC_RE = re.compile(
    r"""
    (?<!\d)
    [-+]?
    (?:
        \d{1,3}(?:,\d{3})+
        |
        \d+
    )
    (?:\.\d+)?
    (?!\d)
    """,
    re.VERBOSE,
)


DATE_RE = re.compile(
    r"""
    (?<!\d)
    \d{1,2}
    \s*
    [/-]
    \s*
    \d{1,2}
    \s*
    [/-]
    \s*
    \d{2,4}
    (?!\d)
    """,
    re.VERBOSE,
)


def _parse_numeric_token(
    token: str,
) -> float | None:

    cleaned = (
        token
        .strip()
        .replace(
            ",",
            "",
        )
    )

    try:

        return float(
            cleaned
        )

    except ValueError:

        return None


def _numeric_tokens(
    text: str,
) -> list[
    tuple[
        str,
        float,
    ]
]:

    values = []

    for match in NUMERIC_RE.finditer(
        text
    ):

        token = (
            match.group(
                0
            )
        )

        parsed = (
            _parse_numeric_token(
                token
            )
        )

        if parsed is None:
            continue

        values.append(
            (
                token,
                parsed,
            )
        )

    return values


def _format_numeric_for_match(
    value: float,
) -> str:

    if float(
        value
    ).is_integer():

        return str(
            int(
                value
            )
        )

    return (
        f"{value:.6f}"
        .rstrip(
            "0"
        )
        .rstrip(
            "."
        )
    )


def _integer_digit_count(
    value: float,
) -> int:
    """Number of digits in the absolute integer part."""

    integer = abs(
        int(
            float(
                value
            )
        )
    )

    return len(
        str(
            integer
        )
    )


def _relative_difference(
    expected: float,
    observed: float,
) -> float:

    denominator = max(
        abs(
            expected
        ),
        1.0,
    )

    return (
        abs(
            observed
            - expected
        )
        / denominator
    )


# ---------------------------------------------------------------------------
# Reference verification
# ---------------------------------------------------------------------------


def _reference_variants(
    reference: Any,
) -> list[str]:

    text = _norm(
        reference
    )

    if not text:
        return []

    variants = [
        text
    ]

    if "/" in text:

        suffix = (
            text
            .rsplit(
                "/",
                1,
            )[-1]
            .strip()
        )

        if suffix:

            variants.append(
                suffix
            )

    return list(
        dict.fromkeys(
            variants
        )
    )


def _reference_candidates(
    document: OCRDocument,
    expected: Any,
    wrapper_ids: set[str],
) -> tuple[
    list[VerificationCandidate],
    int,
]:

    variants = (
        _reference_variants(
            expected
        )
    )

    if not variants:
        return [], 0

    candidates: list[
        VerificationCandidate
    ] = []

    ignored_wrapper_matches = 0

    for page in document.pages:

        if page.status != "ok":
            continue

        for region in page.regions:

            region_compact = (
                _compact(
                    region.text
                )
            )

            best_variant = None
            best_score = 0.0

            for variant in variants:

                variant_compact = (
                    _compact(
                        variant
                    )
                )

                if not variant_compact:
                    continue

                if (
                    variant_compact
                    in region_compact
                ):

                    score = 100.0

                else:

                    score = _similarity(
                        variant,
                        region.text,
                    )

                if score > best_score:

                    best_score = score
                    best_variant = variant

            if (
                best_variant is None
                or best_score < 45.0
            ):
                continue

            if (
                region.region_id
                in wrapper_ids
            ):

                if best_score >= 80.0:

                    ignored_wrapper_matches += 1

                continue

            if (
                _compact(
                    best_variant
                )
                in region_compact
            ):

                matched_value = (
                    best_variant
                )

            else:

                matched_value = (
                    region.text
                )

            candidates.append(
                VerificationCandidate(
                    value=matched_value,
                    value_text=region.text,
                    score=round(
                        best_score,
                        2,
                    ),
                    difference=None,
                    evidence=_evidence(
                        page.page_number,
                        region,
                        provenance=(
                            "document_body"
                        ),
                    ),
                )
            )

    candidates.sort(
        key=lambda item: (
            item.score,
            item.evidence.confidence,
        ),
        reverse=True,
    )

    return (
        candidates,
        ignored_wrapper_matches,
    )


def _reference_status(
    expected: Any,
    selected: VerificationCandidate,
) -> str:

    expected_compact = (
        _compact(
            expected
        )
    )

    selected_compact = (
        _compact(
            selected.value
        )
    )

    if (
        selected_compact
        == expected_compact
    ):

        return "exact_match"

    expected_text = (
        _norm(
            expected
        )
    )

    if "/" in expected_text:

        local_id = (
            expected_text
            .rsplit(
                "/",
                1,
            )[-1]
        )

        if (
            selected_compact
            == _compact(
                local_id
            )
        ):

            return "local_id_match"

    return "fuzzy_match"


def _count_same_reference_value(
    candidates: list[
        VerificationCandidate
    ],
    selected: VerificationCandidate,
) -> int:

    selected_compact = (
        _compact(
            selected.value
        )
    )

    return sum(
        1
        for candidate in candidates
        if (
            _compact(
                candidate.value
            )
            == selected_compact
        )
    )


def _reference_is_reliable(
    expected: Any,
    selected: VerificationCandidate,
) -> bool:
    """Accept exact/local identifiers and only strong fuzzy matches."""

    status = _reference_status(
        expected,
        selected,
    )

    if status in {
        "exact_match",
        "local_id_match",
    }:
        return True

    return (
        selected.score
        >= REFERENCE_FUZZY_MIN_SCORE
    )


# ---------------------------------------------------------------------------
# Numeric candidates
# ---------------------------------------------------------------------------


def _numeric_candidates(
    document: OCRDocument,
    expected: float,
    wrapper_ids: set[str],
) -> tuple[
    list[VerificationCandidate],
    int,
]:

    candidates: list[
        VerificationCandidate
    ] = []

    wrapper_candidates: list[
        VerificationCandidate
    ] = []

    expected_text = (
        _format_numeric_for_match(
            expected
        )
    )

    for page in document.pages:

        if page.status != "ok":
            continue

        for region in page.regions:

            for (
                token,
                value,
            ) in _numeric_tokens(
                region.text
            ):

                difference = (
                    value
                    - expected
                )

                score = _similarity(
                    expected_text,
                    _format_numeric_for_match(
                        value
                    ),
                )

                provenance = (
                    "bgs_wrapper"
                    if region.region_id
                    in wrapper_ids
                    else "document_body"
                )

                candidate = (
                    VerificationCandidate(
                        value=value,
                        value_text=token,
                        score=round(
                            score,
                            2,
                        ),
                        difference=difference,
                        evidence=_evidence(
                            page.page_number,
                            region,
                            provenance=provenance,
                        ),
                    )
                )

                if provenance == "bgs_wrapper":

                    wrapper_candidates.append(
                        candidate
                    )

                else:

                    candidates.append(
                        candidate
                    )

    candidates.sort(
        key=lambda item: (
            abs(
                item.difference
                if item.difference
                is not None
                else float(
                    "inf"
                )
            ),
            -item.score,
            -item.evidence.confidence,
        )
    )

    ignored_wrapper_matches = sum(
        1
        for candidate
        in wrapper_candidates
        if (
            candidate.difference
            is not None
            and abs(
                candidate.difference
            )
            < 1e-9
        )
    )

    return (
        candidates,
        ignored_wrapper_matches,
    )


# ---------------------------------------------------------------------------
# Depth-specific structural evidence
# ---------------------------------------------------------------------------


def _region_contains_date(
    text: str,
) -> bool:

    return (
        DATE_RE.search(
            text
        )
        is not None
    )


def _candidate_has_attached_metre_unit(
    candidate: VerificationCandidate,
) -> bool:

    token = re.escape(
        candidate.value_text.strip()
    )

    pattern = re.compile(
        rf"""
        {token}
        \s*
        m
        (?![A-Za-z])
        """,
        re.IGNORECASE
        | re.VERBOSE,
    )

    return (
        pattern.search(
            candidate.evidence.text
        )
        is not None
    )


def _rank_depth_candidates(
    candidates: list[
        VerificationCandidate
    ],
) -> list[VerificationCandidate]:

    return sorted(
        candidates,
        key=lambda item: (
            abs(
                item.difference
                if item.difference
                is not None
                else float(
                    "inf"
                )
            ),
            1
            if _region_contains_date(
                item.evidence.text
            )
            else 0,
            0
            if _candidate_has_attached_metre_unit(
                item
            )
            else 1,
            -item.score,
            -item.evidence.confidence,
        ),
    )


def _depth_candidates_without_dates_when_possible(
    candidates: list[
        VerificationCandidate
    ],
) -> list[VerificationCandidate]:

    non_date = [
        candidate
        for candidate
        in candidates
        if not _region_contains_date(
            candidate.evidence.text
        )
    ]

    if non_date:
        return non_date

    return candidates


# ---------------------------------------------------------------------------
# Reliability / abstention
# ---------------------------------------------------------------------------


def _coordinate_candidate_is_reliable(
    expected: float,
    selected: VerificationCandidate,
) -> bool:
    """Conservative plausibility test for a coordinate candidate.

    The goal is not to define an acceptable geographic error. It is only to
    reject obviously unrelated numbers before they are shown as documentary
    evidence.
    """

    try:

        observed = float(
            selected.value
        )

    except (
        TypeError,
        ValueError,
    ):

        return False

    if (
        _integer_digit_count(
            observed
        )
        != _integer_digit_count(
            expected
        )
    ):

        return False

    if (
        selected.score
        < COORDINATE_MIN_SCORE
    ):

        return False

    if (
        _relative_difference(
            expected,
            observed,
        )
        > COORDINATE_MAX_RELATIVE_DIFFERENCE
    ):

        return False

    return True


def _depth_candidate_is_reliable(
    expected: float,
    selected: VerificationCandidate,
) -> bool:
    """Conservative plausibility test for depth evidence."""

    try:

        observed = float(
            selected.value
        )

    except (
        TypeError,
        ValueError,
    ):

        return False

    difference = abs(
        observed
        - expected
    )

    if difference < 1e-9:
        return True

    if (
        _relative_difference(
            expected,
            observed,
        )
        > DEPTH_MAX_RELATIVE_DIFFERENCE
    ):

        return False

    if (
        selected.score
        >= DEPTH_MIN_SCORE
    ):

        return True

    return (
        _candidate_has_attached_metre_unit(
            selected
        )
    )


def _abstain(
    *,
    name: str,
    catalogue_value: Any,
    candidates: list[VerificationCandidate],
    ignored_wrapper_matches: int,
    reason: str,
) -> FieldVerification:
    """Return no selected evidence while retaining candidates for diagnostics."""

    return FieldVerification(
        name=name,
        catalogue_value=catalogue_value,
        matched_value=None,
        matched_text=None,
        match_score=None,
        difference=None,
        status="not_found",
        evidence=[],
        candidates=candidates[:10],
        occurrence_count=0,
        ignored_wrapper_matches=ignored_wrapper_matches,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Selection helpers
# ---------------------------------------------------------------------------


def _status_for_numeric(
    difference: float,
) -> str:

    if abs(
        difference
    ) < 1e-9:

        return "exact_match"

    return "different"


def _count_same_numeric_value(
    candidates: list[
        VerificationCandidate
    ],
    selected_value: float,
) -> int:

    return sum(
        1
        for candidate in candidates
        if (
            isinstance(
                candidate.value,
                (
                    int,
                    float,
                ),
            )
            and abs(
                float(
                    candidate.value
                )
                - selected_value
            )
            < 1e-9
        )
    )


# ---------------------------------------------------------------------------
# Field verification
# ---------------------------------------------------------------------------


def _verify_reference(
    document: OCRDocument,
    expected: Any,
    wrapper_ids: set[str],
) -> FieldVerification:

    candidates, ignored = (
        _reference_candidates(
            document,
            expected,
            wrapper_ids,
        )
    )

    if not candidates:

        return _abstain(
            name="borehole_id",
            catalogue_value=expected,
            candidates=[],
            ignored_wrapper_matches=ignored,
            reason=(
                "no matching reference was found "
                "outside the BGS wrapper"
            ),
        )

    selected = (
        candidates[
            0
        ]
    )

    if not _reference_is_reliable(
        expected,
        selected,
    ):

        return _abstain(
            name="borehole_id",
            catalogue_value=expected,
            candidates=candidates,
            ignored_wrapper_matches=ignored,
            reason=(
                "best reference candidate is not "
                "sufficiently reliable"
            ),
        )

    return FieldVerification(
        name="borehole_id",
        catalogue_value=expected,
        matched_value=selected.value,
        matched_text=selected.value_text,
        match_score=selected.score,
        difference=None,
        status=_reference_status(
            expected,
            selected,
        ),
        evidence=[
            selected.evidence
        ],
        candidates=candidates[
            :10
        ],
        occurrence_count=(
            _count_same_reference_value(
                candidates,
                selected,
            )
        ),
        ignored_wrapper_matches=ignored,
        reason=None,
    )


def _verify_numeric(
    field_name: str,
    document: OCRDocument,
    expected: Any,
    wrapper_ids: set[str],
) -> FieldVerification:

    try:

        expected_number = float(
            expected
        )

    except (
        TypeError,
        ValueError,
    ):

        return FieldVerification(
            name=field_name,
            catalogue_value=expected,
            status="not_available",
            reason=(
                "catalogue value is not numeric"
            ),
        )

    candidates, ignored = (
        _numeric_candidates(
            document,
            expected_number,
            wrapper_ids,
        )
    )

    if not candidates:

        return _abstain(
            name=field_name,
            catalogue_value=expected,
            candidates=[],
            ignored_wrapper_matches=ignored,
            reason=(
                "no numeric value was found "
                "outside the BGS wrapper"
            ),
        )

    if field_name == "final_depth":

        candidates = (
            _depth_candidates_without_dates_when_possible(
                candidates
            )
        )

        candidates = (
            _rank_depth_candidates(
                candidates
            )
        )

    selected = (
        candidates[
            0
        ]
    )

    if field_name in {
        "easting",
        "northing",
    }:

        reliable = (
            _coordinate_candidate_is_reliable(
                expected_number,
                selected,
            )
        )

    else:

        reliable = (
            _depth_candidate_is_reliable(
                expected_number,
                selected,
            )
        )

    if not reliable:

        return _abstain(
            name=field_name,
            catalogue_value=expected,
            candidates=candidates,
            ignored_wrapper_matches=ignored,
            reason=(
                "best numeric candidate is not "
                "sufficiently reliable"
            ),
        )

    difference = float(
        selected.difference or 0.0
    )

    selected_value = float(
        selected.value
    )

    return FieldVerification(
        name=field_name,
        catalogue_value=expected,
        matched_value=selected_value,
        matched_text=selected.value_text,
        match_score=selected.score,
        difference=difference,
        status=_status_for_numeric(
            difference
        ),
        evidence=[
            selected.evidence
        ],
        candidates=candidates[
            :10
        ],
        occurrence_count=(
            _count_same_numeric_value(
                candidates,
                selected_value,
            )
        ),
        ignored_wrapper_matches=ignored,
        reason=None,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def verify_document(
    document: OCRDocument,
    sobi_metadata: dict[str, Any],
    cfg: DomainConfig,
) -> DocumentVerification:
    """Verify SOBI metadata against OCR contents.

    The verifier starts from catalogue values and searches for supporting
    evidence in the historical document body.

    The configured field anchors used by ``expert_extractor`` are deliberately
    NOT used here.

    The configuration is currently used only for wrapper/provenance detection.

    A selected match means that a catalogue value, or a nearby candidate, has
    sufficiently credible OCR evidence in the document body.

    If the best candidate is not credible enough, the verifier abstains:
    ``matched_value`` is None and no evidence region is selected.

    SOBI remains an external reference for comparison, not ground truth.
    """

    wrapper_ids = (
        classify_wrapper_regions(
            document,
            cfg,
        )
    )

    fields: list[
        FieldVerification
    ] = []

    reference = (
        sobi_metadata.get(
            "reference"
        )
    )

    if reference is None:

        fields.append(
            FieldVerification(
                name="borehole_id",
                catalogue_value=None,
                status="not_available",
                reason=(
                    "reference is not available "
                    "in the SOBI record"
                ),
            )
        )

    else:

        fields.append(
            _verify_reference(
                document,
                reference,
                wrapper_ids,
            )
        )

    for field_name in (
        "easting",
        "northing",
        "final_depth",
    ):

        catalogue_key = (
            CATALOGUE_KEYS[
                field_name
            ]
        )

        expected = (
            sobi_metadata.get(
                catalogue_key
            )
        )

        if expected is None:

            fields.append(
                FieldVerification(
                    name=field_name,
                    catalogue_value=None,
                    status="not_available",
                    reason=(
                        f"{catalogue_key} is not "
                        "available in the SOBI record"
                    ),
                )
            )

            continue

        fields.append(
            _verify_numeric(
                field_name,
                document,
                expected,
                wrapper_ids,
            )
        )

    return DocumentVerification(
        document_id=document.document_id,
        source_name=document.source_name,
        method=METHOD_NAME,
        verifier_version=VERIFIER_VERSION,
        fields=fields,
        wrapper_region_ids=sorted(
            wrapper_ids
        ),
    )
