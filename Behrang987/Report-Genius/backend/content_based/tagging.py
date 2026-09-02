"""Tag RAG chunks with content-taxonomy topics at ingest time.

Both ingest paths (past reports, standard paragraphs) call :func:`tag_chunks`
after segmentation and before the vector write, so the same chunks carry a
``topic_id`` / ``subtopic_id`` alongside their RICS ``section_id``. This lets the
content-based topic mode retrieve by topic without a second index or re-embedding.

Tagging never raises: classification failures leave the tags empty (content mode
simply retrieves less for that chunk).
"""

from __future__ import annotations

import logging

from backend.config import settings
from backend.content_based import classifier
from backend.content_based.taxonomy import CONTENT_TAXONOMY_VERSION

logger = logging.getLogger(__name__)


def tag_chunks(chunks: list) -> dict:
    """Stamp ``topic_id`` / ``subtopic_id`` / ``theme_tags`` on each chunk in place.

    Also stamps the taxonomy version the tags were assigned under, so a later
    taxonomy change is detectable instead of silently mismatching at retrieval.

    Returns a small coverage summary (per-topic chunk counts) for logging /
    ingest verification. No-op (empty summary) when content mode is disabled.
    """
    if not settings.content_mode_enabled or not chunks:
        return {}
    try:
        texts = [getattr(c, "text", "") or "" for c in chunks]
        hints = [getattr(c, "section_id", "") or "" for c in chunks]
        results = classifier.classify_batch(texts, section_id_hints=hints)
    except Exception:  # noqa: BLE001 - tagging must never break ingest
        logger.warning("Content topic tagging failed; chunks left untagged.", exc_info=True)
        return {}

    summary: dict[str, int] = {}
    for chunk, result in zip(chunks, results):
        chunk.topic_id = result.topic_id
        chunk.subtopic_id = result.subtopic_id
        chunk.theme_tags = list(result.theme_tags)
        chunk.taxonomy_version = CONTENT_TAXONOMY_VERSION
        summary[result.topic_id] = summary.get(result.topic_id, 0) + 1
    return summary
