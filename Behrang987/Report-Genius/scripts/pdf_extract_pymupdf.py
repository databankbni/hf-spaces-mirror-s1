#!/usr/bin/env python3
"""Extract PDF text, page properties, and metadata using PyMuPDF (fitz).

Usage:
    python scripts/pdf_extract_pymupdf.py path/to/document.pdf
    python scripts/pdf_extract_pymupdf.py path/to/document.pdf -o ./output
    python scripts/pdf_extract_pymupdf.py path/to/document.pdf --format json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import fitz  # type: ignore[import-untyped]
except ImportError as exc:
    raise SystemExit("PyMuPDF is required: pip install pymupdf") from exc


def _rect_to_dict(rect: fitz.Rect) -> dict[str, float]:
    return {"x0": rect.x0, "y0": rect.y0, "x1": rect.x1, "y1": rect.y1, "width": rect.width, "height": rect.height}


def _page_labels(doc: fitz.Document) -> dict[int, str]:
    """Map 0-based page index to display label when custom labels exist."""
    labels: dict[int, str] = {}
    get_labels = getattr(doc, "get_page_labels", None)
    if not callable(get_labels):
        return labels
    for entry in get_labels():
        if not isinstance(entry, dict):
            continue
        start = int(entry.get("startpage", 0))
        prefix = str(entry.get("prefix", "") or "")
        style = str(entry.get("style", "") or "")
        first = int(entry.get("firstpagenum", 1))
        # PyMuPDF returns label ranges; assign sequentially from start page.
        labels[start] = f"{prefix}{first}" if style else str(start + 1)
    return labels


def _serialize(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(v) for v in value]
    return str(value)


def extract_pdf(pdf_path: Path, output_dir: Path, save_embedded: bool) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    embedded_dir = output_dir / "embedded_files"
    if save_embedded:
        embedded_dir.mkdir(parents=True, exist_ok=True)

    result: dict[str, Any] = {
        "source_pdf": str(pdf_path.resolve()),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "document": {},
        "pages": [],
        "embedded_files": [],
    }

    with fitz.open(str(pdf_path)) as doc:
        result["document"] = {
            "page_count": doc.page_count,
            "is_pdf": doc.is_pdf,
            "is_encrypted": doc.is_encrypted,
            "needs_pass": doc.needs_pass,
            "metadata": _serialize(dict(doc.metadata)),
            "table_of_contents": _serialize(doc.get_toc(simple=False)),
        }

        if save_embedded:
            for i, name in enumerate(doc.embfile_names()):
                info = doc.embfile_info(name)
                payload = doc.embfile_get(name)
                safe_name = Path(name).name or f"embedded_{i}"
                out_path = embedded_dir / safe_name
                out_path.write_bytes(payload)
                result["embedded_files"].append(
                    {
                        "name": name,
                        "saved_to": str(out_path.resolve()),
                        "size_bytes": len(payload),
                        "info": _serialize(info),
                    }
                )

        page_labels = _page_labels(doc)
        all_text_parts: list[str] = []

        for page_index in range(doc.page_count):
            page = doc[page_index]
            text = page.get_text("text") or ""
            all_text_parts.append(text)

            images = page.get_images(full=True)
            links = page.get_links()

            page_data: dict[str, Any] = {
                "page_number": page_index + 1,
                "label": page_labels.get(page_index, str(page_index + 1)),
                "rect": _rect_to_dict(page.rect),
                "rotation": page.rotation,
                "text_char_count": len(text),
                "text_line_count": len(text.splitlines()),
                "image_count": len(images),
                "link_count": len(links),
                "images": [
                    {
                        "xref": img[0],
                        "smask": img[1],
                        "width": img[2],
                        "height": img[3],
                        "colorspace": img[4],
                        "bpc": img[5],
                    }
                    for img in images
                ],
                "links": [_serialize(link) for link in links],
                "text": text,
            }
            result["pages"].append(page_data)

            page_txt_path = output_dir / f"page_{page_index + 1:04d}.txt"
            page_txt_path.write_text(text, encoding="utf-8")

    full_text = "\n\n".join(all_text_parts)
    (output_dir / f"{pdf_path.stem}_full_text.txt").write_text(full_text, encoding="utf-8")

    return result


def write_output(result: dict[str, Any], output_dir: Path, stem: str, fmt: str) -> Path:
    if fmt == "json":
        out_path = output_dir / f"{stem}_extract.json"
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        return out_path

    out_path = output_dir / f"{stem}_extract.txt"
    lines: list[str] = [
        f"Source: {result['source_pdf']}",
        f"Extracted: {result['extracted_at']}",
        "",
        "=== Document Properties ===",
    ]
    doc = result["document"]
    lines.append(f"Pages: {doc['page_count']}")
    lines.append(f"Encrypted: {doc['is_encrypted']}")
    lines.append(f"Needs password: {doc['needs_pass']}")
    lines.append("")
    lines.append("Metadata:")
    for key, value in doc.get("metadata", {}).items():
        if value:
            lines.append(f"  {key}: {value}")

    if doc.get("table_of_contents"):
        lines.extend(["", "Table of contents:"])
        for level, title, page in doc["table_of_contents"]:
            indent = "  " * max(0, int(level) - 1)
            lines.append(f"{indent}- {title} (page {page})")

    if result.get("embedded_files"):
        lines.extend(["", "=== Embedded Files ==="])
        for ef in result["embedded_files"]:
            lines.append(f"- {ef['name']} -> {ef['saved_to']} ({ef['size_bytes']} bytes)")

    for page in result["pages"]:
        lines.extend(
            [
                "",
                f"=== Page {page['page_number']} ===",
                f"Label: {page['label']}",
                f"Size: {page['rect']['width']:.1f} x {page['rect']['height']:.1f}",
                f"Rotation: {page['rotation']}",
                f"Images: {page['image_count']}, Links: {page['link_count']}",
                "",
                page["text"],
            ]
        )

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract PDF content and properties with PyMuPDF.")
    parser.add_argument("pdf", type=Path, help="Path to the input PDF file")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output directory (default: <pdf_stem>_extract next to the PDF)",
    )
    parser.add_argument(
        "--format",
        choices=("json", "txt"),
        default="json",
        help="Main summary output format (default: json)",
    )
    parser.add_argument(
        "--no-embedded",
        action="store_true",
        help="Skip extracting embedded files from the PDF",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    pdf_path: Path = args.pdf

    if not pdf_path.is_file():
        print(f"Error: PDF not found: {pdf_path}", file=sys.stderr)
        return 1
    if pdf_path.suffix.lower() != ".pdf":
        print(f"Warning: file does not have a .pdf extension: {pdf_path}", file=sys.stderr)

    output_dir = args.output or pdf_path.parent / f"{pdf_path.stem}_extract"

    try:
        result = extract_pdf(pdf_path, output_dir, save_embedded=not args.no_embedded)
        summary_path = write_output(result, output_dir, pdf_path.stem, args.format)
    except fitz.FileDataError as exc:
        print(f"Error: could not open PDF (corrupt or password-protected): {exc}", file=sys.stderr)
        return 1

    print(f"Extracted {result['document']['page_count']} page(s) from {pdf_path.name}")
    print(f"Output directory: {output_dir.resolve()}")
    print(f"Summary: {summary_path.resolve()}")
    print(f"Full text: {(output_dir / f'{pdf_path.stem}_full_text.txt').resolve()}")
    if result["embedded_files"]:
        print(f"Embedded files: {len(result['embedded_files'])} saved under {output_dir / 'embedded_files'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
