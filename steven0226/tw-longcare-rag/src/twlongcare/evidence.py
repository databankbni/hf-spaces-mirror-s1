"""Deterministic evidence requirements for traceable multi-hop retrieval.

This module does not generate an answer and does not ask an LLM to grade
itself.  It turns a small set of observable query facets into explicit
requirements, then records which direct or graph-expanded articles satisfy
each requirement.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .retriever import RetrievedChunk
from .routing import QueryRoute, RouteResult


@dataclass(frozen=True)
class EvidenceRequirement:
    requirement_id: str
    description: str
    query_terms: tuple[str, ...]
    satisfied_article_ids: tuple[str, ...] = field(default_factory=tuple)

    @property
    def satisfied(self) -> bool:
        return bool(self.satisfied_article_ids)

    def to_dict(self) -> dict:
        return {**asdict(self), "satisfied": self.satisfied}


@dataclass(frozen=True)
class EvidencePlan:
    strategy: str
    requirements: tuple[EvidenceRequirement, ...]

    @property
    def coverage(self) -> float | None:
        if not self.requirements:
            return None
        return sum(item.satisfied for item in self.requirements) / len(
            self.requirements
        )

    @property
    def missing_requirement_ids(self) -> tuple[str, ...]:
        return tuple(
            item.requirement_id for item in self.requirements if not item.satisfied
        )

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "coverage": self.coverage,
            "missing_requirement_ids": list(self.missing_requirement_ids),
            "requirements": [item.to_dict() for item in self.requirements],
        }


_FACETS: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "eligibility",
        "資格、適用對象或前提條件",
        ("資格", "符合", "對象", "誰可以", "失能", "幾歲"),
        ("資格", "符合", "對象", "申請", "失能", "年滿", "以上"),
    ),
    (
        "application",
        "申請、評估或受理程序",
        ("申請", "評估", "送件", "受理", "辦理"),
        ("申請", "評估", "受理", "文件", "主管機關", "照管中心"),
    ),
    (
        "establishment",
        "籌設、設立或許可條件",
        ("設立", "籌設", "開辦", "許可"),
        ("設立", "籌設", "許可", "長照機構", "應備文件"),
    ),
    (
        "benefit",
        "給付、補助、額度或費用負擔",
        ("給付", "補助", "額度", "費用", "負擔"),
        ("給付", "補助", "額度", "費用", "負擔", "自付"),
    ),
    (
        "restriction",
        "限制、禁止、期限或例外",
        ("限制", "不得", "禁止", "期限", "多久", "例外", "最長"),
        ("不得", "限制", "期限", "日內", "年", "月", "例外"),
    ),
)


def _evidence_rows(retrieved: list[RetrievedChunk], related: list) -> list[tuple[str, str]]:
    rows = [(item.parent_id, item.text) for item in retrieved]
    rows.extend(
        (f"{item.pcode}-{item.article_no}", item.content) for item in related
    )
    return rows


def _matching_articles(
    rows: list[tuple[str, str]],
    evidence_terms: tuple[str, ...],
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            article_id
            for article_id, text in rows
            if any(term in text for term in evidence_terms)
        )
    )


def build_evidence_plan(
    question: str,
    route: RouteResult,
    retrieved: list[RetrievedChunk],
    related: list,
    *,
    required_articles: tuple[str, ...] = (),
) -> EvidencePlan:
    """Build and grade a bounded evidence plan from observable query facets."""
    rows = _evidence_rows(retrieved, related)
    requirements: list[EvidenceRequirement] = []

    for article_id in required_articles:
        requirements.append(
            EvidenceRequirement(
                requirement_id=f"explicit:{article_id}",
                description=f"使用者明確指定法條 {article_id}",
                query_terms=(article_id,),
                satisfied_article_ids=tuple(
                    row_id for row_id, _ in rows if row_id == article_id
                ),
            )
        )

    is_multi_hop = (
        route.route == QueryRoute.GLOBAL_OR_MULTI_HOP
        and route.handler == "citation_graph"
    )
    if is_multi_hop:
        for facet_id, description, query_terms, evidence_terms in _FACETS:
            if not any(term in question for term in query_terms):
                continue
            requirements.append(
                EvidenceRequirement(
                    requirement_id=f"facet:{facet_id}",
                    description=description,
                    query_terms=tuple(
                        term for term in query_terms if term in question
                    ),
                    satisfied_article_ids=_matching_articles(rows, evidence_terms),
                )
            )

    # A multi-hop route should have at least two independently visible facets.
    # If the deterministic vocabulary cannot extract them, trace that gap rather
    # than pretending coverage is complete.
    if is_multi_hop and len(requirements) < 2:
        requirements.append(
            EvidenceRequirement(
                requirement_id="facet:unresolved_second_hop",
                description="第二個跨條文條件尚未由 deterministic planner 辨識",
                query_terms=(),
                satisfied_article_ids=(),
            )
        )

    strategy = (
        "explicit_articles_and_query_facets"
        if requirements
        else "no_additional_requirements"
    )
    return EvidencePlan(strategy=strategy, requirements=tuple(requirements))
