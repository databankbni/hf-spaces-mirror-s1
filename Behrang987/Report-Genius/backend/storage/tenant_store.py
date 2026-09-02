"""Per-tenant on-disk layout for schema + FAISS artifacts.

Layout (under ``settings.data_dir``)::

    {data_dir}/tenants/{tenant_id}/
        schema.json          # discovered template schema
        schema_prev.json     # rotated previous schema (admin override)
        faiss/standard_paragraphs/  # standard paragraph memory index
        faiss/reference/     # REFERENCE tier index
        costs/               # per-tenant cost ledger (events-YYYYMM.jsonl + summary.json)
        standard_paragraph_uploads/  # Word uploads (local v1)
        standard_paragraph_jobs/     # async ingest job JSON
        standard_paragraph_extracts/ # Word extraction debug JSON (pre-FAISS)

Path segments must use stable IDs (tenant_id, section_id, draft_id, document_id).
Human section *labels* (e.g. ``Gas/Oil``, ``service and terms of engagement``) belong
only inside JSON payloads — never as directory or file names.
"""

from __future__ import annotations

import re
from pathlib import Path

from backend.config import settings

_SECTION_ID_RE = re.compile(r"^[A-Z]\d{0,2}$", re.IGNORECASE)
# Content-mode review codes (e.g. chimney_stacks, bathroom_kitchen_fittings).
_CONTENT_SECTION_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,80}$")
_FORBIDDEN_PATH_CHARS_RE = re.compile(r'[/\\:*?"<>|]')


def path_safe_label(label: str) -> str:
    """Sanitize a human label when it must appear in a path segment (prefer IDs instead)."""
    s = (label or "").replace("/", "_").replace("\\", "_").replace(":", "")
    s = _FORBIDDEN_PATH_CHARS_RE.sub("_", s)
    s = re.sub(r"\s+", "_", s.strip())
    return s[:120] or "unknown"


def path_safe_section_id(section_id: str) -> str:
    """Return a filesystem-safe section code (RICS ``F2`` / content ``chimney_stacks``).

    Rejects descriptive labels such as ``Gas/Oil`` that would create invalid paths on
    Windows when used as directory names.
    """
    sid = (section_id or "").strip()
    if not sid:
        raise ValueError("Empty section_id")
    if "/" in sid or "\\" in sid:
        raise ValueError(
            f"section_id {section_id!r} looks like a label, not an ID — use e.g. F2, M, D1"
        )
    normalized = sid.upper().replace(" ", "")
    if normalized == "UNASSIGNED":
        return normalized
    # RICS leaf/parent codes first so ``f2`` stays ``F2``, not a content slug.
    if _SECTION_ID_RE.fullmatch(normalized):
        return normalized
    # Content-mode review taxonomy ids (snake_case).
    if _CONTENT_SECTION_ID_RE.fullmatch(sid.lower()):
        return sid.lower()
    raise ValueError(f"Invalid section_id for filesystem path: {section_id!r}")


def path_safe_segment(segment: str, *, fallback: str = "unknown") -> str:
    """Sanitize a generic tenant/draft/document path component."""
    s = (segment or "").strip()
    if not s:
        return fallback
    if "/" in s or "\\" in s:
        s = path_safe_label(s)
    else:
        s = _FORBIDDEN_PATH_CHARS_RE.sub("_", s)
        s = re.sub(r"\s+", "_", s)
    return s[:120] or fallback


def normalize_tenant_id(tenant_id: str) -> str:
    """Stable tenant directory key under ``tenants/{id}/``."""
    return path_safe_segment(tenant_id, fallback="default")


def ensure_tenant_schema(tenant_id: str):
    """Ensure ``schema.json`` exists with the canonical 14-parent RICS L3 matrix."""
    from backend.domain import template_discoverer

    return template_discoverer.ensure_canonical_schema(normalize_tenant_id(tenant_id))


def tenant_root(tenant_id: str) -> Path:
    safe_id = normalize_tenant_id(tenant_id)
    root = settings.data_dir_path / "tenants" / safe_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def schema_path(tenant_id: str) -> Path:
    return tenant_root(tenant_id) / "schema.json"


def schema_prev_path(tenant_id: str) -> Path:
    return tenant_root(tenant_id) / "schema_prev.json"


def faiss_dir(tenant_id: str, tier: str) -> Path:
    safe_tier = path_safe_segment(tier, fallback="unknown")
    # One-time rename: legacy faiss/master → faiss/standard_paragraphs
    if safe_tier == "standard_paragraphs":
        migrate_legacy_master_faiss_dir(tenant_id)
    d = tenant_root(tenant_id) / "faiss" / safe_tier
    d.mkdir(parents=True, exist_ok=True)
    return d


