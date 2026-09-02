"""Lightweight retrieval contract shared across the RAG, prompt and domain layers.

This module holds only the dependency-free value types (dataclasses + tier
constants) that describe retrieval inputs/outputs. It intentionally imports
nothing heavy (no faiss/numpy/torch/embedder), so ``prompts.*`` and ``domain.*``
modules can depend on the retrieval *contract* without pulling in the vector
store. ``rag_store`` re-exports these names for backward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Firm-approved / user-managed standard paragraph memory (separate from past reports).
TIER_STANDARD_PARAGRAPHS = "standard_paragraphs"
# Deprecated alias — prefer TIER_STANDARD_PARAGRAPHS.
TIER_MASTER = TIER_STANDARD_PARAGRAPHS

TIER_REFERENCE = "reference"

# Generation knowledge source (one prompt path per section, or both+merge).
KNOWLEDGE_SOURCE_PAST_REPORT = "past_report"
KNOWLEDGE_SOURCE_STANDARD_PARAGRAPH = "standard_paragraph"
KNOWLEDGE_SOURCE_BOTH = "both"

CONTENT_ROLE_BODY = "body"
CONTENT_ROLE_PARENT_INTRO = "parent_intro"


@dataclass
class Chunk:
    text: str
    section_id: str = ""
    doc_id: str = ""
    tier: str = TIER_STANDARD_PARAGRAPHS
    is_scrubbed: bool = False
    chunk_id: str = ""
    source_filename: str = ""
    paragraph_index: int = 0
    document_type: str = ""
    # Canonical RAG bucket: "house" | "flat" | "" (untagged — excluded from typed retrieval).
    property_type: str = ""
    content_role: str = CONTENT_ROLE_BODY
    parent_id: str = ""
    section_name: str = ""
    ingestion_source: str = ""
    content_hash: str = ""
    created_at: str = ""
    blob_key: str = ""
    # Content-based topic mode tags (parallel to section_id; empty when untagged).
    topic_id: str = ""
    subtopic_id: str = ""
    # Cross-cutting themes (damp, movement, ...), orthogonal to topic_id: a chunk
    # has one topic but any number of themes. See content_based.taxonomy.
    theme_tags: list[str] = field(default_factory=list)
    # Taxonomy version the topic/theme tags were assigned under. Lets a stale
    # tagging be detected instead of silently returning nothing at retrieval.
    taxonomy_version: str = ""


@dataclass
class SearchHit:
    text: str
    section_id: str
    doc_id: str
    tier: str
    score: float
    is_scrubbed: bool
    source_filename: str = ""
    paragraph_index: int = 0
    chunk_id: str = ""
    rerank_score: float = 0.0
    # Hybrid retrieval components (populated by store search when available).
    # ``score`` remains the ranking key used by callers (cosine+boosts, or the
    # stamped primary after past-report section expansion). Component fields:
    similarity_score: float = 0.0  # dense cosine (pre-boost)
    bm25_score: float = 0.0  # raw BM25 lexical score
    fusion_score: float = 0.0  # Reciprocal Rank Fusion of dense+BM25 ranks
    document_type: str = ""
    property_type: str = ""
    content_role: str = CONTENT_ROLE_BODY
    parent_id: str = ""
    section_name: str = ""
    ingestion_source: str = ""
    content_hash: str = ""
    # Content-based topic mode tags (parallel to section_id; empty when untagged).
    topic_id: str = ""
    subtopic_id: str = ""
    theme_tags: list[str] = field(default_factory=list)
    taxonomy_version: str = ""
