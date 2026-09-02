"""Partition surveyor notes by REFERENCE-tier match quality before LLM mapping."""

from __future__ import annotations

from backend.config import settings
from backend.domain.notes.parser import UNASSIGNED
from backend.rag.retriever import (
    InterferenceLevel,
    _content_tokens,
    find_paragraph_by_topic,
)


def _note_routes_elsewhere(observation: str, section_id: str) -> bool:
    """True only when the deterministic keyword router is confident the note
    belongs to a DIFFERENT section than the one currently being mapped.

    Used as the final acceptance signal so that a note the parser already placed
    in this section is kept even when the (different-property) baseline never
    mentions it — while an atom that clearly belongs elsewhere (e.g. an asbestos
    fragment inside a roof note) is still rejected.
    """
    sid = (section_id or "").strip().upper()
    if not sid:
        return False
    # Lazy import: notes_keyword_router pulls in heavier routing deps.
    from backend.domain.notes.keyword_router import classify_note_cascade

    routed, _score, _obs = classify_note_cascade(observation)
    routed = (routed or "").strip().upper()
    if not routed or routed == UNASSIGNED:
        # Unrecognised / generic — trust the parser's placement, keep it here.
        return False
    return routed != sid


def lexical_overlap_ratio(observation: str, corpus: str) -> float:
    """Share of observation tokens that also appear in the corpus."""
    obs_tokens = _content_tokens(observation)
    if not obs_tokens:
        return 0.0
    corpus_tokens = _content_tokens(corpus)
    return len(obs_tokens & corpus_tokens) / len(obs_tokens)


def _baseline_lexical_match(observation: str, baseline_text: str) -> bool:
    """True when the note is clearly about the same topic as the section baseline.

    Finite set operations only — no loops over unbounded input.
    """
    obs_tokens = _content_tokens(observation)
    baseline_tokens = _content_tokens(baseline_text)
    if not obs_tokens:
        return False

    shared = obs_tokens & baseline_tokens
    min_lexical = settings.note_baseline_lexical_min_overlap
    ratio = len(shared) / len(obs_tokens)

    if len(shared) >= 2 and ratio >= min_lexical:
        return True

    strong_shared = {t for t in shared if len(t) >= 5}
    return bool(strong_shared) and ratio >= min_lexical


def observation_matches_baseline(
    tenant_id: str,
    observation: str,
    baseline_text: str,
    *,
    paragraph_section_id: str,
    interference_level: InterferenceLevel,
    allowed_doc_keys: frozenset[str] | None = None,
    report_section_id: str = "",
) -> bool:
    """True when a note is safe to map onto the section baseline (not a guess).

    A note has already been routed to this section by :mod:`notes_parser`, so it
    is a legitimate finding here even when the retrieved baseline — which comes
    from a DIFFERENT property — never mentions it. We therefore accept the note
    unless the deterministic keyword router confidently claims it for another
    section (intra-line topic drift, e.g. an asbestos fragment inside a roof note).
    """
    obs = (observation or "").strip()
    if not obs:
        return False

    min_score = settings.confidence_threshold

    hits = find_paragraph_by_topic(
        tenant_id,
        [obs],
        interference_level=interference_level,
        top_k=3,
        allowed_doc_keys=allowed_doc_keys,
        paragraph_section_id=paragraph_section_id,
    )

    if hits and hits[0].score >= min_score:
        if paragraph_section_id:
            want = paragraph_section_id.strip().upper()
            hit_sid = (hits[0].section_id or "").strip().upper()
            if hit_sid and want and hit_sid != want:
                if not _baseline_lexical_match(obs, baseline_text):
                    return False
        return True

    if _baseline_lexical_match(obs, baseline_text):
        return True

    # Baseline is silent on this note (it describes a different property). Keep the
    # note where the parser placed it unless the keyword router is sure it belongs
    # to a different section.
    return not _note_routes_elsewhere(obs, report_section_id or paragraph_section_id)


def partition_observations_for_baseline(
    tenant_id: str,
    observations: list[str],
    baseline_text: str,
    *,
    paragraph_section_id: str,
    interference_level: InterferenceLevel,
    allowed_doc_keys: frozenset[str] | None = None,
    report_section_id: str = "",
) -> tuple[list[str], list[str]]:
    """Split notes into mappable vs UNMATCHED (below RAG threshold / no baseline anchor)."""
    matched: list[str] = []
    unmatched: list[str] = []
    for obs in observations:
        text = (obs or "").strip()
        if not text:
            continue
        if observation_matches_baseline(
            tenant_id,
            text,
            baseline_text,
            paragraph_section_id=paragraph_section_id,
            interference_level=interference_level,
            allowed_doc_keys=allowed_doc_keys,
            report_section_id=report_section_id,
        ):
            matched.append(text)
        else:
            unmatched.append(text)
    return matched, unmatched


def format_unmatched_observation_tag(observation: str) -> str:
    """Standard placeholder tag from instructions v2 mapping output."""
    return f"[UNMATCHED_OBSERVATION: {observation.strip()}]"
