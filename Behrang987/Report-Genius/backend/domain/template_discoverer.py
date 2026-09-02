"""Discover a :class:`TemplateSchema` from the operator report template (PDF).

The **report template** (PDF) is the structural authority: section order, titles,
and ratings. **Standard paragraphs** (Word) supply approved wording and are
ingested separately into the MASTER RAG tier via
:func:`discover_standard_paragraph_chunks`.

Structural discovery is deterministic (heading detection over extracted blocks).
When an OpenAI key is configured, an enrichment pass adds routing keywords and
confirms any rating system.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from backend.config import settings
from backend.domain.rics_level3_schema import (
    PARENT_SECTION_COUNT,
    build_canonical_template_schema,
    is_canonical_schema,
)
from backend.ingest import doc_extractor
from backend.llm import openai_client
from backend.models.schema import (
    RatingSystem,
    RatingValue,
    SectionDefinition,
    TemplateSchema,
)
from backend.prompts.discovery_prompt import build_enrichment_messages
from backend.storage import tenant_store

logger = logging.getLogger(__name__)

# Report-template headings: "A About the inspection", "D1 Chimney stacks", "Section E1 - ..."
_REPORT_SECTION_RE = re.compile(
    r"^(?:section\s+)?([A-Z]\d{0,2})\s+(.+)$",
    re.IGNORECASE,
)
# Single-letter section group codes (A–Z).
_SINGLE_LETTER_CODES = frozenset(chr(c) for c in range(ord("A"), ord("Z") + 1))
_SEPARATORS = ".:-–—\u2013\u2014)"
_VARIANT_TAG_RE = re.compile(r"\[[A-Z]\]")
_LIST_NUM_PREFIX_RE = re.compile(r"^\s*\d{1,4}\s*[.)]\s*")
_SPARE_RE = re.compile(
    r"^\s*(?:\d{1,4}\s*[.)]\s*)?(?:\[[A-Z]\]\s*)?spare\.?\s*$", re.IGNORECASE
)
_RATING_HINT_RE = re.compile(
    r"\bcondition\s+rating\b|\brating\s*[:#]?\s*[123]\b", re.IGNORECASE
)


@dataclass
class DiscoveredChunk:
    section_id: str
    text: str
    section_name: str = ""
    paragraph_index: int = 0
    parent_id: str = ""


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:40] or "section"


def _heading_id_title(text: str) -> tuple[str, str]:
    """Return (id, title) for a heading line."""
    s = text.strip()
    body = re.sub(r"^section\s+", "", s, count=1, flags=re.IGNORECASE)
    m = _REPORT_SECTION_RE.match(body) or _REPORT_SECTION_RE.match(s)
    if m:
        code = m.group(1).upper()
        title = m.group(2).strip().lstrip(_SEPARATORS + " ").strip()
        return code, title or code
    return _slug(body), body


def _looks_like_report_heading(text: str, styled_heading: bool) -> bool:
    """Strict heading detector for report templates (PDF/DOCX structure files)."""
    if styled_heading:
        return True
    s = text.strip()
    if not s or len(s) > 80:
        return False
    m = _REPORT_SECTION_RE.match(s)
    if not m:
        return False
    title = (m.group(2) or "").strip()
    # Reject body sentences ("AS agreed…", "OF this matter…").
    if not title or not title[0].isupper():
        return False
    code = m.group(1).upper()
    if len(code) == 1 and code not in _SINGLE_LETTER_CODES:
        return False
    if len(code) == 2 and not code[1].isdigit():
        return False
    return True


def _looks_like_paragraph_heading(text: str, styled_heading: bool) -> bool:
    """Heading detector for the standard-paragraphs Word master (E1, K3, …)."""
    if styled_heading:
        return True
    s = text.strip()
    m = re.match(r"^(?:section\s+)?([A-Z]{1,2}\d{0,2})\b", s, re.IGNORECASE)
    if not m:
        return False
    code = m.group(1)
    rest = s[m.end() :]
    had_prefix = s.lower().startswith("section ")
    has_digit = any(ch.isdigit() for ch in code)
    if not had_prefix and not has_digit:
        return False
    if not rest:
        return had_prefix or has_digit
    sep = rest[0]
    return sep in _SEPARATORS or sep.isspace()


def _clean_body_line(line: str) -> str:
    s = (line or "").replace("\t", " ").strip()
    if not s or _SPARE_RE.match(s):
        return ""
    s = _LIST_NUM_PREFIX_RE.sub("", s)
    s = _VARIANT_TAG_RE.sub("", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return "" if s.lower() == "spare" else s


def _discover_report_structure(path: Path) -> list[SectionDefinition]:
    """Discover section headings from the report template (structure only)."""
    blocks = doc_extractor.extract_blocks(path)
    sections: list[SectionDefinition] = []
    order = 0
    seen_ids: set[str] = set()

    for blk in blocks:
        if not _looks_like_report_heading(blk.text, blk.is_heading):
            continue
        sid, title = _heading_id_title(blk.text)
        if sid in seen_ids:
            continue
        seen_ids.add(sid)
        sections.append(
            SectionDefinition(
                id=sid,
                title=title,
                order=order,
                level=max(1, blk.level or 1),
            )
        )
        order += 1
    return sections


def _collect_raw_section_texts(path: Path) -> dict[str, str]:
    """Map section_id -> body text beneath each report-template heading."""
    blocks = doc_extractor.extract_blocks(path)
    texts: dict[str, str] = {}
    current_id: str | None = None
    buf: list[str] = []

    def flush() -> None:
        nonlocal buf
        if current_id and buf:
            body = "\n".join(b for b in (_clean_body_line(x) for x in buf) if b).strip()
            if body:
                texts[current_id] = body
        buf = []

    for blk in blocks:
        if _looks_like_report_heading(blk.text, blk.is_heading):
            flush()
            current_id, _ = _heading_id_title(blk.text)
        elif current_id:
            buf.append(blk.text)
    flush()
    return texts


def _infer_section_hierarchy(sections: list[SectionDefinition]) -> str:
    max_level = max((s.level for s in sections), default=1)
    if max_level >= 3:
        return "three-level"
    if max_level >= 2:
        return "two-level"
    return "flat"


def _discover_paragraph_structure(path: Path) -> list[DiscoveredChunk]:
    """Extract per-subsection standard paragraphs from a Word/PDF master.

    Each body paragraph under a leaf heading becomes its own chunk so
    Top-K retrieval and per-chunk delete stay granular.

    For PDFs, ignore the extractor's loose ``is_heading`` heuristic and rely
    on section-code regex only — short title-cased lines must not become
    fake subsection ids.
    """
    blocks = doc_extractor.extract_blocks(path)
    trust_style_headings = path.suffix.lower() != ".pdf"
    chunks: list[DiscoveredChunk] = []
    current_id: str | None = None
    current_title: str = ""
    para_index = 0

    def parent_of(sid: str) -> str:
        s = (sid or "").strip().upper()
        return s[0] if s and s[0].isalpha() else ""

    for blk in blocks:
        styled = bool(blk.is_heading) if trust_style_headings else False
        if _looks_like_paragraph_heading(blk.text, styled):
            sid, title = _heading_id_title(blk.text)
            current_id = sid
            current_title = title or sid
            para_index = 0
            continue
        if not current_id:
            continue
        cleaned = _clean_body_line(blk.text)
        if not cleaned:
            continue
        chunks.append(
            DiscoveredChunk(
                section_id=current_id,
                text=cleaned,
                section_name=current_title,
                paragraph_index=para_index,
                parent_id=parent_of(current_id),
            )
        )
        para_index += 1
    return chunks


def discover_standard_paragraph_chunks(path: Path) -> list[DiscoveredChunk]:
    """Extract standard paragraph bodies from a Word or PDF master."""
    chunks = _discover_paragraph_structure(path)
    if not chunks:
        raise ValueError(f"No standard paragraphs discovered in {path}")
    return chunks


def discover_standard_paragraph_titles(path: Path) -> dict[str, str]:
    """Return ``{section_id: title}`` headings from the SP Word/PDF master."""
    blocks = doc_extractor.extract_blocks(path)
    trust_style_headings = path.suffix.lower() != ".pdf"
    titles: dict[str, str] = {}
    for blk in blocks:
        styled = bool(blk.is_heading) if trust_style_headings else False
        if not _looks_like_paragraph_heading(blk.text, styled):
            continue
        sid, title = _heading_id_title(blk.text)
        if sid not in titles:
            titles[sid] = title
    return titles


def _enrich_with_llm(
    schema: TemplateSchema,
    sample_text: str,
    *,
    filename: str = "report_template",
) -> TemplateSchema:
    if not openai_client.is_available():
        return schema
    rows = [{"id": s.id, "title": s.title} for s in schema.ordered_sections()]
    heading_outline = "\n".join(f"{s.id} {s.title}" for s in schema.ordered_sections())
    body_sample = sample_text[:8000] if len(sample_text) > 8000 else sample_text
    truncated_sample = f"{heading_outline}\n\n{body_sample}"
    try:
        data = openai_client.chat_json(
            build_enrichment_messages(rows, truncated_sample, filename=filename),
            model=settings.discovery_model,
            max_tokens=settings.max_tokens_discovery,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Discovery enrichment failed (%s); using structural schema only.", exc
        )
        return schema

    if data.get("report_type"):
        schema.report_type = str(data["report_type"])
    if data.get("section_hierarchy"):
        schema.section_hierarchy = str(data["section_hierarchy"])

    rating = data.get("rating_system") or {}
    if rating.get("detected"):
        values = [
            RatingValue(
                value=str(v.get("value", "")),
                label=str(v.get("meaning") or v.get("label", "")),
            )
            for v in rating.get("values", [])
            if str(v.get("value", "")).strip()
        ]
        schema.rating_system = RatingSystem(
            detected=True,
            name=str(rating.get("name", schema.rating_system.name)),
            type=rating.get("type"),
            values=values,
            format_template=rating.get("format_template"),
            inline_example=rating.get("inline_example"),
        )

    ph = data.get("placeholder_syntax") or {}
    if ph.get("detected_formats"):
        schema.placeholders.detected_formats = [
            str(x) for x in ph.get("detected_formats", []) if str(x).strip()
        ]
    if ph.get("primary_format"):
        schema.placeholders.primary_format = str(ph.get("primary_format"))

    for row in data.get("sections", []):
        sid = str(row.get("id", ""))
        sec = schema.get_section(sid)
        if sec is None:
            continue
        kws = row.get("keywords") or []
        if kws:
            sec.keywords = [str(k).lower() for k in kws if str(k).strip()]
        if row.get("has_rating_field") is not None:
            sec.has_rating_field = bool(row.get("has_rating_field"))
        if row.get("rating_inline_format"):
            sec.rating_inline_format = str(row["rating_inline_format"])
        hints = row.get("placeholder_hints") or []
        if hints:
            sec.placeholder_hints = [str(h) for h in hints if str(h).strip()]

    extra = data.get("additional_metadata")
    if isinstance(extra, dict):
        schema.additional_metadata = extra
    return schema


def _default_keywords(section: SectionDefinition) -> list[str]:
    """Fallback keywords from the title when no LLM enrichment is available."""
    words = re.findall(r"[A-Za-z]{4,}", section.title.lower())
    stop = {"and", "the", "with", "from", "this", "that", "level", "section"}
    return [w for w in dict.fromkeys(words) if w not in stop][:8]


def discover_report_template_schema(path: Path) -> TemplateSchema:
    """Return the canonical RICS Level 3 schema (PDF/DOCX structure is not parsed)."""
    _ = path  # retained for API compatibility; canonical guard bypasses fluid heuristics
    return build_canonical_template_schema(
        source_filename=path.name if path else "RICS_L3_CANONICAL"
    )


def discover_schema(path: Path) -> tuple[TemplateSchema, list[DiscoveredChunk]]:
    """Canonical L3 schema + standard-paragraph chunks from a Word/PDF master (tests)."""
    schema = build_canonical_template_schema(source_filename=path.name)
    chunks = _discover_paragraph_structure(path)
    if not chunks:
        raise ValueError(f"No standard paragraphs discovered in {path}")
    return schema, chunks


# ── persistence ──────────────────────────────────────────────────────────────
def safe_filename_id(section_id: str) -> str:
    """Forces names to clean safe codes like 'F2.json', 'M.json', 'section_D.txt'."""
    return "".join(c for c in section_id if c.isalnum() or c in ("_", "-")).strip()


def _atomic_write_text(path: Path, content: str) -> None:
    """Write UTF-8 text atomically (Windows-safe replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.stem}.write{path.suffix}")
    tmp.write_text(content, encoding="utf-8")
    if path.is_file():
        path.unlink()
    tmp.replace(path)


