from typing import List, Optional

from pydantic import BaseModel


class SearchRequest(BaseModel):
    question: str
    paper_titles: Optional[List[str]] = None
    search_mode: str = "hybrid"


class Citation(BaseModel):
    paper_title: str
    page_number: int
    chunk_id: str
    citation: str


class EvidenceChunk(BaseModel):
    paper_title: str
    page_number: int
    chunk_id: str
    text: str
    search_score: float = 0.0
    keyword_score: Optional[float] = None
    hybrid_score: Optional[float] = None
    rrf_score: Optional[float] = None
    rerank_score: Optional[float] = None


class SearchResponse(BaseModel):
    question: str
    answer: str
    confidence: str
    evidence_strength: str
    citations: List[Citation]
    evidence: List[EvidenceChunk]