"""Typed query-route contract.

The existing deterministic routers remain the source of truth.  This module
adds a stable contract around them so route decisions can be traced and
evaluated without turning routing into an unbounded agent loop.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from enum import StrEnum

from .structured import (
    detect_enumeration_query,
    detect_global_question,
    detect_meta_query,
)


class QueryRoute(StrEnum):
    NO_RETRIEVAL = "no_retrieval"
    STRUCTURED = "structured"
    SINGLE_HOP = "single_hop"
    GLOBAL_OR_MULTI_HOP = "global_or_multi_hop"
    CORRECTIVE_CANDIDATE = "corrective_candidate"


@dataclass(frozen=True)
class RouteResult:
    route: QueryRoute
    reason: str
    confidence: float
    matched_pcodes: tuple[str, ...] = ()
    handler: str = "hybrid_retrieval"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["route"] = self.route.value
        return data


_AMBIGUOUS_RE = re.compile(
    r"^(這|那|它|這個|那個|怎麼辦|可以嗎|是否合法|有沒有問題)[？?。\s]*$|"
    r"^(這個|那個).{0,6}(可以嗎|是否合法|怎麼辦)[？?。\s]*$|"
    r"(上面|前面|剛才|這件事|那件事|某個規定|相關規定)"
)
_MULTI_HOP_RE = re.compile(
    r"(同時|以及|還有).{0,20}(資格|給付|申請|處罰|設立)|"
    r"(先|之後|再).{0,30}(申請|設立|變更|處罰)|"
    r"(依據|引用|準用).{0,12}(哪些|哪一|何種).{0,8}(法|條)"
)


def route_query(question: str) -> RouteResult:
    """Return one explainable route decision.

    Ordering deliberately mirrors the pre-existing pipeline: meta, structured
    enumeration and global summaries are decided before retrieval.  The final
    two heuristics only mark queries as corrective candidates; the confidence
    gate still decides whether retrieval is actually refined.
    """
    normalized = question.strip()
    if detect_meta_query(normalized):
        return RouteResult(
            QueryRoute.NO_RETRIEVAL,
            "matched deterministic system/meta intent",
            0.99,
            handler="meta_response",
        )

    pcode = detect_enumeration_query(normalized)
    if pcode is not None:
        return RouteResult(
            QueryRoute.STRUCTURED,
            "matched law enumeration/catalog intent with a known law",
            0.99,
            (pcode,),
            "law_overview",
        )

    pcodes = detect_global_question(normalized)
    if pcodes is not None:
        return RouteResult(
            QueryRoute.GLOBAL_OR_MULTI_HOP,
            "matched whole-law, cross-law, or cross-chapter summary intent",
            0.96,
            tuple(pcodes),
            "chapter_summary",
        )

    if len(normalized) < 5 or _AMBIGUOUS_RE.search(normalized):
        return RouteResult(
            QueryRoute.CORRECTIVE_CANDIDATE,
            "query is underspecified or depends on missing conversational context",
            0.82,
        )

    if _MULTI_HOP_RE.search(normalized):
        return RouteResult(
            QueryRoute.GLOBAL_OR_MULTI_HOP,
            "query combines multiple legal conditions or an explicit dependency chain",
            0.78,
            handler="citation_graph",
        )

    return RouteResult(
        QueryRoute.SINGLE_HOP,
        "default route for a scoped legal question",
        0.90,
    )


def route_requires_retrieval(route: RouteResult) -> bool:
    return route.route in {
        QueryRoute.SINGLE_HOP,
        QueryRoute.CORRECTIVE_CANDIDATE,
    } or (
        route.route == QueryRoute.GLOBAL_OR_MULTI_HOP
        and route.handler == "citation_graph"
    )
