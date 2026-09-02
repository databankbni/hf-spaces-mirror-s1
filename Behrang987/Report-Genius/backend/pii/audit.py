"""Document-level PII scrub audit — PII mapping JSON + optional verbose dump.

Every REFERENCE-tier document scrubbed at ingest **always** writes
``pii_mapping.json`` under ``<data_dir>/pii_scrub_audit/<tenant>/<document>/``.
That file is the canonical JSON map of original sensitive values → stable redaction
placeholders, with section/paragraph/chunk location and redacted content per chunk.

When ``settings.pii_scrub_audit_dump`` is enabled (env ``PII_SCRUB_AUDIT_DUMP``),
the same directory also receives:

* ``redacted_content.txt`` — the WHOLE document after redaction, section by section.
* ``redactions.json`` — verbose manifest (redactions, whitelisted spans, dropped chunks).

Generated-output emergency scrubs write
``<data_dir>/pii_scrub_audit/<tenant>/generated/<context_id>/pii_mapping.json``.

A static ``whitelist_catalog.json`` at the audit root lists every survey term the
scrubber treats as safe.

Best-effort only: failures here must never block ingest or export.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.config import settings

logger = logging.getLogger(__name__)

_write_lock = threading.Lock()
_catalog_written = False

_UNSAFE_SEGMENT_RE = re.compile(r"[^A-Za-z0-9._-]+")


def enabled() -> bool:
    """True when verbose audit artifacts (redacted_content.txt) are requested."""
    return bool(getattr(settings, "pii_scrub_audit_dump", False))


def mapping_enabled() -> bool:
    """PII mapping JSON is always emitted for scrubbed content."""
    return True


_PII_SEVERITY: dict[str, str] = {
    "ADDRESS": "critical",
    "POSTCODE": "critical",
    "EMAIL": "high",
    "PHONE": "high",
    "PERSON": "high",
    "URL": "high",
    "REFERENCE": "high",
    "NINO": "critical",
    "MONEY": "medium",
    "DATE": "low",
}

_RECOMMENDED_ACTIONS: dict[str, str] = {
    "reference_ingest": "redact_before_reference_storage",
    "generated_output": "redact_before_export",
}


def audit_root() -> Path:
    d = settings.data_dir_path / "pii_scrub_audit"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_segment(name: str, *, fallback: str) -> str:
    cleaned = _UNSAFE_SEGMENT_RE.sub("_", (name or "").strip()).strip("_")
    return cleaned[:120] or fallback


def _clip(text: str, cap: int) -> str:
    raw = (text or "").strip()
    if cap and len(raw) > cap:
        return f"{raw[:cap]}…[+{len(raw) - cap} more chars]"
    return raw


def _severity(pii_type: str) -> str:
    return _PII_SEVERITY.get((pii_type or "").upper(), "medium")


def _mapping_entry(
    *,
    index: int,
    file_name: str,
    paragraph_index: int,
    field_or_identifier: str,
    pii_type: str,
    original_surface: str,
    surface_cap: int,
    recommended_action: str,
    location: dict[str, Any],
    source: str = "",
    pass_no: int | None = None,
) -> dict[str, Any]:
    placeholder = field_or_identifier or ""
    return {
        "index": index,
        "file": file_name,
        "line": int(paragraph_index or 0) or None,
        "field_or_identifier": placeholder,
        "pii_type": pii_type,
        "severity": _severity(pii_type),
        "example_redacted_value": placeholder,
        "original_surface": _clip(original_surface, surface_cap),
        "recommended_action": recommended_action,
        "location": location,
        "source": source,
        "pass": pass_no,
    }


def _build_pii_mapping(
    *,
    document: str,
    original_filename: str,
    doc_id: str,
    tenant_id: str,
    context: str,
    chunks: list[_ChunkRecord],
    surface_cap: int,
) -> dict[str, Any]:
    mappings: list[dict[str, Any]] = []
    content_blocks: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    idx = 0
    action = _RECOMMENDED_ACTIONS.get(context, "redact")
    file_name = document or doc_id or "document"
    dropped = 0
    for rec in chunks:
        if rec.dropped:
            dropped += 1
        content_blocks.append(
            {
                "section_id": rec.section_id,
                "paragraph_index": rec.paragraph_index,
                "chunk_id": rec.chunk_id,
                "dropped": rec.dropped,
                "residual_leaks": rec.residual_leaks,
                "redacted_text": rec.redacted_text,
            }
        )
        for r in rec.redactions:
            idx += 1
            rtype = str(r.get("type", ""))
            counts[rtype] = counts.get(rtype, 0) + 1
            placeholder = str(r.get("placeholder", ""))
            mappings.append(
                _mapping_entry(
                    index=idx,
                    file_name=file_name,
                    paragraph_index=rec.paragraph_index,
                    field_or_identifier=placeholder,
                    pii_type=rtype,
                    original_surface=str(r.get("surface", "")),
                    surface_cap=surface_cap,
                    recommended_action=action,
                    location={
                        "section_id": rec.section_id,
                        "paragraph_index": rec.paragraph_index,
                        "chunk_id": rec.chunk_id,
                        "char_start": r.get("char_start"),
                        "char_end": r.get("char_end"),
                    },
                    source=str(r.get("source", "")),
                    pass_no=r.get("pass"),
                )
            )
    return {
        "schema_version": "1",
        "document": file_name,
        "original_filename": original_filename or "",
        "doc_id": doc_id,
        "tenant_id": tenant_id,
        "context": context,
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {
            "mappings_total": len(mappings),
            "pii_type_counts": dict(sorted(counts.items())),
            "chunks_total": len(chunks),
            "chunks_dropped": dropped,
        },
        "mappings": mappings,
        "content": {"redacted_chunks": content_blocks},
    }


def ensure_whitelist_catalog() -> None:
    """Write the static whitelist catalog once per process (idempotent on disk)."""
    global _catalog_written
    if _catalog_written:
        return
    path = audit_root() / "whitelist_catalog.json"
    if path.exists() and path.stat().st_size > 0:
        _catalog_written = True
        return
    try:
        from backend.pii.scrubber import export_whitelist_catalog

        payload = export_whitelist_catalog()
        payload["written_at"] = datetime.now(UTC).isoformat()
        with _write_lock, path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        _catalog_written = True
    except Exception:  # noqa: BLE001
        logger.debug("whitelist catalog write failed", exc_info=True)


@dataclass
class _ChunkRecord:
    section_id: str
    paragraph_index: int
    chunk_id: str
    redacted_text: str
    redactions: list[dict]
    whitelisted: list[dict]
    dropped: bool
    residual_leaks: dict[str, int]


@dataclass
class DocumentAudit:
    """Accumulates per-chunk scrub results for one document, then writes two files."""

    tenant_id: str
    doc_id: str
    source_filename: str
    original_filename: str = ""
    _chunks: list[_ChunkRecord] = field(default_factory=list)

    def add_chunk(
        self,
        *,
        section_id: str,
        paragraph_index: int,
        chunk_id: str,
        redacted_text: str,
        redactions: list[dict],
        whitelisted: list[dict],
        dropped: bool,
        residual_leaks: dict[str, int] | None = None,
    ) -> None:
        self._chunks.append(
            _ChunkRecord(
                section_id=section_id or "",
                paragraph_index=int(paragraph_index or 0),
                chunk_id=chunk_id or "",
                redacted_text=redacted_text or "",
                redactions=list(redactions or []),
                whitelisted=list(whitelisted or []),
                dropped=bool(dropped),
                residual_leaks=dict(residual_leaks or {}),
            )
        )

    def _document_dir(self) -> Path:
        tenant_seg = _safe_segment(self.tenant_id, fallback="tenant")
        doc_seg = _safe_segment(
            self.source_filename or self.doc_id, fallback="document"
        )
        d = audit_root() / tenant_seg / doc_seg
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _build_content(self) -> str:
        lines: list[str] = []
        lines.append("#" * 78)
        lines.append("# PII-REDACTED DOCUMENT CONTENT")
        lines.append(f"# document       : {self.source_filename or self.doc_id}")
        if self.original_filename and self.original_filename != self.source_filename:
            lines.append(f"# original_name  : {self.original_filename}")
        lines.append(f"# tenant         : {self.tenant_id}")
        lines.append(f"# generated_at   : {datetime.now(UTC).isoformat()}")
        lines.append(f"# chunks         : {len(self._chunks)}")
        lines.append(
            "# NOTE: text below is AFTER redaction. [REDACTED_*] = removed PII."
        )
        lines.append("#" * 78)
        lines.append("")
        for rec in self._chunks:
            header = (
                f"===== SECTION {rec.section_id or '-'} | "
                f"paragraph {rec.paragraph_index} | chunk={rec.chunk_id or '-'}"
            )
            if rec.dropped:
                leaks = ", ".join(
                    f"{k}={v}" for k, v in sorted(rec.residual_leaks.items())
                )
                header += f" | [CHUNK DROPPED — residual PII: {leaks or 'n/a'}]"
            header += " ====="
            lines.append(header)
            lines.append(rec.redacted_text or "(empty after redaction)")
            lines.append("")
        return "\n".join(lines)

    def _build_manifest(self, *, surface_cap: int) -> dict[str, Any]:
        redactions_out: list[dict[str, Any]] = []
        whitelisted_out: list[dict[str, Any]] = []
        dropped_out: list[dict[str, Any]] = []
        counts: dict[str, int] = {}
        idx = 0
        for rec in self._chunks:
            if rec.dropped:
                dropped_out.append(
                    {
                        "chunk_id": rec.chunk_id,
                        "section_id": rec.section_id,
                        "paragraph_index": rec.paragraph_index,
                        "residual_leaks": rec.residual_leaks,
                    }
                )
            for r in rec.redactions:
                idx += 1
                rtype = str(r.get("type", ""))
                counts[rtype] = counts.get(rtype, 0) + 1
                before = _clip(str(r.get("context_before", "")), surface_cap)
                after = _clip(str(r.get("context_after", "")), surface_cap)
                placeholder = str(r.get("placeholder", ""))
                redactions_out.append(
                    {
                        "index": idx,
                        "type": rtype,
                        "original": _clip(str(r.get("surface", "")), surface_cap),
                        "placeholder": placeholder,
                        "source": r.get("source", ""),
                        "pass": r.get("pass"),
                        "location": {
                            "section_id": rec.section_id,
                            "paragraph_index": rec.paragraph_index,
                            "chunk_id": rec.chunk_id,
                            "char_start": r.get("char_start"),
                            "char_end": r.get("char_end"),
                        },
                        "context_in_redacted_text": f"{before}{placeholder}{after}",
                    }
                )
            for w in rec.whitelisted:
                whitelisted_out.append(
                    {
                        "surface": _clip(str(w.get("surface", "")), surface_cap),
                        "reason": w.get("reason", ""),
                        "ner_label": w.get("ner_label", ""),
                        "location": {
                            "section_id": rec.section_id,
                            "paragraph_index": rec.paragraph_index,
                            "chunk_id": rec.chunk_id,
                        },
                    }
                )
        return {
            "document": self.source_filename or self.doc_id,
            "original_filename": self.original_filename or "",
            "doc_id": self.doc_id,
            "tenant_id": self.tenant_id,
            "generated_at": datetime.now(UTC).isoformat(),
            "summary": {
                "chunks_total": len(self._chunks),
                "chunks_dropped": len(dropped_out),
                "redactions_total": len(redactions_out),
                "redaction_counts": dict(sorted(counts.items())),
                "whitelisted_total": len(whitelisted_out),
            },
            "redactions": redactions_out,
            "whitelisted": whitelisted_out,
            "dropped_chunks": dropped_out,
        }

    def write(self) -> None:
        """Write pii_mapping.json always; verbose dump when audit dump is enabled."""
        if not self._chunks or not mapping_enabled():
            return
        try:
            surface_cap = int(
                getattr(settings, "pii_scrub_audit_max_surface_chars", 200) or 0
            )
            directory = self._document_dir()
            mapping = _build_pii_mapping(
                document=self.source_filename or self.doc_id,
                original_filename=self.original_filename,
                doc_id=self.doc_id,
                tenant_id=self.tenant_id,
                context="reference_ingest",
                chunks=self._chunks,
                surface_cap=surface_cap,
            )
            with _write_lock:
                with (directory / "pii_mapping.json").open("w", encoding="utf-8") as fh:
                    json.dump(mapping, fh, ensure_ascii=False, indent=2)
                    fh.write("\n")
                if enabled():
                    content = self._build_content()
                    manifest = self._build_manifest(surface_cap=surface_cap)
                    (directory / "redacted_content.txt").write_text(
                        content, encoding="utf-8"
                    )
                    with (directory / "redactions.json").open(
                        "w", encoding="utf-8"
                    ) as fh:
                        json.dump(manifest, fh, ensure_ascii=False, indent=2)
                        fh.write("\n")
        except Exception:  # noqa: BLE001 - auditing must never break ingest
            logger.debug("pii_scrub_audit document write failed", exc_info=True)


def start_document(
    *, tenant_id: str, doc_id: str, source_filename: str, original_filename: str = ""
) -> DocumentAudit | None:
    """Begin a document audit for REFERENCE-tier scrub mapping."""
    if not mapping_enabled():
        return None
    ensure_whitelist_catalog()
    return DocumentAudit(
        tenant_id=tenant_id or "",
        doc_id=doc_id or "",
        source_filename=source_filename or "",
        original_filename=original_filename or "",
    )


def write_output_mapping(
    *,
    tenant_id: str,
    context_id: str,
    chunks: list[dict[str, Any]],
) -> None:
    """Write pii_mapping.json for emergency output scrub (generated report)."""
    if not mapping_enabled() or not chunks:
        return
    try:
        surface_cap = int(
            getattr(settings, "pii_scrub_audit_max_surface_chars", 200) or 0
        )
        tenant_seg = _safe_segment(tenant_id, fallback="tenant")
        ctx_seg = _safe_segment(context_id, fallback="report")
        directory = audit_root() / tenant_seg / "generated" / ctx_seg
        directory.mkdir(parents=True, exist_ok=True)
        records = [
            _ChunkRecord(
                section_id=str(c.get("section_id", "")),
                paragraph_index=int(c.get("paragraph_index", 0) or 0),
                chunk_id=str(c.get("chunk_id", "")),
                redacted_text=str(c.get("redacted_text", "")),
                redactions=list(c.get("redactions") or []),
                whitelisted=list(c.get("whitelisted") or []),
                dropped=bool(c.get("dropped")),
                residual_leaks=dict(c.get("residual_leaks") or {}),
            )
            for c in chunks
        ]
        mapping = _build_pii_mapping(
            document=context_id,
            original_filename="",
            doc_id=f"generated:{context_id}",
            tenant_id=tenant_id,
            context="generated_output",
            chunks=records,
            surface_cap=surface_cap,
        )
        with _write_lock:
            with (directory / "pii_mapping.json").open("w", encoding="utf-8") as fh:
                json.dump(mapping, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
    except Exception:  # noqa: BLE001
        logger.debug("pii_scrub_audit output mapping write failed", exc_info=True)
