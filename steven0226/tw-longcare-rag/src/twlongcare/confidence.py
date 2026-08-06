"""Explainable pre-generation retrieval confidence grading.

This is intentionally separate from post-generation sentence grounding:

* this module grades evidence *before* an answer is generated;
* ``refine_once`` may trigger one bounded retrieval retry;
* ``grounding.py`` checks generated sentences afterwards.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum

from .evidence import EvidencePlan
from .retriever import RetrievedChunk, RetrievalDiagnostics
from .routing import QueryRoute, RouteResult
from .structured import LAW_ALIASES


class AdaptiveMode(StrEnum):
    CURRENT_BASELINE = "current_baseline"
    CONFIDENCE_GATE_ONLY = "confidence_gate_only"
    REFINEMENT_ENABLED = "refinement_enabled"
    FULL_ADAPTIVE_ROUTE = "full_adaptive_route"


class GateDecision(StrEnum):
    ANSWER = "answer"
    REFINE_ONCE = "refine_once"
    REFUSE = "refuse"


@dataclass(frozen=True)
class GatePolicy:
    """Thresholds calibrated on development data, never on the locked test."""

    min_top1: float = 0.60
    strong_top1: float = 0.69
    min_margin: float = 0.015
    min_overlap_count: int = 1
    min_overlap_jaccard: float = 0.03
    max_refinements: int = 1
    max_query_tokens: int = 384
    version: str = "gate-calibration-v1"


@dataclass(frozen=True)
class GateSignals:
    top1_rerank: float | None
    top1_top2_margin: float | None
    bm25_dense_overlap_count: int
    bm25_dense_overlap_jaccard: float
    required_articles: tuple[str, ...]
    retrieved_articles: tuple[str, ...]
    graph_articles: tuple[str, ...]
    required_article_coverage: float | None
    graph_added_required_article: bool
    ambiguous_or_multi_hop: bool
    evidence_requirement_coverage: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class GateResult:
    decision: GateDecision
    reason: str
    confidence: float
    signals: GateSignals
    rules_triggered: tuple[str, ...] = field(default_factory=tuple)
    policy_version: str = "gate-calibration-v1"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["decision"] = self.decision.value
        return data


_ARTICLE_RE = re.compile(r"第\s*([0-9]+(?:\s*[-之]\s*[0-9]+)?)\s*條")


def extract_required_articles(question: str) -> tuple[str, ...]:
    """Extract explicit ``pcode-article`` requirements from a user question."""
    pcodes: list[str] = []
    for alias in sorted(LAW_ALIASES, key=len, reverse=True):
        if alias in question:
            pcode = LAW_ALIASES[alias]
            if pcode not in pcodes:
                pcodes.append(pcode)
            # Avoid also matching a shorter alias contained in the same name.
            question = question.replace(alias, " ")
    article_nos = [
        match.replace(" ", "").replace("之", "-")
        for match in _ARTICLE_RE.findall(question)
    ]
    return tuple(f"{pcode}-{no}" for pcode in pcodes for no in article_nos)


def build_gate_signals(
    question: str,
    retrieved: list[RetrievedChunk],
    diagnostics: RetrievalDiagnostics | None,
    related: list,
    route: RouteResult,
    evidence_plan: EvidencePlan | None = None,
) -> GateSignals:
    scores = [
        float(chunk.rerank_score)
        for chunk in retrieved
        if chunk.rerank_score is not None
    ]
    top1 = scores[0] if scores else None
    margin = scores[0] - scores[1] if len(scores) > 1 else None
    required = extract_required_articles(question)
    direct = tuple(dict.fromkeys(chunk.parent_id for chunk in retrieved))
    graph = tuple(
        dict.fromkeys(f"{item.pcode}-{item.article_no}" for item in related)
    )
    covered = set(direct) | set(graph)
    coverage = (
        len(set(required) & covered) / len(set(required))
        if required
        else None
    )
    graph_added = bool(set(required) & set(graph) - set(direct))
    return GateSignals(
        top1_rerank=top1,
        top1_top2_margin=margin,
        bm25_dense_overlap_count=(
            diagnostics.bm25_dense_overlap_count if diagnostics else 0
        ),
        bm25_dense_overlap_jaccard=(
            diagnostics.bm25_dense_overlap_jaccard if diagnostics else 0.0
        ),
        required_articles=required,
        retrieved_articles=direct,
        graph_articles=graph,
        required_article_coverage=coverage,
        graph_added_required_article=graph_added,
        ambiguous_or_multi_hop=(
            route.route == QueryRoute.CORRECTIVE_CANDIDATE
            or (
                route.route == QueryRoute.GLOBAL_OR_MULTI_HOP
                and route.handler == "citation_graph"
            )
        ),
        evidence_requirement_coverage=(
            evidence_plan.coverage if evidence_plan is not None else None
        ),
    )


def grade_retrieval(
    signals: GateSignals,
    *,
    refinement_count: int = 0,
    policy: GatePolicy | None = None,
) -> GateResult:
    """Grade evidence using several interpretable signals.

    No single score can independently produce ``answer``.  A clearly missing
    explicit article or an empty result may refuse; mixed/ambiguous evidence
    requests at most one refinement; after that retry the decision is terminal.
    """
    policy = policy or GatePolicy()
    triggered: list[str] = []

    if signals.top1_rerank is None:
        triggered.append("missing_reranker_score")
    elif signals.top1_rerank < policy.min_top1:
        triggered.append("low_top1")
    elif signals.top1_rerank >= policy.strong_top1:
        triggered.append("strong_top1")

    if (
        signals.top1_top2_margin is not None
        and signals.top1_top2_margin < policy.min_margin
    ):
        triggered.append("small_top1_top2_margin")

    overlap_ok = (
        signals.bm25_dense_overlap_count >= policy.min_overlap_count
        or signals.bm25_dense_overlap_jaccard >= policy.min_overlap_jaccard
    )
    if not overlap_ok:
        triggered.append("no_lexical_semantic_overlap")

    if signals.required_article_coverage == 0:
        triggered.append("explicit_article_missing")
    elif (
        signals.required_article_coverage is not None
        and signals.required_article_coverage < 1
    ):
        triggered.append("partial_explicit_article_coverage")

    if signals.graph_added_required_article:
        triggered.append("graph_rescued_required_article")
    if signals.ambiguous_or_multi_hop:
        triggered.append("ambiguous_or_multi_hop")
    if (
        signals.evidence_requirement_coverage is not None
        and signals.evidence_requirement_coverage < 1
    ):
        triggered.append("incomplete_evidence_requirements")

    initial_hard_fail = (
        signals.top1_rerank is None
        or signals.required_article_coverage == 0
        or (
            signals.top1_rerank < policy.min_top1
            and not overlap_ok
        )
    )
    uncertain = (
        signals.ambiguous_or_multi_hop
        or not overlap_ok
        or "partial_explicit_article_coverage" in triggered
        or "small_top1_top2_margin" in triggered
        or "incomplete_evidence_requirements" in triggered
        or (
            signals.top1_rerank is not None
            and signals.top1_rerank < policy.strong_top1
        )
    )

    if refinement_count < policy.max_refinements and (initial_hard_fail or uncertain):
        return GateResult(
            GateDecision.REFINE_ONCE,
            "retrieval evidence is incomplete or conflicting; one bounded refinement is allowed",
            0.78,
            signals,
            tuple(triggered),
            policy.version,
        )
    terminal_hard_fail = (
        signals.top1_rerank is None
        or signals.required_article_coverage == 0
        or (
            signals.top1_rerank is not None
            and signals.top1_rerank < policy.min_top1
        )
        or not overlap_ok
        or (
            signals.evidence_requirement_coverage is not None
            and signals.evidence_requirement_coverage < 1
        )
    )
    if terminal_hard_fail:
        return GateResult(
            GateDecision.REFUSE,
            "retrieval remained insufficient after the allowed refinement",
            0.92,
            signals,
            tuple(triggered),
            policy.version,
        )
    return GateResult(
        GateDecision.ANSWER,
        "multiple retrieval signals support generation",
        0.86,
        signals,
        tuple(triggered),
        policy.version,
    )