def migrate_legacy_master_faiss_dir(tenant_id: str) -> bool:
    """Rename ``faiss/master`` → ``faiss/standard_paragraphs`` when needed.

    Returns True if a migration rename was performed.
    """
    root = tenant_root(tenant_id) / "faiss"
    old = root / "master"
    new = root / "standard_paragraphs"
    if new.exists():
        return False
    if not old.is_dir():
        return False
    try:
        has_content = any(old.iterdir())
    except OSError:
        has_content = False
    if not has_content:
        return False
    root.mkdir(parents=True, exist_ok=True)
    old.rename(new)
    return True


def standard_paragraph_uploads_dir(tenant_id: str) -> Path:
    d = tenant_root(tenant_id) / "standard_paragraph_uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def standard_paragraph_jobs_dir(tenant_id: str) -> Path:
    d = tenant_root(tenant_id) / "standard_paragraph_jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def standard_paragraph_upload_path(tenant_id: str, document_id: str, suffix: str) -> Path:
    safe_doc = path_safe_segment(document_id, fallback="document")
    safe_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    return standard_paragraph_uploads_dir(tenant_id) / f"{safe_doc}{safe_suffix}"


def standard_paragraph_extracts_dir(tenant_id: str) -> Path:
    """Debug JSON dumps of Word→subsection extraction (pre-FAISS)."""
    d = tenant_root(tenant_id) / "standard_paragraph_extracts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def standard_paragraph_extract_json_path(tenant_id: str, document_id: str) -> Path:
    """Per-upload extraction JSON: ``{document_id}.extracted.json``."""
    safe_doc = path_safe_segment(document_id, fallback="document")
    return standard_paragraph_extracts_dir(tenant_id) / f"{safe_doc}.extracted.json"


def scrub_audit_path(tenant_id: str) -> Path:
    """Append-only JSONL log of reference-tier PII scrubbing at ingest."""
    return tenant_root(tenant_id) / "scrub_audit.jsonl"


def photo_draft_root(tenant_id: str, draft_id: str) -> Path:
    """Root folder for a report draft's section photos."""
    safe_draft = path_safe_segment(draft_id, fallback="draft")
    d = tenant_root(tenant_id) / "photo_drafts" / safe_draft
    d.mkdir(parents=True, exist_ok=True)
    return d


def photo_section_dir(tenant_id: str, draft_id: str, section_id: str) -> Path:
    safe_section = path_safe_section_id(section_id)
    d = photo_draft_root(tenant_id, draft_id) / safe_section
    d.mkdir(parents=True, exist_ok=True)
    return d


def reference_uploads_dir(tenant_id: str) -> Path:
    """Persisted copies of tenant reference uploads (for re-ingest / delete)."""
    d = tenant_root(tenant_id) / "reference_uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def reference_extracts_dir(tenant_id: str) -> Path:
    """Markdown extracts written at ingest so operators can inspect read order."""
    d = tenant_root(tenant_id) / "reference_extracts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def reference_extract_md_path(tenant_id: str, source_filename: str) -> Path:
    """``.extracted.md`` named from the original upload filename (not the UUID)."""
    label = (source_filename or "").strip() or "document"
    safe = path_safe_segment(label, fallback="document")
    return reference_extracts_dir(tenant_id) / f"{safe}.extracted.md"


def reference_upload_path(tenant_id: str, document_id: str, suffix: str) -> Path:
    """Path for a stored reference upload — ``document_id`` only, never the filename label."""
    safe_doc = path_safe_segment(document_id, fallback="document")
    safe_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    return reference_uploads_dir(tenant_id) / f"{safe_doc}{safe_suffix}"


def cost_dir(tenant_id: str) -> Path:
    """Per-tenant cost ledger folder: ``tenants/<id>/costs/``."""
    d = tenant_root(tenant_id) / "costs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cost_events_path(tenant_id: str, *, month: str | None = None) -> Path:
    """Append-only monthly events file: ``costs/events-YYYYMM.jsonl``."""
    from datetime import UTC, datetime

    key = (month or "").strip()
    if not key:
        key = datetime.now(UTC).strftime("%Y-%m")
    # Accept YYYY-MM or YYYYMM
    safe = key.replace("-", "")[:6]
    if len(safe) != 6 or not safe.isdigit():
        safe = datetime.now(UTC).strftime("%Y%m")
    return cost_dir(tenant_id) / f"events-{safe}.jsonl"


def cost_summary_path(tenant_id: str) -> Path:
    """Rolling totals JSON: ``costs/summary.json``."""
    return cost_dir(tenant_id) / "summary.json"
