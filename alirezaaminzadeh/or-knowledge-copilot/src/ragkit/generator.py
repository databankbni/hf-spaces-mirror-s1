"""Extractive answer composer with mandatory citations and abstention."""

from __future__ import annotations

import re

from ragkit.models import (
    Citation,
    ConfidenceLevel,
    QueryResult,
    RetrievalHit,
    confidence_level_from_score,
)
from ragkit.text import tokenize


def generate_answer(
    question: str,
    hits: list[RetrievalHit],
    language: str = "en",
    rewritten_query: str = "",
    abstain_threshold: float = 0.18,
    extras: dict | None = None,
    route: str = "document",
    product: str = "assistant",
) -> QueryResult:
    if not hits or hits[0].score < abstain_threshold:
        return QueryResult(
            question=question,
            answer=_no_answer(language, product),
            citations=[],
            confidence=float(hits[0].score) if hits else 0.0,
            confidence_level=ConfidenceLevel.ABSTAIN,
            language=language,
            retrieval_hits=hits,
            abstained=True,
            route=route,
            extras=extras or {},
            rewritten_query=rewritten_query,
        )

    top_score = hits[0].score
    confidence = min(0.98, round(top_score, 4))
    level = confidence_level_from_score(confidence, abstain_threshold)
    selected = _select_sentences(question, hits)
    citations: list[Citation] = []
    parts: list[str] = []
    for idx, (sentence, hit) in enumerate(selected[:4], start=1):
        citations.append(
            Citation(
                index=idx,
                chunk_id=hit.chunk.chunk_id,
                doc_id=hit.chunk.doc_id,
                doc_title=hit.chunk.doc_title,
                section=hit.chunk.section,
                page=hit.chunk.page,
                paragraph=hit.chunk.paragraph,
                excerpt=_truncate(hit.chunk.text, 240),
                relevance_score=round(hit.score, 4),
                layer=hit.chunk.layer,
                modality=hit.chunk.modality,
            )
        )
        parts.append(f"{sentence} [{idx}]")
    answer = " ".join(parts) if parts else _truncate(hits[0].chunk.text, 280)
    if level == ConfidenceLevel.LOW:
        answer += " " + _low_confidence_note(language)
    return QueryResult(
        question=question,
        answer=answer,
        citations=citations,
        confidence=confidence,
        confidence_level=level,
        language=language,
        retrieval_hits=hits,
        abstained=False,
        route=route,
        extras=extras or {},
        rewritten_query=rewritten_query,
    )


def _select_sentences(question: str, hits: list[RetrievalHit]) -> list[tuple[str, RetrievalHit]]:
    query_tokens = set(tokenize(question))
    scored: list[tuple[float, str, RetrievalHit]] = []
    for hit in hits:
        for sentence in _split_sentences(hit.chunk.text):
            tokens = set(tokenize(sentence))
            if len(tokens) < 3:
                continue
            overlap = len(query_tokens & tokens) / max(len(query_tokens), 1)
            length_penalty = 1.0 if 40 <= len(sentence) <= 320 else 0.86
            score = (0.62 * overlap + 0.38 * hit.score) * length_penalty
            scored.append((score, sentence.strip(), hit))
    scored.sort(key=lambda x: x[0], reverse=True)
    seen: set[str] = set()
    selected: list[tuple[str, RetrievalHit]] = []
    for _, sentence, hit in scored:
        key = sentence[:90].lower()
        if key in seen:
            continue
        seen.add(key)
        selected.append((sentence, hit))
        if len(selected) >= 4:
            break
    if not selected and hits:
        selected.append((_truncate(hits[0].chunk.text, 280), hits[0]))
    return selected


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?؟])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _no_answer(language: str, product: str) -> str:
    if language == "fa":
        return (
            f"در پایگاه دانش {product} منبعی با اطمینان کافی پیدا نشد. "
            "سؤال را دقیق‌تر بپرسید یا سند مرتبط را ایندکس کنید. هیچ ادعایی بدون استناد ارائه نمی‌شود."
        )
    return (
        f"No sufficiently confident source was found in the {product} knowledge base. "
        "Rephrase the question or index the missing document. Answers are never invented without citations."
    )


def _low_confidence_note(language: str) -> str:
    if language == "fa":
        return "این پاسخ با اطمینان پایین بازیابی شده است؛ منبع را قبل از اقدام بررسی کنید."
    return "Retrieved with low confidence — verify the cited source before acting."
