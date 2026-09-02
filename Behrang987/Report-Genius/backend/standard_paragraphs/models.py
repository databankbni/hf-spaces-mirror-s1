"""DTOs for standard paragraph memory."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

IngestionSource = Literal["upload", "runtime", "operator"]
KnowledgeSource = Literal["past_report", "standard_paragraph"]


class AddToMemoryRequest(BaseModel):
    subsection_id: str = Field(..., min_length=1, description="Leaf code e.g. D1")
    text: str = Field(..., min_length=1)
    section_id: str | None = Field(
        default=None,
        description="Optional parent letter (e.g. D). Derived from subsection_id when omitted.",
    )
    section_name: str | None = None
    subsection_name: str | None = None


class AddToMemoryResponse(BaseModel):
    ok: bool = True
    data: dict
    error: dict | None = None


class ParagraphItem(BaseModel):
    chunk_id: str
    subsection_id: str
    section_id: str = ""
    section_name: str = ""
    text: str
    ingestion_source: str = ""
    created_at: str = ""
    content_hash: str = ""
    doc_id: str = ""
    source_filename: str = ""
    paragraph_index: int = 0
