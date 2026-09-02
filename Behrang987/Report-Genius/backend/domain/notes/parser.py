"""Pure RAG semantic classification for surveyor notes.

Each observation is embedded once and compared against 54 canonical RICS L3
subsection anchor vectors using strict L2-normalized cosine similarity. The top
match must meet ``settings.confidence_threshold`` (default 0.72) and lead the
runner-up by at least ``settings.note_rag_ambiguity_margin`` (default 0.05),
otherwise the note is ``UNASSIGNED``.
"""

from __future__ import annotations

import logging
import re
import threading

import numpy as np

from backend.config import settings
from backend.domain.notes.routing import (
    RAG_CLASSIFICATION_GUIDANCE,
)
from backend.domain.rics_level3_schema import (
    build_section_anchor_text,
    iter_canonical_leaf_sections,
    valid_leaf_section_ids,
)
from backend.llm import embeddings as _embeddings
from backend.models.schema import TemplateSchema
from backend.models.section import SectionNote

logger = logging.getLogger(__name__)

UNASSIGNED = "UNASSIGNED"


class _SectionAnchorCache:
    """In-memory matrix of normalized anchor embeddings keyed by leaf section id."""

    def __init__(self) -> None:
        self.section_ids: list[str] = []
        self.matrix: np.ndarray | None = None

    @property
    def ready(self) -> bool:
        return self.matrix is not None and len(self.section_ids) > 0

    def clear(self) -> None:
        self.section_ids = []
        self.matrix = None


_cache = _SectionAnchorCache()
_anchor_lock = threading.Lock()


def anchors_ready() -> bool:
    """True when the 54-leaf anchor matrix is loaded in memory."""
    return _cache.ready


def initialize_section_anchors() -> int:
    """Embed and cache canonical anchors once (startup or first lazy load)."""
    if _cache.ready:
        return len(_cache.section_ids)

    with _anchor_lock:
        if _cache.ready:
            return len(_cache.section_ids)

        leaves = iter_canonical_leaf_sections()
        section_ids = [row[0] for row in leaves]
        anchor_texts = [build_section_anchor_text(sid) for sid in section_ids]

        embedder = _embeddings.get_embedder()
        vectors = embedder.embed_documents(anchor_texts)
        matrix = _normalize_anchor_matrix(np.asarray(vectors, dtype=np.float32))

        _cache.section_ids = section_ids
        _cache.matrix = matrix
        logger.info(
            "Initialized %d canonical section anchor vectors (dim=%d, cached)",
            len(section_ids),
            matrix.shape[1],
        )
        return len(section_ids)


def reset_section_anchors() -> None:
    """Clear cached anchors (tests / embedder reload)."""
    with _anchor_lock:
        _cache.clear()


def _ensure_anchors() -> None:
    """Lazy load — never re-embed when the startup cache is warm."""
    if not _cache.ready:
        initialize_section_anchors()


def _l2_normalize(vec: np.ndarray) -> np.ndarray:
    """Return a unit vector; zero vectors are returned unchanged."""
    norm = float(np.linalg.norm(vec))
    if norm == 0.0:
        return vec
    return vec / norm


