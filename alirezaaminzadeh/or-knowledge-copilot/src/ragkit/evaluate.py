"""Reproducible RAG evaluation (hit rate, keyword coverage, abstention)."""

from __future__ import annotations

from typing import Any, Callable

from ragkit.models import QueryResult


def evaluate_qa(
    ask: Callable[[dict[str, Any]], QueryResult],
    pairs: list[dict[str, Any]],
    min_doc_hit_rate: float = 0.80,
    min_keyword_hit_rate: float = 0.75,
    min_abstain_rate: float = 0.66,
) -> dict[str, Any]:
    positive = [p for p in pairs if not p.get("expect_abstain")]
    negative = [p for p in pairs if p.get("expect_abstain")]
    doc_hits = 0
    keyword_hits = 0
    details: list[dict[str, Any]] = []

    for pair in positive:
        result = ask(pair)
        cited_docs = {c.doc_id for c in result.citations}
        top_doc = result.retrieval_hits[0].chunk.doc_id if result.retrieval_hits else ""
        expected = pair.get("expected_doc_id", "")
        doc_ok = expected in cited_docs or top_doc == expected
        if doc_ok:
            doc_hits += 1
        answer_lower = result.answer.lower()
        keywords = pair.get("expected_keywords") or []
        kw_ok = any(str(k).lower() in answer_lower for k in keywords) if keywords else True
        if kw_ok:
            keyword_hits += 1
        details.append(
            {
                "id": pair.get("id"),
                "doc_hit": doc_ok,
                "keyword_hit": kw_ok,
                "confidence": result.confidence,
                "abstained": result.abstained,
                "top_doc": top_doc,
            }
        )

    abstain_ok = 0
    for pair in negative:
        result = ask(pair)
        ok = result.abstained or result.confidence_level.value == "abstain"
        if ok:
            abstain_ok += 1
        details.append(
            {
                "id": pair.get("id"),
                "expect_abstain": True,
                "passed": ok,
                "confidence": result.confidence,
            }
        )

    n_pos = max(len(positive), 1)
    n_neg = max(len(negative), 1)
    report = {
        "positive_pairs": len(positive),
        "negative_pairs": len(negative),
        "doc_hit_rate": round(doc_hits / n_pos, 4),
        "keyword_hit_rate": round(keyword_hits / n_pos, 4),
        "abstain_rate": round(abstain_ok / n_neg, 4) if negative else 1.0,
        "thresholds": {
            "min_doc_hit_rate": min_doc_hit_rate,
            "min_keyword_hit_rate": min_keyword_hit_rate,
            "min_abstain_rate": min_abstain_rate,
        },
        "passed": (
            doc_hits / n_pos >= min_doc_hit_rate
            and keyword_hits / n_pos >= min_keyword_hit_rate
            and (abstain_ok / n_neg >= min_abstain_rate if negative else True)
        ),
        "details": details,
    }
    return report
