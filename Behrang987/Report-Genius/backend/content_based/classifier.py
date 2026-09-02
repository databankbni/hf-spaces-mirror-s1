"""Content-first topic classification for the content-based report mode.

Classifies a piece of text (a note line, a past-report paragraph, or a standard
paragraph) into the fixed topic taxonomy in :mod:`backend.content_based.taxonomy`
*by meaning*, so reports that do not follow the RICS layout are still understood.

Decision order (per text):
  1. Exact RICS leaf code hint (e.g. ``D2``) -> trust it (structure prior).
  2. LLM pass over everything else — the model reads the taxonomy and places the
     text by meaning. This is the primary classifier: content mode exists for
     documents that carry no structural codes, so there is usually nothing to
     match on but the words themselves.
  3. Deterministic fallback for whatever step 2 did not resolve (LLM disabled,
     no API key, call failed, or the model stayed silent on a snippet):
     RICS parent prior -> room heading -> embedding-anchor cosine.
  4. Fall back to "Other / General Observations", flagged ``needs_review``.

Only the *ingest* path supplies ``section_id_hints`` (a chunk's segmented RICS
code), so steps 1 and the parent prior are inert when routing surveyor notes —
by design, since those notes have no codes to trust.

Embeddings reuse the shared embedder (:mod:`backend.llm.embeddings`); anchor
vectors are built once and cached.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from backend.config import settings
from backend.content_based import taxonomy

logger = logging.getLogger(__name__)

_MIN_CLASSIFY_CHARS = 3
_ROOM_HEADING_MAX_CHARS = 64


@dataclass(frozen=True)
class TopicClassification:
    """Result of classifying one text into the content taxonomy."""

    topic_id: str
    subtopic_id: str
    confidence: float
    method: str  # rics_leaf | rics_parent | room | embedding | llm | catch_all | too_short
    needs_review: bool = False
    """True when no positive identification was made (catch-all), or when the
    classifier's own confidence was too low to rely on. Callers may surface this
    to the surveyor rather than silently filing the text under 'Other'."""
    theme_tags: tuple[str, ...] = ()
    """Cross-cutting themes (damp, movement, ...), orthogonal to the topic. Always
    populated lexically; the LLM's own suggestions are unioned in when it ran."""


# One validated model assignment: (topic_id, subtopic_id, confidence, theme_tags).
_Assignment = tuple[str, str, float, tuple[str, ...]]

# Below this the LLM's self-reported confidence is treated as a guess.
_LLM_LOW_CONFIDENCE = 0.5
# Used when the model places a snippet but omits (or mangles) its confidence.
_LLM_DEFAULT_CONFIDENCE = 0.7


# ── Anchor embedding cache ────────────────────────────────────────────────────
# (cache_key, matrix[N, dim], labels[(topic_id, subtopic_id)])
_anchor_cache: tuple[tuple, object, list[tuple[str, str]]] | None = None


def reset_cache() -> None:
    """Drop the cached anchor matrix (tests / embedder reconfiguration)."""
    global _anchor_cache
    _anchor_cache = None


def _cache_key() -> tuple:
    return (
        (settings.embedding_provider or "local").lower(),
        settings.local_embedding_model,
        settings.openai_embedding_model,
        taxonomy.CONTENT_TAXONOMY_VERSION,
    )