def save_schema(tenant_id: str, schema: TemplateSchema) -> None:
    """Persist schema.json, rotating any existing schema to schema_prev.json.

    On-disk layout uses ``tenant_id`` only — section titles/labels belong
    inside the JSON document, never as path segments.
    """
    safe_tenant = tenant_store.normalize_tenant_id(tenant_id)
    schema.tenant_id = safe_tenant
    path = tenant_store.schema_path(safe_tenant)
    if path.is_file():
        prev = tenant_store.schema_prev_path(safe_tenant)
        _atomic_write_text(prev, path.read_text(encoding="utf-8"))
    _atomic_write_text(path, schema.model_dump_json(indent=2))
    logger.info(
        "Saved schema for tenant=%s (%d sections, v%d)",
        safe_tenant,
        len(schema.sections),
        schema.version,
    )


def install_canonical_schema(
    tenant_id: str, *, source_filename: str = "RICS_L3_CANONICAL"
) -> TemplateSchema:
    """Wipe and persist the canonical RICS L3 schema for a tenant."""
    safe_tenant = tenant_store.normalize_tenant_id(tenant_id)
    schema = build_canonical_template_schema(
        source_filename=source_filename, tenant_id=safe_tenant
    )
    save_schema(safe_tenant, schema)
    _schema_repair_marker(safe_tenant).write_text("1", encoding="utf-8")
    logger.info(
        "Installed canonical RICS L3 schema for tenant=%s (%d parents, %d leaf sections)",
        safe_tenant,
        PARENT_SECTION_COUNT,
        len(schema.sections),
    )
    return schema


