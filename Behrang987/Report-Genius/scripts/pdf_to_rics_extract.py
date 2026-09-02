#!/usr/bin/env python3
"""Convert a RICS Home Survey PDF to HTML / Markdown / XML, then extract
sections against the canonical RICS Level 3 template (14 parents A-N, 57 leaves).

Pipeline:
  PDF -> html + md + xml -> plain text -> RICS section chunks (JSON)

Usage (from repo root):
  python scripts/pdf_to_rics_extract.py path/to/report.pdf
  python scripts/pdf_to_rics_extract.py path/to/report.pdf -o ./out
  python scripts/pdf_to_rics_extract.py path/to/report.pdf --llm
  python scripts/pdf_to_rics_extract.py path/to/*.pdf -o ./batch_out

Requires: pymupdf  (pip install pymupdf)
Optional: run from repo root so backend.rag.reference_chunker / llm_segmenter
are importable for production-grade segmentation.
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.dom import minidom

try:
    import fitz  # type: ignore[import-untyped]
except ImportError as exc:
    raise SystemExit("PyMuPDF is required: pip install pymupdf") from exc

# ---------------------------------------------------------------------------
# Repo bootstrap (so `backend.*` imports work when run as a script)
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Canonical RICS L3 template (embedded fallback; prefer backend schema)
# ---------------------------------------------------------------------------
_PARENT_STORAGE = frozenset({"A", "B", "C", "K", "L", "M", "N"})
_LEAF_STORAGE = frozenset({"D", "E", "F", "G", "H", "I", "J"})

_CANONICAL_PARENTS: list[dict[str, Any]] = [
    {"id": "A", "label": "About the inspection", "leaves": ["A1", "A2", "A3", "A4", "A5"]},
    {
        "id": "B",
        "label": "Overall opinion and summary of the condition ratings",
        "leaves": ["B1", "B2", "B3"],
    },
    {"id": "C", "label": "About the property", "leaves": ["C1", "C2", "C3", "C4", "C5"]},
    {
        "id": "D",
        "label": "Outside the property",
        "leaves": ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9"],
    },
    {
        "id": "E",
        "label": "Inside the property",
        "leaves": ["E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "E9"],
    },
    {
        "id": "F",
        "label": "Services",
        "leaves": ["F1", "F2", "F3", "F4", "F5", "F6", "F7"],
    },
    {
        "id": "G",
        "label": "Grounds (including shared areas for flats)",
        "leaves": ["G1", "G2", "G3"],
    },
    {
        "id": "H",
        "label": "Issues for your legal advisers",
        "leaves": ["H1", "H2", "H3"],
    },
    {"id": "I", "label": "Risks", "leaves": ["I1", "I2", "I3", "I4"]},
    {"id": "J", "label": "Energy matters", "leaves": ["J1", "J2", "J3", "J4", "J5"]},
    {"id": "K", "label": "Surveyor's declaration", "leaves": ["K1"]},
    {"id": "L", "label": "What to do now", "leaves": ["L1"]},
    {"id": "M", "label": "Description of the RICS Home Survey – Level 3 service and terms of engagement", "leaves": ["M1"]},
    {"id": "N", "label": "Typical house diagram", "leaves": ["N1"]},
]

_RICS_HEADING_LINE = re.compile(
    r"""
    (?m)^\s*
    (?:(?:section|part|element|item)\s+)?
    (?P<code>[A-N]\d{1,2})
    \b
    (?:[\s:.\-\u2013\u2014]+[^\n]{0,120})?
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)
_PARENT_BANNER_RE = re.compile(
    r"(?m)^\s*(?P<letter>[A-N])\s*\n\s*(?P<title>[^\n]{3,120})\s*$"
)
_TOC_LINE_RE = re.compile(r"(?im)^[ \t]*ToC:[A-N]\b.*$")
_SECTION_PAGE_RE = re.compile(r"(?im)^[ \t]*section-page[ \t]*$")
_REPORT_PAGE_RE = re.compile(r"(?im)^[ \t]*report-page[ \t]*$")
_PAGE_HEADER_FURNITURE_RE = re.compile(
    r"(?im)^[ \t]*(?:page[ \t]*\d+[ \t]*)?"
    r"rics[ \t]+home[ \t]+survey[ \t]*[-\u2013\u2014][ \t]*level[ \t]+\d.*$"
)
_PAGE_LABEL_RE = re.compile(r"(?im)^[ \t]*page[ \t]*\d+[ \t]*$")
_ORPHAN_RATING_BADGE_RE = re.compile(r"(?m)^[ \t]*[123][ \t]*$")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")
_C_PROSE_HEADINGS = (
    "Type of property",
    "Approximate year of construction",
    "Approximate year of extension",
    "Approximate year of conversion",
    "Information relevant to flats and maisonettes",
    "Construction",
    "Accommodation",
    "Means of escape",
    "Energy",
    "Energy efficiency",
    "Mains services",
    "Central heating",
    "Other services or energy sources",
    "Grounds",
    "Location",
    "Facilities",
    "Local environment",
)
_C_PROSE_HEADING_RE = re.compile(
    r"(?im)^[ \t]*(?:"
    + "|".join(re.escape(h) for h in _C_PROSE_HEADINGS)
    + r")[ \t]*:?[ \t]*$"
)