def _normalize_anchor_matrix(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return matrix / norms


def _cosine_similarity_scores(
    note_vec: np.ndarray, anchor_matrix: np.ndarray
) -> np.ndarray:
    """Strict cosine similarity between one note vector and all anchor rows."""
    note_unit = _l2_normalize(note_vec.astype(np.float32, copy=False))
    anchor_unit = _normalize_anchor_matrix(anchor_matrix.astype(np.float32, copy=False))
    return anchor_unit @ note_unit


def _top_two_scores(scores: np.ndarray) -> tuple[int, float, float]:
    best_idx = int(np.argmax(scores))
    best_score = float(scores[best_idx])
    if scores.size <= 1:
        return best_idx, best_score, -1.0
    masked = scores.copy()
    masked[best_idx] = -np.inf
    second_idx = int(np.argmax(masked))
    return best_idx, best_score, float(scores[second_idx])


def classify_note_semantically(text: str) -> tuple[str, float]:
    """Return ``(section_id | UNASSIGNED, score)`` for one note."""
    from backend.domain.notes.keyword_router import classify_note_cascade

    section_id, score, _ = classify_note_cascade(text)
    if section_id != UNASSIGNED:
        return section_id, score
    if settings.note_routing_mode.strip().lower() == "rag":
        return _classify_note_rag(text)
    return UNASSIGNED, 0.0


def _classify_note_rag(text: str) -> tuple[str, float]:
    """Embedding anchor classifier with ambiguity margin (Priority 3 fallback)."""
    _ensure_anchors()
    matrix = _cache.matrix
    if matrix is None or not _cache.section_ids:
        return UNASSIGNED, 0.0

    # Anchor the query with strict L3 disambiguation guidance (prepended, not embedded
    # in user-visible note text).
    query_text = f"{RAG_CLASSIFICATION_GUIDANCE}\n\nNote: {text or ''}"
    note_vec = np.asarray(
        _embeddings.get_embedder().embed_query(query_text), dtype=np.float32
    )
    if float(np.linalg.norm(note_vec)) == 0.0:
        return UNASSIGNED, 0.0

    scores = _cosine_similarity_scores(note_vec, matrix)
    best_idx, best_score, second_score = _top_two_scores(scores)
    threshold = settings.confidence_threshold
    margin = settings.note_rag_ambiguity_margin
    score_gap = best_score - second_score if second_score >= 0.0 else margin

    if best_score < threshold or score_gap < margin:
        if best_score >= threshold and score_gap < margin:
            logger.debug(
                "Ambiguous note routing (top=%s %.3f second=%.3f gap=%.3f): %s",
                _cache.section_ids[best_idx],
                best_score,
                second_score,
                score_gap,
                (text or "")[:120],
            )
        return UNASSIGNED, best_score

    return _cache.section_ids[best_idx], best_score


def route_note_to_section(text: str, schema: TemplateSchema | None = None) -> str:
    """Classify one note → canonical leaf id or ``UNASSIGNED``."""
    _ = schema
    section_id, _ = classify_note_semantically(text)
    return section_id


def _is_hazard_section(section_id: str) -> bool:
    """True for I-group leaves (risks to building / people / grounds).

    Hazards are safety-critical: a hazard mention is always filed in its own
    section and is never silently absorbed into the surrounding element via
    context inheritance.
    """
    return bool(section_id) and section_id.upper().startswith("I")


def _iter_note_lines(raw_notes: str) -> list[str]:
    """Split raw notes into individual lines for per-line cascade routing."""
    raw = (raw_notes or "").replace("\r\n", "\n").strip()
    if not raw:
        return []
    blocks = [b.strip() for b in re.split(r"\n{2,}", raw) if b.strip()]
    if len(blocks) <= 1:
        blocks = [b.strip(" \t-*•") for b in raw.split("\n") if b.strip(" \t-*•")]
    lines: list[str] = []
    for block in blocks:
        lines.extend(_extract_observations(block))
    return lines


def _extract_observations(block: str) -> list[str]:
    raw_lines = re.split(r"\n|(?<=\.)\s+(?=[A-Z])", block)
    observations: list[str] = []
    for line in raw_lines:
        line = line.strip().lstrip("•-*·▸▹◆►").strip()
        if line and len(line) > 5:
            observations.append(line)
    return observations or ([block.strip()] if block.strip() else [])


def _extract_rating_value(text: str, schema: TemplateSchema) -> str | None:
    if not schema.rating_system.detected:
        return None

    for rv in schema.rating_system.values:
        pattern = r"(?<!\w)" + re.escape(rv.value) + r"(?!\w)"
        if re.search(pattern, text, re.IGNORECASE):
            return rv.value

    if schema.rating_system.type == "numeric" or any(
        v.value.isdigit() for v in schema.rating_system.values
    ):
        for rv in schema.rating_system.values:
            if rv.value.isdigit():
                patterns = [
                    r"(?i)\bcr\s*" + rv.value + r"\b",
                    r"(?i)\brating\s+" + rv.value + r"\b",
                    r"(?i)\bcondition\s+" + rv.value + r"\b",
                ]
                for p in patterns:
                    if re.search(p, text):
                        return rv.value
    return None


def _split_blocks(raw_notes: str) -> list[str]:
    raw = (raw_notes or "").replace("\r\n", "\n")
    blocks = [b.strip() for b in re.split(r"\n{2,}", raw.strip()) if b.strip()]
    if len(blocks) <= 1:
        blocks = [b.strip(" \t-*•") for b in raw.split("\n") if b.strip(" \t-*•")]
    return blocks


def parse_notes_to_sections(
    raw_notes: str, schema: TemplateSchema
) -> list[SectionNote]:
    """Route surveyor notes into per-leaf buckets with block-level context.

    Surveyors write one element per paragraph but pack several sentences into it
    (``Chimney stack: ... Flashing is cracked. Repairs and repointing required.``).
    Only the first sentence carries the section label/code, so we route each block
    left to right and apply a *tier lock*:

    * A **strong** signal — an explicit code (``F6,``), an element label
      (``Main roof:``), or curated high-confidence vocabulary (``ceilings``) —
      establishes or overrides the block's running section.
    * A **weak** general-keyword match (bare ``repointing``, ``cracking``) does
      NOT override an already-established context: it inherits the block section.
      It only sets the context when none exists yet (e.g. the block's first line).
    * A **hazard** (I-group) match is always filed in its own section but never
      hijacks the running element context for later sentences.
    * A sentence with no signal inherits the block's running section.

    This stops generic boilerplate (``repairs and repointing``) inside a chimney
    block from being dragged to the walls, without hardcoding any note wording.
    """
    from backend.domain.notes.keyword_router import (
        STRONG_TIERS,
        classify_note_cascade_with_tier,
    )
    from backend.domain.section_scope import storage_section_id

    allowed = valid_leaf_section_ids()
    section_accumulator: dict[str, list[str]] = {}
    section_ratings: dict[str, str | None] = {}
    unassigned_blocks: list[str] = []

    for block in _split_blocks(raw_notes):
        current_context = UNASSIGNED
        for sentence in _extract_observations(block):
            section_id, tier, obs_text = classify_note_cascade_with_tier(sentence)
            if section_id != UNASSIGNED:
                section_id = storage_section_id(section_id.upper())
            routed = (
                section_id
                if section_id != UNASSIGNED and section_id.upper() in allowed
                else UNASSIGNED
            )

            if routed != UNASSIGNED and (
                tier in STRONG_TIERS or current_context == UNASSIGNED
            ):
                # Strong signal, or the first signal in the block → set/override context.
                current_context = routed
                target = routed
            elif routed != UNASSIGNED and _is_hazard_section(routed):
                # Weak hazard mid-block: file it as a hazard, keep the element flow.
                target = routed
            elif current_context != UNASSIGNED:
                # Weak (general) keyword or no signal → inherit the running section.
                target = current_context
            else:
                target = UNASSIGNED

            if target == UNASSIGNED:
                unassigned_blocks.append(obs_text)
                continue
            section_accumulator.setdefault(target, []).append(obs_text)
            if target not in section_ratings:
                rating = _extract_rating_value(obs_text, schema)
                if rating:
                    section_ratings[target] = rating

    notes: list[SectionNote] = []
    for sec in schema.ordered_sections():
        if sec.id.upper() not in allowed:
            continue
        if sec.id in section_accumulator:
            obs = section_accumulator[sec.id]
            notes.append(
                SectionNote(
                    section_id=sec.id,
                    raw_observations=obs,
                    text="\n".join(obs).strip(),
                    rating_value=section_ratings.get(sec.id),
                )
            )

    if unassigned_blocks:
        notes.append(
            SectionNote(
                section_id=UNASSIGNED,
                raw_observations=unassigned_blocks,
                text="\n".join(unassigned_blocks).strip(),
            )
        )
    return notes
