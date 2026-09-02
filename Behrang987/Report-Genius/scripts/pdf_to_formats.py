#!/usr/bin/env python3
"""Convert PDF directly to HTML, Markdown, and XML via PyMuPDF (no pypdf).

Uses MuPDF's native structured exporters — not a plain-text extract wrapped
in tags. Markdown prefers pymupdf4llm when installed; otherwise builds MD
from PyMuPDF block/span layout.

Usage:
  python scripts/pdf_to_formats.py report.pdf
  python scripts/pdf_to_formats.py report.pdf -o ./out
  python scripts/pdf_to_formats.py a.pdf b.pdf -o ./batch
  python scripts/pdf_to_formats.py report.pdf --only html xml

Requires: pymupdf
Optional:  pip install pymupdf4llm   # higher-quality Markdown
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import fitz  # type: ignore[import-untyped]
except ImportError as exc:
    raise SystemExit("PyMuPDF is required: pip install pymupdf") from exc


def _has_pymupdf4llm() -> bool:
    try:
        import pymupdf4llm  # noqa: F401

        return True
    except ImportError:
        return False


def pdf_to_html(doc: fitz.Document) -> str:
    """Whole-document HTML via MuPDF's HTML textwriter (layout-aware)."""
    parts: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8"/>',
        f"<title>{_esc(doc.metadata.get('title') or 'document')}</title>",
        "</head>",
        "<body>",
    ]
    for i in range(doc.page_count):
        page = doc[i]
        # Native HTML: font, size, position — not plain-text wrapping.
        parts.append(f'<!-- page {i + 1} -->')
        parts.append(page.get_text("html") or "")
    parts.extend(["</body>", "</html>"])
    return "\n".join(parts)


def pdf_to_xml(doc: fitz.Document, source: Path) -> str:
    """Whole-document XML via MuPDF's XML textwriter (chars/spans/lines/blocks)."""
    header = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<document source="{_esc_attr(str(source.resolve()))}" '
        f'pageCount="{doc.page_count}" '
        f'extractedAt="{datetime.now(timezone.utc).isoformat()}">\n'
    )
    pages: list[str] = []
    for i in range(doc.page_count):
        page = doc[i]
        # Native XML tree from MuPDF — not hand-built from .get_text("text").
        body = page.get_text("xml") or ""
        pages.append(f'<page number="{i + 1}">\n{body}\n</page>')
    return header + "\n".join(pages) + "\n</document>\n"


def pdf_to_markdown(doc: fitz.Document, pdf_path: Path) -> str:
    """Markdown: pymupdf4llm when available, else layout-aware block dump."""
    if _has_pymupdf4llm():
        import pymupdf4llm  # type: ignore[import-untyped]

        # Direct PDF -> Markdown (tables, headers, structure).
        return pymupdf4llm.to_markdown(str(pdf_path))

    parts: list[str] = [f"# {_doc_title(doc, pdf_path)}", ""]
    for i in range(doc.page_count):
        page = doc[i]
        parts.append(f"## Page {i + 1}")
        parts.append("")
        parts.append(_page_blocks_to_md(page))
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def _page_blocks_to_md(page: fitz.Page) -> str:
    """Build MD from dict blocks/spans (still no pypdf; no plain-text-first)."""
    data = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    lines_out: list[str] = []
    for block in data.get("blocks") or []:
        if block.get("type") != 0:  # text only
            continue
        for line in block.get("lines") or []:
            spans = line.get("spans") or []
            if not spans:
                continue
            # Use largest span size on the line as a crude heading signal.
            max_size = max(float(s.get("size") or 0) for s in spans)
            text = "".join(str(s.get("text") or "") for s in spans).rstrip()
            if not text.strip():
                continue
            flags = 0
            for s in spans:
                flags |= int(s.get("flags") or 0)
            bold = bool(flags & 2 ** 4)  # bit 4 = bold in MuPDF span flags
            if max_size >= 16:
                lines_out.append(f"### {text.strip()}")
            elif bold and max_size >= 12:
                lines_out.append(f"**{text.strip()}**")
            else:
                lines_out.append(text)
        lines_out.append("")  # blank between blocks
    return "\n".join(lines_out).strip()


def _doc_title(doc: fitz.Document, pdf_path: Path) -> str:
    title = (doc.metadata or {}).get("title") or ""
    return title.strip() or pdf_path.stem


def _esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _esc_attr(s: str) -> str:
    return _esc(s).replace("'", "&apos;")


def convert_one(
    pdf_path: Path,
    out_dir: Path,
    *,
    formats: set[str],
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem
    written: dict[str, Path] = {}

    with fitz.open(str(pdf_path)) as doc:
        if "html" in formats:
            path = out_dir / f"{stem}.html"
            path.write_text(pdf_to_html(doc), encoding="utf-8")
            written["html"] = path
        if "xml" in formats:
            path = out_dir / f"{stem}.xml"
            path.write_text(pdf_to_xml(doc, pdf_path), encoding="utf-8")
            written["xml"] = path
        if "md" in formats:
            path = out_dir / f"{stem}.md"
            path.write_text(pdf_to_markdown(doc, pdf_path), encoding="utf-8")
            written["md"] = path

    return written


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Convert PDF directly to HTML / Markdown / XML with PyMuPDF "
            "(no pypdf, no plain-text-first wrap)."
        )
    )
    p.add_argument("pdfs", nargs="+", type=Path, help="Input PDF path(s)")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output directory (default: <pdf_dir>/<stem>_formats)",
    )
    p.add_argument(
        "--only",
        nargs="+",
        choices=("html", "md", "xml"),
        default=None,
        help="Write only these formats (default: all three)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    formats = set(args.only) if args.only else {"html", "md", "xml"}
    pdfs = [p for p in args.pdfs if p.is_file() and p.suffix.lower() == ".pdf"]
    for p in args.pdfs:
        if not p.is_file():
            print(f"Error: not found: {p}", file=sys.stderr)
        elif p.suffix.lower() != ".pdf":
            print(f"Warning: skipping non-PDF: {p}", file=sys.stderr)
    if not pdfs:
        print("Error: no PDF files to process.", file=sys.stderr)
        return 1

    md_engine = "pymupdf4llm" if _has_pymupdf4llm() else "pymupdf-blocks"
    print(f"Engine: PyMuPDF {fitz.version[0]} | Markdown: {md_engine}")

    for pdf in pdfs:
        out_dir = args.output
        if out_dir is None:
            out_dir = pdf.parent / f"{pdf.stem}_formats"
        elif len(pdfs) > 1:
            out_dir = out_dir / pdf.stem

        try:
            written = convert_one(pdf, out_dir, formats=formats)
        except fitz.FileDataError as exc:
            print(f"Error: {pdf.name}: {exc}", file=sys.stderr)
            continue

        print(f"{pdf.name} -> {out_dir.resolve()}")
        for fmt, path in written.items():
            print(f"  {fmt}: {path.name} ({path.stat().st_size} bytes)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