def _schema_repair_marker(tenant_id: str) -> Path:
    return tenant_store.tenant_root(tenant_id) / ".schema_repaired"


def _schema_has_unsafe_labels(schema: TemplateSchema) -> bool:
    """True when persisted labels still contain path-breaking characters."""
    for sec in schema.sections:
        title = sec.title or ""
        if "/" in title or "\\" in title:
            return True
    meta = schema.additional_metadata or {}
    for row in meta.get("parent_sections") or []:
        label = str(row.get("label") or "")
        if "/" in label or "\\" in label:
            return True
    return False


def ensure_canonical_schema(tenant_id: str) -> TemplateSchema:
    """Load schema or replace corrupt/non-canonical persisted schemas."""
    safe_tenant = tenant_store.normalize_tenant_id(tenant_id)
    schema = load_schema(safe_tenant, repair=False)
    if (
        schema is not None
        and is_canonical_schema(schema)
        and not _schema_has_unsafe_labels(schema)
    ):
        return schema
    if schema is not None:
        logger.warning(
            "Replacing schema for tenant=%s (%d sections) — non-canonical or unsafe labels.",
            safe_tenant,
            len(schema.sections),
        )
    return install_canonical_schema(safe_tenant)


def load_schema(tenant_id: str, *, repair: bool = True) -> TemplateSchema | None:
    """Load tenant schema; when ``repair=True``, auto-seed canonical L3 if missing."""
    safe_tenant = tenant_store.normalize_tenant_id(tenant_id)
    path = tenant_store.schema_path(safe_tenant)
    if not path.is_file():
        if repair:
            logger.info(
                "No schema.json for tenant=%s — installing canonical RICS L3 (%d parents).",
                safe_tenant,
                PARENT_SECTION_COUNT,
            )
            return install_canonical_schema(safe_tenant)
        return None
    try:
        schema = TemplateSchema.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load schema for tenant=%s (%s).", safe_tenant, exc)
        return install_canonical_schema(safe_tenant) if repair else None
    if repair and (
        not is_canonical_schema(schema) or _schema_has_unsafe_labels(schema)
    ):
        return install_canonical_schema(safe_tenant)
    return schema