def _normalize(arr):
    import numpy as np

    a = np.asarray(arr, dtype="float32")
    if a.ndim == 1:
        a = a.reshape(1, -1)
    norms = np.linalg.norm(a, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return a / norms


def _get_anchor_matrix():
    """Return ``(matrix, labels)`` of normalized anchor vectors.

    Dynamic-sub-topic topics (Rooms Described) are excluded — rooms are detected
    by heading, not by anchor similarity, to avoid stealing element observations.
    """
    global _anchor_cache
    key = _cache_key()
    if _anchor_cache is not None and _anchor_cache[0] == key:
        return _anchor_cache[1], _anchor_cache[2]

    from backend.llm.embeddings import get_embedder

    rows = [
        (tid, sid, anchor)
        for (tid, sid, anchor) in taxonomy.iter_anchor_units()
        if not taxonomy.has_dynamic_subtopics(tid)
    ]
    texts = [taxonomy.build_topic_anchor_text(tid, sid) for tid, sid, _ in rows]
    labels = [(tid, sid) for tid, sid, _ in rows]
    vecs = get_embedder().embed_documents(texts)
    matrix = _normalize(vecs)
    _anchor_cache = (key, matrix, labels)
    return matrix, labels


# ── Room detection ────────────────────────────────────────────────────────────
_ROOM_TRIGGER_RE = re.compile(
    r"\b(" + "|".join(
        re.escape(trig)
        for triggers in taxonomy.ROOM_LEXICON.values()
        for trig in triggers
    ) + r")\b",
    re.IGNORECASE,
)


def _detect_room_subtopic(text: str) -> str:
    """Return a room sub-topic slug when the text opens with a room heading.

    Room-by-room descriptions lead with the room name ("Kitchen: ...",
    "Front First Floor Bedroom - ..."); inline element mentions ("the kitchen
    units are cracked") are long, non-heading lines and are not routed here.
    """
    if not settings.content_room_detection_enabled:
        return ""
    first_line = (text or "").strip().splitlines()[0] if text.strip() else ""
    # Heading = text before the first colon/dash if short, else the whole first line.
    head = re.split(r"[:\-\u2013\u2014]", first_line, maxsplit=1)[0].strip()
    candidate = head if head else first_line
    if not candidate or len(candidate) > _ROOM_HEADING_MAX_CHARS:
        return ""
    # Strip leading list markers ("1.", "-", "*", bullets).
    candidate = re.sub(r"^[\s\-*\u2022\d.\)]+", "", candidate).strip()
    if not candidate or not _ROOM_TRIGGER_RE.search(candidate):
        return ""
    # Resolve to a stable seed room id (kitchen, bathroom, bedroom, ...) so the
    # taxonomy, note router, and catalog stay aligned.
    return taxonomy.base_room_for(candidate) or taxonomy.normalize_room_subtopic_id(candidate)


# ── Embedding classification ────────────────────────────────────────────────
def _score_rows(query_vecs):
    """Return the full [n_texts, n_anchors] cosine score matrix."""
    import numpy as np

    matrix, labels = _get_anchor_matrix()
    q = _normalize(query_vecs)
    scores = q @ np.asarray(matrix).T  # cosine (all normalized)
    return scores, labels


def _best_for_row(scores_row, labels, *, topic_id: str = "") -> tuple[str, str, float]:
    """Argmax anchor for one score row, optionally restricted to a topic."""
    import numpy as np

    row = np.asarray(scores_row)
    if topic_id:
        idxs = [i for i, (tid, _sid) in enumerate(labels) if tid == topic_id]
        if not idxs:
            return topic_id, "", 0.0
        sub = row[idxs]
        j = int(np.argmax(sub))
        best_i = idxs[j]
        return labels[best_i][0], labels[best_i][1], float(row[best_i])
    best_i = int(np.argmax(row))
    return labels[best_i][0], labels[best_i][1], float(row[best_i])


# ── Public API ────────────────────────────────────────────────────────────────
def classify_text(text: str, *, section_id_hint: str = "") -> TopicClassification:
    """Classify a single text into ``(topic_id, subtopic_id)``."""
    return classify_batch([text], section_id_hints=[section_id_hint])[0]


def classify_batch(
    texts: list[str],
    *,
    section_id_hints: list[str] | None = None,
) -> list[TopicClassification]:
    """Classify many texts at once (windowed LLM call, batched embedding fallback)."""
    n = len(texts)
    hints = list(section_id_hints or [])
    hints += [""] * (n - len(hints))
    results: list[TopicClassification | None] = [None] * n
    # Themes are independent of the topic decision, so they are resolved for every
    # snippet up front — including the many that short-circuit on a leaf code.
    lexical_tags = [tuple(taxonomy.theme_tags_for_text(t or "")) for t in texts]

    # Pass 1 — structural certainties. An exact leaf code is better than anything
    # we could buy from the model, so those never reach it.
    pending: list[int] = []
    for i, raw in enumerate(texts):
        text = (raw or "").strip()
        if len(text) < _MIN_CLASSIFY_CHARS:
            results[i] = TopicClassification(*taxonomy.catch_all(), 0.0, "too_short")
            continue
        prior = taxonomy.section_prior(hints[i])
        if prior and prior[2] == "leaf":
            results[i] = TopicClassification(
                prior[0], prior[1], 0.99, "rics_leaf", theme_tags=lexical_tags[i]
            )
            continue
        pending.append(i)

    # Pass 2 — the LLM reads the taxonomy and places the rest by meaning.
    unresolved = pending
    if pending and settings.content_classifier_llm_enabled:
        assignments = _llm_classify_batch([(texts[i] or "").strip() for i in pending])
        still: list[int] = []
        for k, i in enumerate(pending):
            assigned = assignments[k] if k < len(assignments) else None
            if assigned is None:
                still.append(i)
                continue
            topic_id, subtopic_id, confidence, llm_tags = assigned
            results[i] = TopicClassification(
                topic_id,
                subtopic_id,
                confidence,
                "llm",
                needs_review=confidence < _LLM_LOW_CONFIDENCE,
                theme_tags=_merge_tags(lexical_tags[i], llm_tags),
            )
        unresolved = still

    # Pass 3 — deterministic fallback for whatever the model did not place.
    if unresolved:
        _fallback_classify(texts, hints, unresolved, results, lexical_tags)

    return [
        r or TopicClassification(*taxonomy.catch_all(), 0.0, "catch_all", needs_review=True)
        for r in results
    ]


def _merge_tags(lexical: tuple[str, ...], model: tuple[str, ...]) -> tuple[str, ...]:
    """Union two tag sets back into canonical vocabulary order."""
    return tuple(taxonomy.normalize_theme_tags([*lexical, *model]))


def _fallback_classify(
    texts: list[str],
    hints: list[str],
    indices: list[int],
    results: list[TopicClassification | None],
    lexical_tags: list[tuple[str, ...]],
) -> None:
    """Place texts the LLM did not resolve, writing into ``results`` in place.

    This is also the whole classifier when the LLM is disabled or no API key is
    configured, which is what keeps content mode usable offline.
    """
    scores = labels = None
    try:
        from backend.llm.embeddings import get_embedder

        batch_texts = [(texts[i] or "").strip() for i in indices]
        qvecs = get_embedder().embed_documents(batch_texts)
        scores, labels = _score_rows(qvecs)
    except Exception:  # noqa: BLE001 - never fail ingest on classification
        logger.warning(
            "Topic embedding classification unavailable; using priors/catch-all.",
            exc_info=True,
        )

    min_score = float(settings.content_topic_min_score)
    for pos, i in enumerate(indices):
        text = (texts[i] or "").strip()
        prior = taxonomy.section_prior(hints[i])

        emb_topic = emb_sub = ""
        emb_score = 0.0
        if scores is not None and labels is not None:
            emb_topic, emb_sub, emb_score = _best_for_row(scores[pos], labels)

        # Structural topic prior (e.g. parent C/D/E/F/G): keep the topic, refine
        # the sub-topic by content within that topic.
        if prior and prior[2] == "parent":
            topic_id = prior[0]
            if scores is not None and labels is not None:
                _t, sub, sub_score = _best_for_row(scores[pos], labels, topic_id=topic_id)
                sub = sub or prior[1]
                conf = max(sub_score, 0.6)
            else:
                sub, conf = prior[1], 0.6
            results[i] = TopicClassification(
                topic_id, sub, conf, "rics_parent", theme_tags=lexical_tags[i]
            )
            continue

        # No structural prior (typical for non-RICS reports) — content decides.
        room_sub = _detect_room_subtopic(text)
        if room_sub:
            results[i] = TopicClassification(
                taxonomy.TOPIC_ROOMS_DESCRIBED,
                room_sub,
                0.9,
                "room",
                theme_tags=lexical_tags[i],
            )
            continue
        if emb_score >= min_score and emb_topic:
            results[i] = TopicClassification(
                emb_topic, emb_sub, emb_score, "embedding", theme_tags=lexical_tags[i]
            )
            continue
        results[i] = TopicClassification(
            *taxonomy.catch_all(),
            0.0,
            "catch_all",
            needs_review=True,
            theme_tags=lexical_tags[i],
        )


# ── Optional LLM classifier ────────────────────────────────────────────────
def _taxonomy_prompt_block() -> str:
    lines: list[str] = []
    for tid in taxonomy.ORDERED_TOPIC_IDS:
        subs = taxonomy.subtopics_for_topic(tid)
        sub_str = ", ".join(f"{sid} ({label})" for sid, label in subs) or "(free-form)"
        lines.append(f"- {tid} ({taxonomy.topic_label(tid)}): {sub_str}")
    return "\n".join(lines)


_LLM_SYSTEM = (
    "You classify UK residential building-survey text into a FIXED topic taxonomy. "
    "Decide from the CONTENT of each snippet — the source documents do not follow a "
    "standard layout, so headings and numbering are unreliable. For each numbered "
    "snippet choose the single best topic id and sub-topic id from the list. "
    "If a snippet describes an individual room (kitchen, bathroom, a named bedroom, "
    "conservatory, ...), use topic 'rooms_described' and set subtopic to a short "
    "snake_case room slug. If a snippet is address, tenure, locality or general "
    "property-description text, it belongs to 'location_facilities', not to a "
    "building-element topic. Only use topic 'other' / subtopic 'general' when the "
    "snippet genuinely fits nothing else. "
    "Separately, list any cross-cutting THEMES the snippet raises, chosen only from "
    "the theme list. Themes are independent of the topic: a damp patch on a bedroom "
    "wall is topic 'inside'/'walls_partitions' with theme 'damp'. Use [] when the "
    "snippet raises none. "
    "Return one item for EVERY snippet, with 'confidence' between 0 and 1 reflecting "
    "how sure you are. Return ONLY JSON: {\"items\":[{\"i\":<int>,\"topic\":\"<id>\","
    "\"subtopic\":\"<id>\",\"confidence\":<number>,\"tags\":[\"<theme>\"]}]}."
)


def _theme_tag_prompt_block() -> str:
    return "\n".join(
        f"- {tag}: {desc}" for tag, desc in taxonomy.CONTENT_THEME_TAGS.items()
    )


def _llm_classify_batch(texts: list[str]) -> list[_Assignment | None]:
    """Classify snippets with the LLM, windowed so a large ingest still fits.

    Returns one ``(topic_id, subtopic_id, confidence, theme_tags)`` per input, or
    ``None`` where the model gave nothing usable so the caller can fall back. A
    failing window degrades only its own snippets.
    """
    from backend.llm import openai_client

    if not texts or not openai_client.is_available():
        return [None] * len(texts)

    out: list[_Assignment | None] = [None] * len(texts)
    size = max(1, int(settings.content_classification_window_size))
    for lo in range(0, len(texts), size):
        window = texts[lo : lo + size]
        try:
            assigned = _classify_window(window)
        except Exception:  # noqa: BLE001 - classification must never break ingest
            logger.warning(
                "LLM topic classification window [%d,%d) failed; falling back for those snippets.",
                lo,
                lo + len(window),
                exc_info=True,
            )
            continue
        for k, item in enumerate(assigned):
            out[lo + k] = item
    return out


def _classify_window(texts: list[str]) -> list[_Assignment | None]:
    """One classification call; retry once when the model returns nothing usable."""
    from backend.llm import openai_client

    cap = max(200, int(settings.content_classification_max_chars))
    numbered = "\n".join(f"[{i}] {t[:cap]}" for i, t in enumerate(texts))
    messages = [
        {"role": "system", "content": _LLM_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Topics and sub-topics:\n{_taxonomy_prompt_block()}\n\n"
                f"Themes:\n{_theme_tag_prompt_block()}\n\n"
                f"Snippets:\n{numbered}"
            ),
        },
    ]
    effort = (settings.content_classification_reasoning_effort or "minimal").strip()
    for attempt in (0, 1):
        raw = openai_client.chat_json(
            messages,
            model=settings.content_classification_model or settings.discovery_model,
            temperature=0.0,
            timeout=float(settings.content_classification_timeout_seconds),
            max_tokens=int(settings.content_classification_max_tokens),
            reasoning_effort=effort,
            call_label="content_classification",
        )
        parsed = _parse_assignments(raw, len(texts))
        if any(p is not None for p in parsed):
            return parsed
        if attempt == 0:
            logger.info(
                "LLM topic classification returned nothing usable for %d snippets; retrying once.",
                len(texts),
            )
    logger.warning(
        "LLM topic classification empty after retry for %d snippets; using fallback.",
        len(texts),
    )
    return [None] * len(texts)


