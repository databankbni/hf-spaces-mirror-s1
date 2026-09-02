"""Dual-path merge agent (past-report + standard-paragraph drafts → one section)."""

from __future__ import annotations

from backend.merge_agent.models import DualPathDraft, MergeResult
from backend.merge_agent.orchestrator import merge_dual_path_drafts
from backend.merge_agent.prompts import (
    MERGE_SYSTEM_PROMPT,
    MERGE_SYSTEM_PROMPT_V1,
    MERGE_SYSTEM_PROMPT_V2,
    build_merge_messages,
)
from backend.merge_agent.sources import (
    format_sources_text,
    source_names_from_chunks,
    source_names_from_manifest_section,
    write_sources_file,
)

__all__ = [
    "DualPathDraft",
    "MergeResult",
    "MERGE_SYSTEM_PROMPT",
    "MERGE_SYSTEM_PROMPT_V1",
    "MERGE_SYSTEM_PROMPT_V2",
    "build_merge_messages",
    "format_sources_text",
    "merge_dual_path_drafts",
    "source_names_from_chunks",
    "source_names_from_manifest_section",
    "write_sources_file",
]
