"""Shared data models for hybrid RAG."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    ABSTAIN = "abstain"


def confidence_level_from_score(score: float, abstain_threshold: float = 0.18) -> ConfidenceLevel:
    if score < abstain_threshold:
        return ConfidenceLevel.ABSTAIN
    if score >= 0.42:
        return ConfidenceLevel.HIGH
    if score >= 0.28:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    doc_title: str
    text: str
    section: str
    page: int = 1
    paragraph: int = 1
    parent_id: str = ""
    layer: str = "text"
    modality: str = "text"
    language: str = "en"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "doc_title": self.doc_title,
            "text": self.text,
            "section": self.section,
            "page": self.page,
            "paragraph": self.paragraph,
            "parent_id": self.parent_id or self.doc_id,
            "layer": self.layer,
            "modality": self.modality,
            "language": self.language,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Chunk":
        return cls(
            chunk_id=data["chunk_id"],
            doc_id=data["doc_id"],
            doc_title=data["doc_title"],
            text=data["text"],
            section=data.get("section", ""),
            page=int(data.get("page", 1)),
            paragraph=int(data.get("paragraph", 1)),
            parent_id=data.get("parent_id", data.get("doc_id", "")),
            layer=data.get("layer", "text"),
            modality=data.get("modality", "text"),
            language=data.get("language", "en"),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class RetrievalHit:
    chunk: Chunk
    score: float
    rank: int
    components: dict[str, float] = field(default_factory=dict)


@dataclass
class Citation:
    index: int
    chunk_id: str
    doc_id: str
    doc_title: str
    section: str
    page: int
    paragraph: int
    excerpt: str
    relevance_score: float
    layer: str = "text"
    modality: str = "text"


@dataclass
class QueryResult:
    question: str
    answer: str
    citations: list[Citation]
    confidence: float
    confidence_level: ConfidenceLevel
    language: str
    retrieval_hits: list[RetrievalHit]
    abstained: bool = False
    route: str = "document"
    extras: dict[str, Any] = field(default_factory=dict)
    rewritten_query: str = ""
