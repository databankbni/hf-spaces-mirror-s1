"""Prompts for content-based (topic-first) report generation.

Mirrors the grounding discipline of the RICS-mode prompts: the surveyor's
observations are the ONLY source of facts; retrieved past-report / standard
paragraphs supply house style, tone, and length only.
"""

from __future__ import annotations

CONTENT_TOPIC_SYSTEM = (
    "You are a UK residential building surveyor writing one section of a survey "
    "report. You are given a TOPIC and SUB-TOPIC, the surveyor's field observations "
    "for it, and example paragraphs from approved reports as STYLE reference only.\n\n"
    "Rules:\n"
    "- The surveyor's observations are the ONLY source of facts. Never invent "
    "defects, materials, measurements, or conclusions that are not supported by "
    "them.\n"
    "- Use the example paragraphs only for tone, structure, and professional "
    "wording — do not copy their specific facts.\n"
    "- Write in clear, professional British English, in the third person, present "
    "tense, as continuous prose (no bullet lists, no headings).\n"
    "- If the observations are sparse, write briefly rather than padding.\n"
    "- Do not add a rating line; the rating is handled separately."
)


def build_topic_messages(
    *,
    topic_label: str,
    subtopic_label: str,
    observations: list[str],
    style_paragraphs: list[str],
    rating_value: str | None = None,
) -> list[dict[str, str]]:
    """Build the chat messages for one topic/sub-topic unit."""
    obs = [o.strip() for o in observations if o and o.strip()]
    obs_block = "\n".join(f"- {o}" for o in obs) if obs else "(no specific observations)"
    style_block = (
        "\n\n".join(f"[Example {i + 1}]\n{p.strip()}" for i, p in enumerate(style_paragraphs) if p.strip())
        or "(no examples available — write from the observations alone)"
    )
    heading = subtopic_label or topic_label
    rating_hint = (
        f"\nThe surveyor's RICS rating for this item is {rating_value}. "
        "Make the prose consistent with that severity."
        if rating_value
        else ""
    )
    user = (
        f"TOPIC: {topic_label}\n"
        f"SUB-TOPIC: {heading}{rating_hint}\n\n"
        f"Surveyor observations:\n{obs_block}\n\n"
        f"Style reference paragraphs (do not copy facts):\n{style_block}\n\n"
        f"Write the '{heading}' prose now."
    )
    return [
        {"role": "system", "content": CONTENT_TOPIC_SYSTEM},
        {"role": "user", "content": user},
    ]
