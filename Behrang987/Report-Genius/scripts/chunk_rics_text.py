#!/usr/bin/env python3
"""Chunk an already-parsed RICS report (markdown/text) or a PDF/DOCX with the
production segmenters.

Same mechanism as reference ingest:
  LLM markers (llm_segmenter)  ->  else regex (reference_chunker)

Accepts ``.md`` / ``.txt`` (e.g. LlamaParse output) or ``.pdf`` / ``.docx``
(text extracted via ``backend.ingest.doc_extractor``).

Usage (from repo root):
  python scripts/chunk_rics_text.py report.llamaparse.md -o ./chunks_out --regex-only --one-chunk-per-section
  python scripts/chunk_rics_text.py "E:\\path\\report.pdf" -o ./chunks_out --regex-only --one-chunk-per-section
"""
"""

python scripts/chunk_rics_text.py "E:\my report ai\20b Harvist Road, London, NW6 6SD_llamaparse\20b Harvist Road, London, NW6 6SD.llamaparse.md" -o "E:\my report ai\20b Harvist Road, London, NW6 6SD_llamaparse\chunks" --regex-only --one-chunk-per-section
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_TEXT_SUFFIXES = {".md", ".markdown", ".txt"}
_DOC_SUFFIXES = {".pdf", ".docx", ".docm"}
_SUPPORTED_SUFFIXES = _TEXT_SUFFIXES | _DOC_SUFFIXES


def _load_dotenv() -> None:
    import os

    for path in (_REPO_ROOT / ".env", Path.cwd() / ".env"):
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


def load_input_text(path: Path) -> str:
    """Load report text from markdown/plain text or PDF/DOCX."""
    suffix = path.suffix.lower()
    if suffix in _TEXT_SUFFIXES:
        text = path.read_text(encoding="utf-8")
        if suffix in {".md", ".markdown"}:
            return normalize_markdown_for_rics(text)
        return text
    if suffix in _DOC_SUFFIXES:
        from backend.ingest.doc_extractor import extract_text

        return extract_text(path)
    raise ValueError(
        f"Unsupported file type {suffix!r}. "
        f"Use one of: {', '.join(sorted(_SUPPORTED_SUFFIXES))}"
    )


def _chunks_to_rows(chunks: list[Any], *, scrubbed: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for c in chunks:
        text = getattr(c, "text", "") or ""
        rows.append(
            {
                "chunk_id": getattr(c, "chunk_id", "") or "",
                "section_id": getattr(c, "section_id", "") or "",
                "paragraph_index": getattr(c, "paragraph_index", 1) or 1,
                "content_role": getattr(c, "content_role", "body") or "body",
                "parent_id": getattr(c, "parent_id", "") or "",
                "document_type": getattr(c, "document_type", "reference_report")
                or "reference_report",
                "is_scrubbed": scrubbed,
                "text": text,
            }
        )
    return rows


def normalize_markdown_for_rics(text: str) -> str:
    """Delegate to the production normalizer so CLI and ingest never drift.

    Kept as a thin wrapper (same name/signature) for callers of this script.
    """
    from backend.rag.reference_chunker import normalize_reference_markdown

    return normalize_reference_markdown(text)


def _legacy_normalize_markdown_for_rics(text: str) -> str:
    """Original CLI-local implementation, retained for reference only."""
    from backend.domain.section_scope import parent_letter_for_title

    raw_lines = (text or "").splitlines()
    lines: list[str] = []
    for line in raw_lines:
        stripped = line.strip()

        # Bold leaf: **J1 Insulation**
        bold_leaf = re.match(
            r"^\*\*\s*([A-N]\d{1,2})\b(?:\s*[:.\-\u2013\u2014]\s*|\s+)([^*]+?)\s*\*\*\s*$",
            stripped,
            re.IGNORECASE,
        )
        if bold_leaf:
            code = bold_leaf.group(1).upper()
            title = bold_leaf.group(2).strip()
            lines.append(f"{code} {title}".rstrip() if title else code)
            continue

        # ATX headings: "# D1 …" / "## Outside the property" / "# J"
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            body = m.group(2).strip()
            leaf = re.match(
                r"^([A-N]\d{1,2})\b(?:\s*[:.\-\u2013\u2014]\s*|\s+)(.*)$",
                body,
                re.IGNORECASE,
            )
            if leaf:
                code = leaf.group(1).upper()
                title = (leaf.group(2) or "").strip()
                lines.append(f"{code} {title}".rstrip() if title else code)
                continue
            # Lone parent letter: "# J"
            if re.fullmatch(r"[A-N]", body, re.IGNORECASE):
                lines.append(body.upper())
                continue
            # "D Outside the property" — but not "D icon Full detail…" chrome.
            parent = re.match(r"^([A-N])\s+(.+)$", body, re.IGNORECASE)
            if parent:
                rest = parent.group(2).strip()
                rest_l = rest.lower()
                if rest_l.startswith("icon") or rest_l.startswith("logo"):
                    continue
                lines.append(parent.group(1).upper())
                lines.append(rest)
                continue
            lines.append(body)
            continue

        lines.append(line)

    # Second pass: title-only parent lines -> Letter\nTitle (unless already preceded
    # by that letter). Prevents "Inside the property" from sticking to D9.
    out: list[str] = []
    for i, line in enumerate(lines):
        letter = parent_letter_for_title(line.strip())
        if letter:
            prev = out[-1].strip().upper() if out else ""
            if prev != letter:
                out.append(letter)
            out.append(line.strip())
            continue
        out.append(line)
    return "\n".join(out)


def segment_text(
    text: str,
    *,
    source_filename: str,
    prefer_llm: bool,
    regex_only: bool,
    one_chunk_per_section: bool,
) -> tuple[list[Any], str]:
    from backend.domain.rics_level3_schema import build_canonical_template_schema
    from backend.rag.reference_chunker import build_reference_chunks

    schema = build_canonical_template_schema(source_filename="RICS_L3_CANONICAL")
    valid_ids = set(schema.section_ids())
    # Parent letters are also valid storage keys for A/B/C/K/L/M/N.
    valid_ids |= {s.id[0].upper() for s in schema.sections if s.id}

    if not regex_only and prefer_llm:
        from backend.ingest import llm_segmenter

        llm_chunks = llm_segmenter.llm_segment_reference_text(
            text,
            source_filename=source_filename,
            one_chunk_per_section=one_chunk_per_section,
        )
        if llm_chunks:
            return llm_chunks, "llm"

    chunks = build_reference_chunks(
        text,
        source_filename=source_filename,
        valid_section_ids=valid_ids,
        one_chunk_per_section=one_chunk_per_section,
        include_section_headings=True,
    )
    return chunks, "regex"


def maybe_scrub(chunks: list[Any], *, enabled: bool) -> tuple[list[Any], bool]:
    if not enabled:
        return chunks, False
    from backend.pii import scrubber as pii_scrubber

    scrubbed: list[Any] = []
    for c in chunks:
        text = getattr(c, "text", "") or ""
        cleaned, _hits = pii_scrubber.scrub_text(text)
        # Chunk is a dataclass-like object; rebuild via replace if available.
        replace = getattr(c, "model_copy", None) or getattr(c, "replace", None)
        if callable(replace):
            try:
                scrubbed.append(replace(text=cleaned, is_scrubbed=True))
                continue
            except TypeError:
                pass
        try:
            from dataclasses import replace as dc_replace

            scrubbed.append(dc_replace(c, text=cleaned, is_scrubbed=True))
        except Exception:
            c.text = cleaned  # type: ignore[attr-defined]
            if hasattr(c, "is_scrubbed"):
                c.is_scrubbed = True  # type: ignore[attr-defined]
            scrubbed.append(c)
    return scrubbed, True


def write_section_files(out_dir: Path, stem: str, rows: list[dict[str, Any]]) -> Path:
    sections_dir = out_dir / "sections"
    sections_dir.mkdir(parents=True, exist_ok=True)
    by_key: dict[str, list[str]] = {}
    for row in rows:
        if row.get("content_role") == "parent_intro":
            key = f"parent_intro_{row.get('parent_id') or 'unknown'}"
        else:
            key = row.get("section_id") or "unscoped"
        by_key.setdefault(key, []).append(row.get("text") or "")
    for key, texts in by_key.items():
        (sections_dir / f"{stem}__{key}.txt").write_text(
            "\n\n".join(t for t in texts if t.strip()),
            encoding="utf-8",
        )
    return sections_dir


def process_one(
    path: Path,
    out_dir: Path,
    *,
    prefer_llm: bool,
    regex_only: bool,
    scrub: bool,
    source_name: str | None,
    one_chunk_per_section: bool,
) -> dict[str, Any]:
    text = load_input_text(path)
    source_filename = source_name or path.name

    # Optional sidecar of extracted plain text for PDF/DOCX runs.
    if path.suffix.lower() in _DOC_SUFFIXES:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{path.stem}_extracted.txt").write_text(text, encoding="utf-8")

    chunks, method = segment_text(
        text,
        source_filename=source_filename,
        prefer_llm=prefer_llm,
        regex_only=regex_only,
        one_chunk_per_section=one_chunk_per_section,
    )
    chunks, was_scrubbed = maybe_scrub(chunks, enabled=scrub)
    rows = _chunks_to_rows(chunks, scrubbed=was_scrubbed)

    body_sections = sorted(
        {
            r["section_id"]
            for r in rows
            if r.get("content_role") != "parent_intro" and r.get("section_id")
        }
    )
    parent_intros = sorted(
        {
            r["parent_id"]
            for r in rows
            if r.get("content_role") == "parent_intro" and r.get("parent_id")
        }
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = path.stem

    file_entry = {
        "document_id": "",
        "status": "chunked",
        "file_size": path.stat().st_size,
        "content_hash": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_path": str(path.resolve()),
        "segmentation_method": method,
        "one_chunk_per_section": one_chunk_per_section,
        "chunk_count": len(rows),
        "sections": body_sections,
        "parent_intro_sections": parent_intros,
        "chunks": rows,
    }

    # Tenant-manifest shape: keyed by source filename
    extracted = {source_filename: file_entry}
    extracted_path = out_dir / "extracted_chunks.json"
    extracted_path.write_text(
        json.dumps(extracted, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Flat list sidecar (easier to inspect)
    chunks_only = {
        "source_filename": source_filename,
        "segmentation_method": method,
        "chunk_count": len(rows),
        "chunks": rows,
    }
    chunks_only_path = out_dir / "chunks_only.json"
    chunks_only_path.write_text(
        json.dumps(chunks_only, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    manifest = {
        "source_file": str(path.resolve()),
        "source_filename": source_filename,
        "extracted_at": file_entry["created_at"],
        "segmentation_method": method,
        "scrubbed": was_scrubbed,
        "chunk_count": len(rows),
        "sections": body_sections,
        "parent_intro_sections": parent_intros,
        "outputs": {
            "extracted_chunks": str(extracted_path.resolve()),
            "chunks_only": str(chunks_only_path.resolve()),
        },
    }
    manifest_path = out_dir / f"{stem}_chunk_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    sections_dir = write_section_files(out_dir, stem, rows)
    manifest["outputs"]["sections_dir"] = str(sections_dir.resolve())
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return {
        "method": method,
        "chunk_count": len(rows),
        "sections": body_sections,
        "out_dir": str(out_dir.resolve()),
        "extracted_chunks": str(extracted_path.resolve()),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Create RICS L3 chunks from an existing .md/.txt using "
            "llm_segmenter + reference_chunker (same as reference ingest)."
        )
    )
    p.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="Report path(s): .md/.txt or .pdf/.docx",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help=(
            "Output root (writes under <output>/<source_stem>/ so the folder "
            "names the PDF/MD; default: <source_dir>/<stem>_chunks)"
        ),
    )
    p.add_argument(
        "--regex-only",
        action="store_true",
        help="Skip LLM; use reference_chunker regex only (default: LLM then regex)",
    )
    p.add_argument(
        "--one-chunk-per-section",
        action="store_true",
        help=(
            "Emit exactly one chunk per subsection / parent-intro / parent body "
            "(no paragraph or max-char splitting)"
        ),
    )
    p.add_argument(
        "--multi-chunk",
        action="store_true",
        help=(
            "Allow multiple chunks per subsection when bodies exceed "
            "reference_paragraph_max_chars (default unless --one-chunk-per-section "
            "or REFERENCE_ONE_CHUNK_PER_SECTION=true)"
        ),
    )
    p.add_argument(
        "--scrub",
        action="store_true",
        help="Run PII scrubber on chunk text before save",
    )
    p.add_argument(
        "--source-name",
        default=None,
        help="Override source_filename used in chunk_ids (default: input basename)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    args = parse_args(argv)

    paths: list[Path] = []
    for p in args.inputs:
        if not p.is_file():
            print(f"Error: not found: {p}", file=sys.stderr)
            continue
        if p.suffix.lower() not in _SUPPORTED_SUFFIXES:
            print(
                f"Error: unsupported type {p.suffix!r} for {p.name} "
                f"(use {', '.join(sorted(_SUPPORTED_SUFFIXES))})",
                file=sys.stderr,
            )
            continue
        paths.append(p)
    if not paths:
        return 1

    prefer_llm = not args.regex_only
    from backend.config import settings

    if args.one_chunk_per_section and args.multi_chunk:
        print(
            "Error: pass only one of --one-chunk-per-section / --multi-chunk",
            file=sys.stderr,
        )
        return 1
    if args.one_chunk_per_section:
        one_chunk = True
    elif args.multi_chunk:
        one_chunk = False
    else:
        one_chunk = bool(settings.reference_one_chunk_per_section)

    ok = 0
    for path in paths:
        # Always keep the source stem in the output path so PDF vs MD runs
        # do not overwrite each other and the folder names the source file.
        if args.output is None:
            out_dir = path.parent / f"{path.stem}_chunks"
        else:
            out_dir = args.output / path.stem

        print(
            f"Chunking {path.name} "
            f"(one_chunk_per_section={one_chunk}) ..."
        )
        try:
            result = process_one(
                path,
                out_dir,
                prefer_llm=prefer_llm,
                regex_only=args.regex_only,
                scrub=args.scrub,
                source_name=args.source_name,
                one_chunk_per_section=one_chunk,
            )
        except Exception as exc:
            print(f"  Error: {exc}", file=sys.stderr)
            continue
        ok += 1
        print(
            f"  method={result['method']} chunks={result['chunk_count']} "
            f"sections={len(result['sections'])}"
        )
        print(f"  saved: {result['extracted_chunks']}")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

# ---------------------------------------------------------------------------
# Run examples (from Report-genius-ai repo root):
#
# Chunk LlamaParse markdown:
#   python scripts/chunk_rics_text.py "E:\my report ai\out_llamaparse\5 Hillcrest Avenue, Pinner, HA5 1AJ.llamaparse.md" -o "E:\my report ai\out_llamaparse" --regex-only --one-chunk-per-section
#
#   python scripts/chunk_rics_text.py "E:\my report ai\out_llamaparse\1a Woodland Hill London SE19 1PB.llamaparse.md" -o "E:\my report ai\out_llamaparse" --regex-only --one-chunk-per-section
#
# Chunk Textract markdown:
#   python scripts/chunk_rics_text.py "E:\my report ai\out_textract\1a Woodland Hill London SE19 1PB.textract.md" -o "E:\my report ai\out_textract" --regex-only --one-chunk-per-section
#
# Chunk a PDF directly (local extract, NOT LlamaParse/Textract):
#   python scripts/chunk_rics_text.py "E:\my report ai\5 Hillcrest Avenue, Pinner, HA5 1AJ.pdf" -o "E:\my report ai\out_llamaparse" --regex-only --one-chunk-per-section
#
# One-shot PDF -> LlamaParse MD -> chunks:
#   python scripts/rics_pdf_to_chunks.py "E:\my report ai\5 Hillcrest Avenue, Pinner, HA5 1AJ.pdf" -o "E:\my report ai\out_llamaparse" --regex-only --one-chunk-per-section
#
# One-shot PDF -> Textract MD -> chunks:
#   python scripts/rics_pdf_textract_to_chunks.py "E:\my report ai\1a Woodland Hill London SE19 1PB.pdf" -o "E:\my report ai\out_textract" --regex-only --one-chunk-per-section
#
# Chunk existing Textract MD via one-shot helper:
#   python scripts/rics_pdf_textract_to_chunks.py --from-md "E:\my report ai\out_textract\1a Woodland Hill London SE19 1PB.textract.md" -o "E:\my report ai\out_textract" --regex-only --one-chunk-per-section
# ---------------------------------------------------------------------------