def _storage_section_id(section_id: str) -> str:
    sid = (section_id or "").strip().upper()
    if not sid:
        return ""
    parent = sid[0]
    if parent in _PARENT_STORAGE:
        return parent
    return sid


def _valid_section_ids() -> set[str]:
    ids: set[str] = set()
    for parent in _CANONICAL_PARENTS:
        ids.add(parent["id"])
        for leaf in parent["leaves"]:
            ids.add(leaf)
    return ids


def load_rics_template() -> dict[str, Any]:
    """Load canonical RICS L3 template from backend when available."""
    try:
        from backend.domain.rics_level3_schema import (  # type: ignore[import-not-found]
            CANONICAL_SCHEMA_VERSION,
            build_canonical_template_schema,
        )

        schema = build_canonical_template_schema(source_filename="RICS_L3_CANONICAL")
        return {
            "source": "backend.domain.rics_level3_schema",
            "version": CANONICAL_SCHEMA_VERSION,
            "sections": [
                {
                    "id": s.id,
                    "label": s.label,
                    "order": s.order,
                    "has_rating_field": s.has_rating_field,
                    "subsections": [
                        {"id": sub.id, "label": sub.label} for sub in (s.subsections or [])
                    ],
                }
                for s in schema.sections
            ],
            "valid_section_ids": sorted(
                {s.id for s in schema.sections}
                | {sub.id for s in schema.sections for sub in (s.subsections or [])}
            ),
        }
    except Exception:
        return {
            "source": "embedded_fallback",
            "version": "v4.0",
            "sections": _CANONICAL_PARENTS,
            "valid_section_ids": sorted(_valid_section_ids()),
        }


# ---------------------------------------------------------------------------
# PDF → HTML / Markdown / XML
# ---------------------------------------------------------------------------


