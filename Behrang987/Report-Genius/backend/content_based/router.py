"""Route surveyor notes into content-taxonomy topic buckets.

Content-mode analogue of :func:`backend.domain.notes.routing.route_lines_to_level3_sections`.
A line that opens with a known code prefix ("roof_coverings: ...", written by the
card-driven UI) is placed deterministically; free-form lines are classified by
meaning via :mod:`backend.content_based.classifier`.
"""

from __future__ import annotations

import re
from collections import defaultdict

from backend.content_based import classifier, taxonomy
from backend.content_based.models import TopicBucket

# Canonical RICS 1/2/3/NI ratings (content mode has no per-topic schema).
_RATING_VALUES = ("1", "2", "3", "NI")


def _split_lines(raw_notes: str) -> list[str]:
    raw = (raw_notes or "").replace("\r\n", "\n")
    blocks = [b.strip() for b in re.split(r"\n{2,}", raw.strip()) if b.strip()]
    if len(blocks) <= 1:
        blocks = [b.strip(" \t-*\u2022") for b in raw.split("\n") if b.strip(" \t-*\u2022")]
    return [b for b in blocks if b]


def _parse_code_prefix(line: str) -> tuple[str, str, str] | None:
    """Return ``(topic_id, subtopic_id, body)`` for a ``<code>: body`` prefix."""
    m = re.match(r"^\s*([a-z0-9_]+)\s*:\s*(.+)$", line, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    code = m.group(1).strip().lower()
    body = m.group(2).strip()
    if not body:
        return None
    topic = taxonomy.topic_for_subtopic(code)
    if topic:
        # Canonical id, so a pre-v2 prefix ("heating:") still lands in the right bucket.
        return topic, taxonomy.resolve_subtopic_id(code), body
    if code in taxonomy.valid_topic_ids():
        return code, "", body
    return None


def _extract_rating(text: str) -> str | None:
    for rv in _RATING_VALUES:
        if re.search(r"(?<!\w)" + re.escape(rv) + r"(?!\w)", text, re.IGNORECASE):
            if rv.isdigit():
                return rv
    for rv in ("1", "2", "3"):
        for pat in (
            rf"(?i)\bcr\s*{rv}\b",
            rf"(?i)\brating\s+{rv}\b",
            rf"(?i)\bcondition\s+{rv}\b",
        ):
            if re.search(pat, text):
                return rv
    if re.search(r"(?i)\bNI\b|not inspected", text):
        return "NI"
    return None


def bucket_notes_by_topic(raw_notes: str) -> list[TopicBucket]:
    """Group raw notes into ordered topic/sub-topic buckets for generation."""
    lines = _split_lines(raw_notes)
    if not lines:
        return []

    buckets: dict[tuple[str, str], TopicBucket] = {}

    def _add(topic_id: str, subtopic_id: str, body: str) -> None:
        key = (topic_id, subtopic_id)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = TopicBucket(
                topic_id=topic_id,
                subtopic_id=subtopic_id,
                topic_label=taxonomy.topic_label(topic_id),
                subtopic_label=taxonomy.subtopic_label(topic_id, subtopic_id),
            )
            buckets[key] = bucket
        bucket.observations.append(body)
        rating = _extract_rating(body)
        if rating and not bucket.rating_value:
            bucket.rating_value = rating

    free: list[str] = []
    for line in lines:
        parsed = _parse_code_prefix(line)
        if parsed:
            _add(parsed[0], parsed[1], parsed[2])
        else:
            free.append(line)

    if free:
        for line, result in zip(free, classifier.classify_batch(free)):
            if result.method == "too_short":
                continue
            _add(result.topic_id, result.subtopic_id, line)

    return sorted(
        buckets.values(),
        key=lambda b: (taxonomy.topic_order(b.topic_id), b.subtopic_id),
    )


def route_lines_to_topics(lines: list[str]) -> tuple[dict[str, list[str]], list[str]]:
    """Route note lines into topic buckets keyed by sub-topic code (for /route-notes).

    Mirrors ``route_lines_to_level3_sections``: returns ``(routed, unmatched)`` where
    ``routed`` maps a sub-topic code to its note lines. Content mode always has an
    "Other / General Observations" home, so ``unmatched`` only holds empties.
    """
    cleaned = [ln.strip() for ln in lines if ln and ln.strip() and len(ln.strip()) >= 3]
    routed: dict[str, list[str]] = defaultdict(list)
    unmatched: list[str] = []

    free: list[str] = []
    for line in cleaned:
        parsed = _parse_code_prefix(line)
        if parsed:
            code = parsed[1] or parsed[0]
            routed[code].append(parsed[2])
        else:
            free.append(line)

    if free:
        for line, result in zip(free, classifier.classify_batch(free)):
            if result.method == "too_short":
                unmatched.append(line)
                continue
            code = result.subtopic_id or result.topic_id
            routed[code].append(line)

    return dict(routed), unmatched
