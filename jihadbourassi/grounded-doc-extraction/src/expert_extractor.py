"""Expert / hybrid extractor.

Input: a normalized `OCRDocument` (Phase 3). Output: an `ExtractionResult`.

The engine here is generic. Every anchor word, value pattern, wrapper marker,
range, tolerance and weight arrives from a `DomainConfig`; this file contains no
domain-specific string or number. Pointing it at a different corpus is a
configuration change, not a code change.

Flow, deliberately linear so every step is inspectable:

    anchors -> candidates -> candidate-level provenance -> scoring
            -> selection (document_body only) -> grounding / traceability
            -> validation -> FieldExtraction

Provenance is decided per candidate, from that candidate's own local evidence
neighbourhood. There is no page-level classification anywhere: a single page can
legitimately hold both wrapper metadata and document-body evidence.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Iterable

from .domain_config import DomainConfig
from .extraction_result import (
    EXTRACTOR_VERSION,
    EvidenceRef,
    ExtractionCandidate,
    ExtractionResult,
    FieldExtraction,
    SourceEvidence,
    are_regions_traceable,
    is_value_grounded,
    source_text_for,
)
from .ocr_document import OCRDocument, OCRPage, OCRRegion

METHOD_NAME = "expert"


# ---------------------------------------------------------------------------
# small geometry / text helpers
# ---------------------------------------------------------------------------


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _overlap_ratio(a0: float, a1: float, b0: float, b1: float) -> float:
    """Fraction of the shorter interval covered by the intersection."""
    lo, hi = max(a0, b0), min(a1, b1)
    if hi <= lo:
        return 0.0
    shorter = min(a1 - a0, b1 - b0)
    return (hi - lo) / shorter if shorter > 0 else 0.0


def _centre(bbox: list[float]) -> tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)


def _normalised_distance(a: list[float], b: list[float], width: float, height: float) -> float:
    ax, ay = _centre(a)
    bx, by = _centre(b)
    dx = (ax - bx) / width if width else 0.0
    dy = (ay - by) / height if height else 0.0
    return (dx * dx + dy * dy) ** 0.5


@dataclass(frozen=True)
class _PageCtx:
    """A page plus the dimensions needed to normalise distances."""

    page: OCRPage
    width: float
    height: float

    @property
    def regions(self) -> list[OCRRegion]:
        return self.page.regions


def build_source_lookup(document: OCRDocument) -> dict[str, SourceEvidence]:
    """The authoritative contents of every region, keyed by region_id.

    Traceability is checked against this, not against the copies carried inside
    the result, so a citation cannot forge its own supporting text.
    """
    return {
        region.region_id: SourceEvidence(
            region_id=region.region_id,
            page_number=page.page_number,
            bbox=tuple(float(v) for v in region.bbox),
            text=region.text,
        )
        for page in document.pages
        for region in page.regions
    }


def _evidence(region: OCRRegion, page_number: int) -> EvidenceRef:
    return EvidenceRef(
        region_id=region.region_id,
        page_number=page_number,
        bbox=list(region.bbox),
        text=region.text,
        confidence=region.confidence,
    )


def _relation_holds(
    relation: str,
    anchor: OCRRegion,
    other: OCRRegion,
    ctx: _PageCtx,
    cfg: DomainConfig,
) -> bool:
    """Is `other` in the given spatial relation to `anchor`?

    Relations are expressed from the anchor's point of view and are named in the
    configuration, so a prefix label ("Final Depth") and a terminator label
    ("End of Borehole") can allow different geometries.
    """
    ax0, ay0, ax1, ay1 = anchor.bbox
    ox0, oy0, ox1, oy1 = other.bbox

    if relation == "right":
        return (
            ox0 >= ax1
            and _overlap_ratio(ay0, ay1, oy0, oy1) >= cfg.spatial("min_y_overlap")
            and (ox0 - ax1) <= cfg.spatial("max_gap_frac_x") * ctx.width
        )
    if relation == "below":
        return (
            oy0 >= ay1
            and _overlap_ratio(ax0, ax1, ox0, ox1) >= cfg.spatial("min_x_overlap")
            and (oy0 - ay1) <= cfg.spatial("max_gap_frac_y") * ctx.height
        )
    if relation == "above":
        return (
            oy1 <= ay0
            and _overlap_ratio(ax0, ax1, ox0, ox1) >= cfg.spatial("min_x_overlap")
            and (ay0 - oy1) <= cfg.spatial("max_gap_frac_y") * ctx.height
        )
    if relation == "left":
        # A value in the same table row, to the left of a terminator label.
        # The vertical tolerance is a dedicated, conservative centre-offset bound
        # rather than the generic vertical radius: a large radius would let a
        # value from a neighbouring column win on raw proximity.
        ay_c = (ay0 + ay1) / 2
        oy_c = (oy0 + oy1) / 2
        return (
            ox1 <= ax0
            and abs(ay_c - oy_c) <= cfg.spatial("row_max_centre_dy_frac") * ctx.height
            and (ax0 - ox1) <= cfg.spatial("row_max_gap_frac_x") * ctx.width
        )
    if relation == "overlap":
        return (
            _overlap_ratio(ax0, ax1, ox0, ox1) >= cfg.spatial("overlap_min_x")
            and _overlap_ratio(ay0, ay1, oy0, oy1) >= cfg.spatial("overlap_min_y")
        )
    if relation == "near":
        return _normalised_distance(anchor.bbox, other.bbox, ctx.width, ctx.height) <= cfg.spatial(
            "near_frac"
        )
    return False


# ---------------------------------------------------------------------------
# provenance — candidate-local only
# ---------------------------------------------------------------------------


def _local_context_texts(
    value_region: OCRRegion,
    anchor_region: OCRRegion | None,
    ctx: _PageCtx,
    cfg: DomainConfig,
) -> list[str]:
    """The bounded neighbourhood used to decide one candidate's provenance.

    Value region + matched anchor region + the nearest few regions within a small
    normalised radius. Bounded and local by construction: never a page aggregate.
    """
    texts = [value_region.text]
    if anchor_region is not None:
        texts.append(anchor_region.text)

    radius = cfg.spatial("provenance_neighbour_frac")
    limit = int(cfg.spatial("provenance_max_neighbours"))
    skip = {value_region.region_id} | (
        {anchor_region.region_id} if anchor_region is not None else set()
    )

    neighbours = [
        (
            _normalised_distance(value_region.bbox, r.bbox, ctx.width, ctx.height),
            r,
        )
        for r in ctx.regions
        if r.region_id not in skip
    ]
    neighbours = [(d, r) for d, r in neighbours if d <= radius]
    neighbours.sort(key=lambda pair: pair[0])
    texts.extend(r.text for _, r in neighbours[:limit])
    return texts


def _classify_provenance(
    value_region: OCRRegion,
    anchor_region: OCRRegion | None,
    has_strong_anchor: bool,
    ctx: _PageCtx,
    cfg: DomainConfig,
) -> str:
    """bgs_wrapper only on explicit lexical wrapper evidence, locally.

    Format alone (for instance a packed integer pair) is never sufficient: it is
    a format signal that affects scoring, not provenance.
    """
    context = " ".join(_norm(t) for t in _local_context_texts(value_region, anchor_region, ctx, cfg))
    # OCR frequently drops inter-word spacing ("BritishNationalGrid"), so markers
    # are matched against both the spaced and space-free forms.
    context_nospace = context.replace(" ", "")
    for marker in cfg.wrapper_markers:
        if marker in context or marker.replace(" ", "") in context_nospace:
            return "bgs_wrapper"
    return "document_body" if has_strong_anchor else "unknown"


# ---------------------------------------------------------------------------
# unit handling (no conversion, ever)
# ---------------------------------------------------------------------------


def _classify_unit(
    field_spec: dict[str, Any],
    value_region: OCRRegion,
    value_text: str,
    anchor_region: OCRRegion | None,
    ctx: _PageCtx,
    cfg: DomainConfig,
) -> tuple[str, str | None]:
    """Return (unit_kind, unit_text) without converting anything.

    Metric evidence may be a suffix on the value, or a locally associated header
    such as "(m)". An explicit non-metric token makes the candidate unsupported;
    absence of any evidence leaves the unit unknown. No factor is invented and
    metres are never assumed.
    """
    unit_spec = field_spec.get("unit")
    if not unit_spec:
        return "not_applicable", None

    metric = [t.lower() for t in unit_spec.get("metric_tokens", [])]
    non_metric = [t.lower() for t in unit_spec.get("non_metric_tokens", [])]

    def _find(text: str) -> tuple[str, str] | None:
        low = _norm(text)
        # Non-metric first: an explicit foot marking must not be masked by an "m".
        for token in sorted(non_metric, key=len, reverse=True):
            if _token_present(low, token):
                return "non_metric", token
        for token in sorted(metric, key=len, reverse=True):
            if _token_present(low, token):
                return "metric", token
        return None

    # 1. the value region itself, restricted to what follows the value
    low = value_region.text
    idx = low.find(value_text)
    tail = low[idx + len(value_text) :] if idx >= 0 else low
    found = _find(tail)
    if found:
        return found

    # 2. the matched anchor region
    if anchor_region is not None:
        found = _find(anchor_region.text)
        if found:
            return found

    # 3. a locally associated unit token, within a small radius
    radius = float(unit_spec.get("context_neighbour_frac", cfg.spatial("near_frac")))
    nearby = sorted(
        (
            (_normalised_distance(value_region.bbox, r.bbox, ctx.width, ctx.height), r)
            for r in ctx.regions
            if r.region_id != value_region.region_id
        ),
        key=lambda pair: pair[0],
    )
    for distance, region in nearby:
        if distance > radius:
            break
        found = _find(region.text)
        if found:
            return found

    # 4. same-column header above the value.
    # Table headers sit far above the row they describe, so euclidean proximity is
    # the wrong association: a unit in an adjacent column can be much closer than
    # the header of this column. Require column alignment and search upwards,
    # nearest first. Generic table-layout reasoning, not corpus-specific.
    min_overlap = float(unit_spec.get("column_min_x_overlap", cfg.spatial("min_x_overlap")))
    max_dy = float(unit_spec.get("column_max_dy_frac", 0.0)) * ctx.height
    if max_dy > 0:
        vx0, vy0, vx1, _vy1 = value_region.bbox
        above = []
        for region in ctx.regions:
            if region.region_id == value_region.region_id:
                continue
            rx0, _ry0, rx1, ry1 = region.bbox
            if ry1 > vy0:  # not above the value
                continue
            if _overlap_ratio(vx0, vx1, rx0, rx1) < min_overlap:
                continue
            if (vy0 - ry1) > max_dy:
                continue
            above.append((vy0 - ry1, region))
        above.sort(key=lambda pair: pair[0])
        for _dy, region in above:
            found = _find(region.text)
            if found:
                return found

    return "unknown", None


def _anchor_matches(anchor: dict[str, Any], anchor_text: str, region_text_norm: str) -> bool:
    """Does an anchor fire on a region?

    Two generic modes, selected in configuration:

    * `contains` (default) — substring, right for specific labels like
      "borehole no" that are always followed by their value;
    * `exact` — the whole normalised region text must equal the anchor, which is
      what makes a bare, generic word usable as an anchor at all. A bare
      "borehole" matched by substring would also fire on "END OF BOREHOLE",
      "BOREHOLERECORD" and "BOREHOLE1".
    """
    mode = str(anchor.get("match", "contains")).lower()
    if mode == "exact":
        return region_text_norm.strip(" :.") == anchor_text
    return anchor_text in region_text_norm


def _mask_span(original: str, normalised: str, start: int, length: int) -> str:
    """Blank out an anchor occurrence while keeping the original casing.

    `normalised` is the collapsed/lowercased form used to locate the anchor. When
    collapsing changed the string's length the offsets no longer line up, so the
    safe fallback is a case-insensitive removal on the original text.
    """
    if start < 0:
        return original
    if len(original) == len(normalised):
        return original[:start] + " " * length + original[start + length :]
    return re.sub(re.escape(normalised[start : start + length]), " " * length, original,
                  count=1, flags=re.IGNORECASE)


def _token_present(text: str, token: str) -> bool:
    """Whole-token match, so 'm' does not fire inside 'made ground'."""
    if token.isalnum():
        return re.search(rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])", text) is not None
    return token in text


# ---------------------------------------------------------------------------
# candidate generation
# ---------------------------------------------------------------------------


def _iter_page_contexts(document: OCRDocument) -> Iterable[_PageCtx]:
    for page in document.pages:
        if page.status != "ok":
            continue
        width = float(page.width_px or 1)
        height = float(page.height_px or 1)
        yield _PageCtx(page=page, width=width, height=height)


def _make_candidate(
    value_text: str,
    value_region: OCRRegion,
    ctx: _PageCtx,
    cfg: DomainConfig,
    field_name: str,
    field_spec: dict[str, Any],
    match_rule: str,
    anchor_region: OCRRegion | None,
    anchor_text: str | None,
    has_strong_anchor: bool,
    format_bonus: float,
) -> ExtractionCandidate:
    evidence = [_evidence(value_region, ctx.page.page_number)]
    if anchor_region is not None and anchor_region.region_id != value_region.region_id:
        evidence.append(_evidence(anchor_region, ctx.page.page_number))

    provenance = _classify_provenance(value_region, anchor_region, has_strong_anchor, ctx, cfg)
    unit_kind, unit_text = _classify_unit(
        field_spec, value_region, value_text, anchor_region, ctx, cfg
    )

    proximity = 0.0
    if anchor_region is not None and anchor_region.region_id != value_region.region_id:
        proximity = _normalised_distance(anchor_region.bbox, value_region.bbox, ctx.width, ctx.height)

    parts = {
        "rule_strength": float(cfg.scoring("rule_strength", {}).get(match_rule, 0.0)),
        "anchor_proximity": -float(cfg.scoring("anchor_proximity_weight")) * proximity,
        "format_specificity": float(cfg.scoring("format_specificity_weight")) * format_bonus,
        "ocr_confidence": float(cfg.scoring("ocr_confidence_weight")) * value_region.confidence,
    }
    return ExtractionCandidate(
        value_text=value_text,
        value=_parse_value(value_text, field_spec),
        evidence=evidence,
        provenance=provenance,
        match_rule=match_rule,
        score=sum(parts.values()),
        score_parts=parts,
        anchor_region_id=anchor_region.region_id if anchor_region is not None else None,
        anchor_text=anchor_region.text if anchor_region is not None else anchor_text,
        unit_text=unit_text,
        unit_kind=unit_kind,
    )


def _parse_value(value_text: str, field_spec: dict[str, Any]) -> float | str | None:
    if field_spec.get("validation", {}).get("type") == "range":
        try:
            return float(value_text)
        except ValueError:
            return None
    return value_text


def _accepts_digit_rule(value_text: str, field_spec: dict[str, Any]) -> bool:
    if field_spec.get("require_digit") and not any(ch.isdigit() for ch in value_text):
        return False
    return True


def generate_candidates(
    document: OCRDocument,
    field_name: str,
    cfg: DomainConfig,
) -> tuple[list[ExtractionCandidate], bool]:
    """All candidates for one field, plus whether any anchor matched at all.

    The anchor flag distinguishes "no anchor in this document" from "anchor found
    but no value near it" — two different failures that deserve different reasons.
    """
    field_spec = cfg.field(field_name)
    value_re = re.compile(field_spec["value_pattern"])
    inline_res = [re.compile(p) for p in field_spec.get("inline_patterns", [])]
    packed_pattern = field_spec.get("packed_pair_pattern")
    packed_re = re.compile(packed_pattern) if packed_pattern else None
    packed_position = int(field_spec.get("packed_pair_position", 1))
    anchors = field_spec["anchors"]

    candidates: list[ExtractionCandidate] = []
    anchor_seen = False

    for ctx in _iter_page_contexts(document):
        for region in ctx.regions:
            text = region.text
            low = _norm(text)

            # --- rule 1a: labelled inline pattern (e.g. a symbol-prefixed value)
            for pattern in inline_res:
                for match in pattern.finditer(text):
                    value_text = match.group(1)
                    if not _accepts_digit_rule(value_text, field_spec):
                        continue
                    candidates.append(
                        _make_candidate(
                            value_text, region, ctx, cfg, field_name, field_spec,
                            "labelled_in_region", region, None, True, format_bonus=1.0,
                        )
                    )

            # --- rule 1b/2: word anchors, same region or neighbour
            for anchor in anchors:
                anchor_text = str(anchor["text"]).lower()
                if not _anchor_matches(anchor, anchor_text, low):
                    continue
                anchor_seen = True
                strong = anchor.get("strength", "strong") == "strong"
                relations = list(anchor["relations"])

                if "same_region" in relations:
                    # Mask the anchor in the ORIGINAL text: values must keep their
                    # original casing, since accepted values are verbatim OCR text.
                    start = low.find(anchor_text)
                    remainder = _mask_span(text, low, start, len(anchor_text))
                    for match in value_re.finditer(remainder):
                        value_text = match.group(0)
                        if not _accepts_digit_rule(value_text, field_spec):
                            continue
                        candidates.append(
                            _make_candidate(
                                value_text, region, ctx, cfg, field_name, field_spec,
                                "labelled_in_region", region, anchor_text, strong,
                                format_bonus=0.5,
                            )
                        )

                for relation in relations:
                    if relation == "same_region":
                        continue
                    neighbours = [
                        other
                        for other in ctx.regions
                        if other.region_id != region.region_id
                        and _relation_holds(relation, region, other, ctx, cfg)
                    ]
                    neighbours.sort(
                        key=lambda o: _normalised_distance(region.bbox, o.bbox, ctx.width, ctx.height)
                    )
                    for other in neighbours:
                        match = value_re.search(other.text)
                        if not match:
                            continue
                        value_text = match.group(0)
                        if not _accepts_digit_rule(value_text, field_spec):
                            continue
                        candidates.append(
                            _make_candidate(
                                value_text, other, ctx, cfg, field_name, field_spec,
                                "labelled_neighbour", region, anchor_text, strong,
                                format_bonus=0.0,
                            )
                        )
                        break  # nearest satisfying neighbour only

            # --- rule 3: packed pair — a FORMAT signal, not a provenance signal
            if packed_re is not None:
                for match in packed_re.finditer(text):
                    value_text = match.group(packed_position)
                    candidates.append(
                        _make_candidate(
                            value_text, region, ctx, cfg, field_name, field_spec,
                            "packed_pair", None, None, False, format_bonus=0.0,
                        )
                    )


    return _dedupe_best(candidates), anchor_seen


def _dedupe_best(candidates: list[ExtractionCandidate]) -> list[ExtractionCandidate]:
    """Keep the best-scoring candidate per (value region, value text).

    The same value can be reached by several rules — an inline label and a
    neighbouring label, say. Deduplicating on first arrival would let whichever
    rule happened to run first decide the match_rule and the score, so the
    strongest evidence for a value wins instead.
    """
    best: dict[tuple[str, str], ExtractionCandidate] = {}
    for candidate in candidates:
        key = (candidate.value_region_id, candidate.value_text)
        current = best.get(key)
        if current is None or candidate.score > current.score:
            best[key] = candidate
    return list(best.values())


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


def _validate_candidate(
    candidate: ExtractionCandidate, field_spec: dict[str, Any]
) -> tuple[str, str | None]:
    """Return (validation, failure_reason). Never repairs or clamps a value."""
    spec = field_spec.get("validation")
    if not spec:
        return "not_checked", None

    if spec["type"] == "range":
        if not isinstance(candidate.value, (int, float)):
            return "failed", "validation_failed"
        if not (float(spec["min"]) <= float(candidate.value) <= float(spec["max"])):
            return "failed", "out_of_configured_range"
        return "passed", None

    if spec["type"] == "format":
        text = candidate.value_text
        if not (int(spec.get("min_length", 1)) <= len(text) <= int(spec.get("max_length", 1000))):
            return "failed", "validation_failed"
        if not re.fullmatch(spec["pattern"], text):
            return "failed", "validation_failed"
        return "passed", None

    return "not_checked", None


# ---------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------


def _traceable_and_grounded(
    candidate: ExtractionCandidate, source_lookup: dict[str, SourceEvidence]
) -> tuple[bool, bool]:
    """Verify a candidate's citations against the source, then ground its value.

    Grounding uses the SOURCE region text, so a forged evidence copy can neither
    pass traceability nor supply its own support.
    """
    traceable = are_regions_traceable(candidate.evidence, source_lookup)
    grounded = is_value_grounded(
        candidate.value_text, source_text_for(candidate.evidence[0], source_lookup)
    )
    return traceable, grounded


def _abstain(
    name: str,
    status: str,
    reason: str,
    candidates: list[ExtractionCandidate],
    selected: ExtractionCandidate | None = None,
    source_lookup: dict[str, SourceEvidence] | None = None,
    validation: str = "not_checked",
) -> FieldExtraction:
    """Build a non-accepted result, exposing the selected candidate for diagnosis."""
    if selected is None:
        return FieldExtraction(
            name=name,
            raw_value=None,
            accepted_value=None,
            status=status,
            reason=reason,
            candidates=candidates,
        )
    traceable, grounded = _traceable_and_grounded(selected, source_lookup or {})
    return FieldExtraction(
        name=name,
        raw_value=selected.value,
        accepted_value=None,
        status=status,
        reason=reason,
        evidence=selected.evidence,
        evidence_traceable=traceable,
        value_grounded=grounded,
        validation=validation,
        provenance=selected.provenance,
        candidates=candidates,
    )


def select_field(
    name: str,
    candidates: list[ExtractionCandidate],
    anchor_seen: bool,
    cfg: DomainConfig,
    source_lookup: dict[str, SourceEvidence],
) -> FieldExtraction:
    """Choose one candidate and decide whether it may be accepted.

    Selection happens among document_body candidates. If none exists, the best
    other candidate is still exposed as raw_value/evidence for diagnosis, with
    accepted_value=None and a reason naming why it was not usable.
    """
    field_spec = cfg.field(name)
    ranked = sorted(candidates, key=lambda c: c.score, reverse=True)

    if not ranked:
        reason = "no_value_near_anchor" if anchor_seen else "no_anchor"
        return _abstain(name, "not_found", reason, candidates)

    body = [c for c in ranked if c.provenance == "document_body"]
    if not body:
        best = ranked[0]
        reason = "wrapper_only" if best.provenance == "bgs_wrapper" else "provenance_unknown"
        return _abstain(name, "unsupported", reason, candidates, best, source_lookup)

    selected = body[0]
    distinct_values = {c.value for c in body}

    # Ambiguity. For fields configured as single-entity, any second distinct
    # value is disqualifying; otherwise a close runner-up is.
    if len(distinct_values) > 1:
        if field_spec.get("distinct_value_abstention") == "always":
            return _abstain(
                name, "unsupported", "multiple_entities", candidates, selected, source_lookup
            )
        runner_up = next((c for c in body[1:] if c.value != selected.value), None)
        if runner_up is not None and (selected.score - runner_up.score) < cfg.tie_margin:
            return _abstain(
                name, "unsupported", "ambiguous_candidates", candidates, selected, source_lookup
            )

    traceable, grounded = _traceable_and_grounded(selected, source_lookup)

    if not traceable:
        return _abstain(
            name, "unsupported", "evidence_not_traceable", candidates, selected, source_lookup
        )
    if not grounded:
        return _abstain(
            name, "unsupported", "value_not_in_evidence", candidates, selected, source_lookup
        )

    validation, failure_reason = _validate_candidate(selected, field_spec)
    if validation != "passed":
        status = "out_of_range" if failure_reason == "out_of_configured_range" else "unsupported"
        return _abstain(
            name, status, failure_reason or "validation_failed", candidates, selected,
            source_lookup, validation,
        )

    if selected.unit_kind == "non_metric":
        return _abstain(
            name, "unsupported", "unsupported_unit", candidates, selected, source_lookup, validation
        )
    if selected.unit_kind == "unknown":
        return _abstain(
            name, "unsupported", "unit_unknown", candidates, selected, source_lookup, validation
        )

    return FieldExtraction(
        name=name,
        raw_value=selected.value,
        accepted_value=selected.value,
        status="accepted",
        reason=None,
        evidence=selected.evidence,
        evidence_traceable=True,
        value_grounded=True,
        validation="passed",
        provenance="document_body",
        candidates=candidates,
    )


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def extract(document: OCRDocument, cfg: DomainConfig) -> ExtractionResult:
    """Run the expert extractor over a normalized OCR document."""
    started = time.perf_counter()

    source_lookup = build_source_lookup(document)
    error_pages = [p.page_number for p in document.pages if p.status == "error"]
    no_text_pages = [p.page_number for p in document.pages if p.status == "no_text"]

    by_field: dict[str, list[ExtractionCandidate]] = {}
    anchors_seen: dict[str, bool] = {}
    failures: dict[str, str] = {}

    for name in cfg.field_names:
        try:
            candidates, anchor_seen = generate_candidates(document, name, cfg)
        except Exception as exc:  # noqa: BLE001 - one bad field must not void the document
            by_field[name], anchors_seen[name] = [], False
            failures[name] = f"{type(exc).__name__}: {exc}"
            continue
        by_field[name], anchors_seen[name] = candidates, anchor_seen

    fields: list[FieldExtraction] = []
    for name in cfg.field_names:
        if name in failures:
            fields.append(
                FieldExtraction(
                    name=name,
                    raw_value=None,
                    accepted_value=None,
                    status="extraction_error",
                    reason="exception",
                )
            )
            continue
        try:
            fields.append(
                select_field(name, by_field[name], anchors_seen[name], cfg, source_lookup)
            )
        except Exception:  # noqa: BLE001
            fields.append(
                FieldExtraction(
                    name=name,
                    raw_value=None,
                    accepted_value=None,
                    status="extraction_error",
                    reason="exception",
                )
            )

    return ExtractionResult(
        document_id=document.document_id,
        source_name=document.source_name,
        method=METHOD_NAME,
        extractor_version=EXTRACTOR_VERSION,
        config_id=cfg.config_id,
        raster_dpi=document.raster_dpi,
        duration_ms=int((time.perf_counter() - started) * 1000),
        fields=fields,
        error_pages=error_pages,
        no_text_pages=no_text_pages,
    )