def convert_pdf_formats(pdf_path: Path, out_dir: Path) -> dict[str, Any]:
    """Write HTML, Markdown, and XML sidecars; return paths + plain text."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem

    html_parts: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8"/>',
        f"<title>{html_lib.escape(stem)}</title>",
        "<style>body{font-family:Georgia,serif;max-width:48rem;margin:2rem auto;"
        "line-height:1.45} .page{page-break-after:always;margin-bottom:2rem;"
        "border-bottom:1px solid #ccc;padding-bottom:1.5rem}"
        " h2.page-label{color:#444;font-size:0.95rem}</style>",
        "</head>",
        "<body>",
        f"<h1>{html_lib.escape(stem)}</h1>",
    ]
    md_parts: list[str] = [f"# {stem}", ""]
    xml_root = ET.Element(
        "ricsDocument",
        {
            "source": str(pdf_path.resolve()),
            "extractedAt": datetime.now(timezone.utc).isoformat(),
        },
    )
    plain_parts: list[str] = []

    with fitz.open(str(pdf_path)) as doc:
        xml_root.set("pageCount", str(doc.page_count))
        meta = ET.SubElement(xml_root, "metadata")
        for key, value in (doc.metadata or {}).items():
            if value:
                m = ET.SubElement(meta, "meta", {"name": str(key)})
                m.text = str(value)

        for page_index in range(doc.page_count):
            page = doc[page_index]
            page_no = page_index + 1
            text = page.get_text("text") or ""
            plain_parts.append(text)

            # Prefer PyMuPDF HTML; fall back to escaped pre if empty.
            page_html = page.get_text("html") or ""
            if not page_html.strip():
                page_html = f"<pre>{html_lib.escape(text)}</pre>"
            html_parts.append(f'<section class="page" id="page-{page_no}">')
            html_parts.append(f'<h2 class="page-label">Page {page_no}</h2>')
            html_parts.append(page_html)
            html_parts.append("</section>")

            md_parts.append(f"## Page {page_no}")
            md_parts.append("")
            md_parts.append(_text_to_markdown_blocks(text))
            md_parts.append("")

            page_el = ET.SubElement(xml_root, "page", {"number": str(page_no)})
            # Structured blocks (dict) → XML paragraphs / lines
            blocks = page.get_text("dict").get("blocks") or []
            for bi, block in enumerate(blocks):
                if block.get("type") != 0:
                    continue
                block_el = ET.SubElement(
                    page_el, "block", {"index": str(bi), "bbox": _bbox_attr(block.get("bbox"))}
                )
                for line in block.get("lines") or []:
                    spans = line.get("spans") or []
                    line_text = "".join(str(s.get("text") or "") for s in spans).strip()
                    if not line_text:
                        continue
                    line_el = ET.SubElement(block_el, "line")
                    line_el.text = line_text
            if not list(page_el):
                # No text blocks — store raw page text
                raw = ET.SubElement(page_el, "rawText")
                raw.text = text

    html_parts.extend(["</body>", "</html>"])
    full_text = "\n\n".join(plain_parts)

    html_path = out_dir / f"{stem}.html"
    md_path = out_dir / f"{stem}.md"
    xml_path = out_dir / f"{stem}.xml"
    txt_path = out_dir / f"{stem}.txt"

    html_path.write_text("\n".join(html_parts), encoding="utf-8")
    md_path.write_text("\n".join(md_parts), encoding="utf-8")
    xml_path.write_text(_pretty_xml(xml_root), encoding="utf-8")
    txt_path.write_text(full_text, encoding="utf-8")

    return {
        "html": html_path,
        "md": md_path,
        "xml": xml_path,
        "txt": txt_path,
        "plain_text": full_text,
        "page_count": len(plain_parts),
    }


def _bbox_attr(bbox: Any) -> str:
    if not bbox:
        return ""
    try:
        return ",".join(f"{float(v):.1f}" for v in bbox)
    except (TypeError, ValueError):
        return str(bbox)


def _text_to_markdown_blocks(text: str) -> str:
    """Light MD shaping: promote lone RICS codes / parent banners to headings."""
    lines = (text or "").splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if _RICS_HEADING_LINE.match(stripped):
            out.append(f"### {stripped}")
            out.append("")
            i += 1
            continue
        if (
            re.fullmatch(r"[A-N]", stripped)
            and i + 1 < len(lines)
            and len(lines[i + 1].strip()) >= 3
        ):
            out.append(f"## {stripped} {lines[i + 1].strip()}")
            out.append("")
            i += 2
            continue
        out.append(line)
        i += 1
    return "\n".join(out).strip()


def _pretty_xml(root: ET.Element) -> str:
    rough = ET.tostring(root, encoding="utf-8")
    parsed = minidom.parseString(rough)
    return parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")


# ---------------------------------------------------------------------------
# Text cleanup + RICS extraction
# ---------------------------------------------------------------------------


def strip_pdf_furniture(text: str) -> str:
    cleaned = text or ""
    cleaned = _TOC_LINE_RE.sub("", cleaned)
    cleaned = _SECTION_PAGE_RE.sub("", cleaned)
    cleaned = _REPORT_PAGE_RE.sub("", cleaned)
    cleaned = _ORPHAN_RATING_BADGE_RE.sub("", cleaned)
    cleaned = _PAGE_HEADER_FURNITURE_RE.sub("", cleaned)
    cleaned = _PAGE_LABEL_RE.sub("", cleaned)
    cleaned = _MULTI_BLANK_RE.sub("\n\n", cleaned)
    return cleaned


def _alpha_len(text: str) -> int:
    return sum(1 for ch in text if ch.isalpha())


def _text_from_converted(paths: dict[str, Path], prefer: str) -> str:
    """Re-read converted sidecars so extraction is based on converted content."""
    if prefer == "md":
        raw = paths["md"].read_text(encoding="utf-8")
        # Drop MD heading markers we added; keep body text.
        raw = re.sub(r"(?m)^#{1,3}\s+", "", raw)
        return raw
    if prefer == "xml":
        tree = ET.parse(paths["xml"])
        root = tree.getroot()
        lines: list[str] = []
        for page in root.findall("page"):
            for line in page.findall(".//line"):
                if line.text:
                    lines.append(line.text)
            raw = page.find("rawText")
            if raw is not None and raw.text:
                lines.append(raw.text)
        return "\n".join(lines)
    if prefer == "html":
        raw = paths["html"].read_text(encoding="utf-8")
        # Crude tag strip — good enough for RICS heading regexes.
        raw = re.sub(r"(?is)<script[^>]*>.*?</script>", "", raw)
        raw = re.sub(r"(?is)<style[^>]*>.*?</style>", "", raw)
        raw = re.sub(r"(?s)<[^>]+>", "\n", raw)
        raw = html_lib.unescape(raw)
        return _MULTI_BLANK_RE.sub("\n\n", raw)
    return paths["txt"].read_text(encoding="utf-8")


def extract_rics_fallback(text: str, *, source_filename: str) -> list[dict[str, Any]]:
    """Regex segmenter mirroring backend.rag.reference_chunker storage rules."""
    text = strip_pdf_furniture(text)
    valid = _valid_section_ids()
    chunks: list[dict[str, Any]] = []

    matches = list(_RICS_HEADING_LINE.finditer(text))
    best_body: dict[str, str] = {}
    for i, match in enumerate(matches):
        code = re.sub(r"\s+", "", match.group("code").strip().upper())
        if code not in valid:
            continue
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[match.end() : end].strip()
        body = _MULTI_BLANK_RE.sub("\n\n", body).strip()
        if not body:
            continue
        if _alpha_len(body) > _alpha_len(best_body.get(code, "")):
            best_body[code] = body

    seen_parent: set[str] = set()
    for code, body in best_body.items():
        stored = _storage_section_id(code)
        if stored != code:
            seen_parent.add(stored)
        chunks.append(
            {
                "chunk_id": f"{source_filename}:{code}:p1",
                "section_id": stored,
                "paragraph_index": 1,
                "content_role": "body",
                "parent_id": stored[0] if stored else "",
                "document_type": "reference_report",
                "text": body,
            }
        )

    # Parent-level bodies for A/B/C/K/L/M/N
    banners = list(_PARENT_BANNER_RE.finditer(text))
    starts: list[tuple[str, int]] = [
        (b.group("letter").upper(), b.end())
        for b in banners
        if b.group("letter").upper() in _PARENT_STORAGE
    ]
    if not any(letter == "C" for letter, _ in starts):
        c_hit = _C_PROSE_HEADING_RE.search(text)
        if c_hit:
            starts.append(("C", c_hit.start()))

    parent_best: dict[str, str] = {}
    for letter, start in starts:
        if letter in seen_parent:
            continue
        end = len(text)
        for banner in banners:
            if banner.start() > start:
                end = min(end, banner.start())
                break
        for match in matches:
            if match.start() > start:
                end = min(end, match.start())
                break
        body = text[start:end].strip()
        if body and _alpha_len(body) > _alpha_len(parent_best.get(letter, "")):
            parent_best[letter] = body

    for parent_id, body in sorted(parent_best.items()):
        chunks.append(
            {
                "chunk_id": f"{source_filename}:{parent_id}:p1",
                "section_id": parent_id,
                "paragraph_index": 1,
                "content_role": "body",
                "parent_id": parent_id,
                "document_type": "reference_report",
                "text": body,
            }
        )

    # Parent intros (D–J) between banner and first leaf
    intro_best: dict[str, str] = {}
    for banner in banners:
        parent = banner.group("letter").upper()
        if parent not in _LEAF_STORAGE:
            continue
        intro_start = banner.end()
        first_leaf: int | None = None
        for match in matches:
            code = re.sub(r"\s+", "", match.group("code").strip().upper())
            if code not in valid or code[0] != parent:
                continue
            if match.start() < intro_start:
                continue
            first_leaf = match.start()
            break
        if first_leaf is None:
            continue
        intro = text[intro_start:first_leaf].strip()
        if intro and _alpha_len(intro) > _alpha_len(intro_best.get(parent, "")):
            intro_best[parent] = intro

    for parent_id, body in sorted(intro_best.items()):
        chunks.append(
            {
                "chunk_id": f"{source_filename}:parent_{parent_id}:p1",
                "section_id": "",
                "paragraph_index": 1,
                "content_role": "parent_intro",
                "parent_id": parent_id,
                "document_type": "reference_report",
                "text": body,
            }
        )

    return chunks


def extract_rics_backend(
    text: str, *, source_filename: str, use_llm: bool
) -> tuple[list[dict[str, Any]], str]:
    """Use production segmenters when importable. Returns (chunks, method)."""
    try:
        from backend.domain.rics_level3_schema import (  # type: ignore[import-not-found]
            build_canonical_template_schema,
        )
        from backend.domain.section_scope import storage_section_id  # type: ignore[import-not-found]
        from backend.rag.reference_chunker import (  # type: ignore[import-not-found]
            build_reference_chunks,
            strip_pdf_extract_furniture,
        )
    except Exception as exc:
        return extract_rics_fallback(text, source_filename=source_filename), f"fallback({exc})"

    cleaned = strip_pdf_extract_furniture(text)
    schema = build_canonical_template_schema(source_filename="RICS_L3_CANONICAL")
    valid_ids = {s.id for s in schema.sections} | {
        sub.id for s in schema.sections for sub in (s.subsections or [])
    }

    method = "regex"
    chunk_objs: list[Any] = []

    if use_llm:
        try:
            from backend.ingest.llm_segmenter import (  # type: ignore[import-not-found]
                llm_segment_reference_text,
            )

            llm_chunks = llm_segment_reference_text(
                cleaned, source_filename=source_filename
            )
            if llm_chunks:
                chunk_objs = llm_chunks
                method = "llm"
        except Exception:
            chunk_objs = []

    if not chunk_objs:
        chunk_objs = build_reference_chunks(
            cleaned,
            source_filename=source_filename,
            valid_section_ids=valid_ids,
        )
        method = "regex"

    out: list[dict[str, Any]] = []
    for c in chunk_objs:
        sid = getattr(c, "section_id", "") or ""
        role = getattr(c, "content_role", "body") or "body"
        parent = getattr(c, "parent_id", "") or (sid[:1] if sid else "")
        if sid and role == "body":
            sid = storage_section_id(sid) or sid
        out.append(
            {
                "chunk_id": getattr(c, "chunk_id", "") or "",
                "section_id": sid,
                "paragraph_index": getattr(c, "paragraph_index", 1) or 1,
                "content_role": role,
                "parent_id": parent,
                "document_type": getattr(c, "document_type", "reference_report"),
                "text": getattr(c, "text", "") or "",
            }
        )
    return out, method


def build_manifest(
    *,
    pdf_path: Path,
    converted: dict[str, Any],
    template: dict[str, Any],
    chunks: list[dict[str, Any]],
    method: str,
    source_format: str,
) -> dict[str, Any]:
    body_sections = sorted(
        {
            c["section_id"]
            for c in chunks
            if c.get("content_role") == "body" and c.get("section_id")
        }
    )
    parent_intros = sorted(
        {
            c["parent_id"]
            for c in chunks
            if c.get("content_role") == "parent_intro" and c.get("parent_id")
        }
    )
    return {
        "source_pdf": str(pdf_path.resolve()),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "page_count": converted["page_count"],
        "converted_files": {
            "html": str(converted["html"].resolve()),
            "md": str(converted["md"].resolve()),
            "xml": str(converted["xml"].resolve()),
            "txt": str(converted["txt"].resolve()),
        },
        "extraction": {
            "source_format": source_format,
            "method": method,
            "template_source": template["source"],
            "template_version": template["version"],
        },
        "chunk_count": len(chunks),
        "sections": body_sections,
        "parent_intro_sections": parent_intros,
        "template_sections": template["sections"],
        "chunks": chunks,
    }


def write_section_sidecars(out_dir: Path, stem: str, chunks: list[dict[str, Any]]) -> Path:
    """Write one .txt per storage section under sections/."""
    sections_dir = out_dir / "sections"
    sections_dir.mkdir(parents=True, exist_ok=True)
    by_key: dict[str, list[str]] = {}
    for c in chunks:
        if c.get("content_role") == "parent_intro":
            key = f"parent_intro_{c.get('parent_id') or 'unknown'}"
        else:
            key = c.get("section_id") or "unscoped"
        by_key.setdefault(key, []).append(c.get("text") or "")

    for key, texts in by_key.items():
        path = sections_dir / f"{stem}__{key}.txt"
        path.write_text("\n\n".join(t for t in texts if t.strip()), encoding="utf-8")
    return sections_dir


def process_one(
    pdf_path: Path,
    output_root: Path,
    *,
    use_llm: bool,
    source_format: str,
) -> dict[str, Any]:
    out_dir = output_root / pdf_path.stem
    converted = convert_pdf_formats(pdf_path, out_dir)
    template = load_rics_template()

    paths = {
        "html": converted["html"],
        "md": converted["md"],
        "xml": converted["xml"],
        "txt": converted["txt"],
    }
    text = _text_from_converted(paths, source_format)
    chunks, method = extract_rics_backend(
        text, source_filename=pdf_path.name, use_llm=use_llm
    )
    if method.startswith("fallback"):
        # Already fallback chunks
        pass

    manifest = build_manifest(
        pdf_path=pdf_path,
        converted=converted,
        template=template,
        chunks=chunks,
        method=method,
        source_format=source_format,
    )
    manifest_path = out_dir / f"{pdf_path.stem}_rics_extract.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    # Compact extracted_chunks-shaped sidecar (matches tenant manifest shape)
    compact = {
        pdf_path.name: {
            "chunk_count": manifest["chunk_count"],
            "sections": manifest["sections"],
            "parent_intro_sections": manifest["parent_intro_sections"],
            "chunks": chunks,
        }
    }
    (out_dir / "extracted_chunks.json").write_text(
        json.dumps(compact, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    sections_dir = write_section_sidecars(out_dir, pdf_path.stem, chunks)

    # Persist template used for this run
    (out_dir / "rics_template.json").write_text(
        json.dumps(template, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return {
        "pdf": str(pdf_path),
        "out_dir": str(out_dir.resolve()),
        "manifest": str(manifest_path.resolve()),
        "sections_dir": str(sections_dir.resolve()),
        "chunk_count": len(chunks),
        "sections": manifest["sections"],
        "method": method,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Convert PDF -> HTML/MD/XML, then extract RICS L3 sections "
            "from the converted content."
        )
    )
    p.add_argument(
        "pdfs",
        nargs="+",
        type=Path,
        help="One or more PDF paths (shell globs expanded by the shell)",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output root (default: <first_pdf_dir>/rics_extract)",
    )
    p.add_argument(
        "--from",
        dest="source_format",
        choices=("txt", "md", "html", "xml"),
        default="txt",
        help="Which converted artifact to segment from (default: txt)",
    )
    p.add_argument(
        "--llm",
        action="store_true",
        help="Prefer LLM segmentation when backend + API key are available",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    pdfs = [p for p in args.pdfs if p.is_file() and p.suffix.lower() == ".pdf"]
    missing = [p for p in args.pdfs if not p.is_file()]
    non_pdf = [p for p in args.pdfs if p.is_file() and p.suffix.lower() != ".pdf"]

    for p in missing:
        print(f"Error: not found: {p}", file=sys.stderr)
    for p in non_pdf:
        print(f"Warning: skipping non-PDF: {p}", file=sys.stderr)
    if not pdfs:
        print("Error: no PDF files to process.", file=sys.stderr)
        return 1

    output_root = args.output or (pdfs[0].parent / "rics_extract")
    output_root.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for pdf in pdfs:
        print(f"Processing {pdf.name} …")
        try:
            result = process_one(
                pdf,
                output_root,
                use_llm=args.llm,
                source_format=args.source_format,
            )
        except fitz.FileDataError as exc:
            print(f"  Error: could not open PDF: {exc}", file=sys.stderr)
            continue
        results.append(result)
        print(f"  pages -> html/md/xml under {result['out_dir']}")
        print(
            f"  RICS extract ({result['method']}): "
            f"{result['chunk_count']} chunk(s), "
            f"{len(result['sections'])} section(s) -> {result['manifest']}"
        )

    summary_path = output_root / "batch_summary.json"
    summary_path.write_text(
        json.dumps({"results": results}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nDone. {len(results)}/{len(pdfs)} PDF(s). Summary: {summary_path.resolve()}")
    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main())