def _parse_assignments(raw: object, count: int) -> list[_Assignment | None]:
    """Validate a model payload into per-snippet assignments."""
    out: list[_Assignment | None] = [None] * count
    items = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("i"))
        except (TypeError, ValueError):
            continue
        if not (0 <= idx < count):
            continue
        validated = _validate_assignment(
            str(item.get("topic") or "").strip(),
            str(item.get("subtopic") or "").strip(),
        )
        if validated is None:
            continue
        out[idx] = (
            *validated,
            _coerce_confidence(item.get("confidence")),
            tuple(taxonomy.normalize_theme_tags(item.get("tags"))),
        )
    return out


def _coerce_confidence(value: object) -> float:
    """Clamp a model-reported confidence into [0, 1]; default when unusable."""
    try:
        conf = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return _LLM_DEFAULT_CONFIDENCE
    if conf != conf:  # NaN
        return _LLM_DEFAULT_CONFIDENCE
    return max(0.0, min(1.0, conf))


def _validate_assignment(topic: str, subtopic: str) -> tuple[str, str] | None:
    if topic not in taxonomy.valid_topic_ids():
        return None
    if taxonomy.has_dynamic_subtopics(topic):
        # Rooms Described: resolve to a seed room id when recognisable, else slug.
        if not subtopic:
            return topic, taxonomy.CATCH_ALL_SUBTOPIC
        return topic, (
            taxonomy.base_room_for(subtopic) or taxonomy.normalize_room_subtopic_id(subtopic)
        )
    valid_subs = taxonomy.valid_subtopic_ids(topic)
    if subtopic in valid_subs:
        return topic, subtopic
    # Topic is valid but sub-topic isn't — keep the topic, drop to its catch-all-ish first sub.
    subs = taxonomy.subtopics_for_topic(topic)
    return topic, (subs[0][0] if subs else "")
