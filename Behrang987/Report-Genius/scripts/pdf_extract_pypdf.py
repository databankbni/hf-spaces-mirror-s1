#!/usr/bin/env python3
"""Extract PDF text, page properties, and metadata using pypdf.

Usage:
    python scripts/pdf_extract_pypdf.py path/to/document.pdf
    python scripts/pdf_extract_pypdf.py path/to/document.pdf -o ./output
    python scripts/pdf_extract_pypdf.py path/to/document.pdf --format json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
except ImportError as exc:
    raise SystemExit("pypdf is required: pip install pypdf") from exc


def _box_to_dict(box: Any) -> dict[str, float]:
    return {
        "x0": float(box.left),
        "y0": float(box.bottom),
        "x1": float(box.right),
        "y1": float(box.top),
        "width": float(box.width),
        "height": float(box.height),
    }


def _serialize(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(v) for v in value]
    return str(value)


def _metadata_dict(reader: PdfReader) -> dict[str, str]:
    raw = reader.metadata
    if not raw:
        return {}
    key_map = {
        "/Title": "title",
        "/Author": "author",
        "/Subject": "subject",
        "/Keywords": "keywords",
        "/Creator": "creator",
        "/Producer": "producer",
        "/CreationDate": "creationDate",
        "/ModDate": "modDate",
        "/Trapped": "trapped",
    }
    out: dict[str, str] = {"format": reader.pdf_header or ""}
    for src, dst in key_map.items():
        value = raw.get(src)  # type: ignore[index]
        out[dst] = "" if value is None else str(value)
    return out


def _flatten_outline(items: Any, reader: PdfReader, level: int = 1) -> list[list[Any]]:
    toc: list[list[Any]] = []
    for item in items or []:
        if isinstance(item, list):
            toc.extend(_flatten_outline(item, reader, level + 1))
            continue
        try:
            page_index = reader.get_destination_page_number(item)
        except Exception:
            page_index = -1
        title = getattr(item, "title", str(item))
        toc.append([level, title, page_index + 1 if page_index >= 0 else 0])
    return toc


def _page_annotations(page: Any) -> list[dict[str, Any]]:
    annotations: list[dict[str, Any]] = []
    for annot in page.annotations or []:
        try:
            obj = annot.get_object()
        except Exception:
            continue
        annotations.append(
            {
                "subtype": str(obj.get("/Subtype", "")),
                "contents": str(obj.get("/Contents", "") or ""),
                "rect": _serialize(obj.get("/Rect")),
            }
        )
    return annotations


def _extract_attachments(reader: PdfReader, embedded_dir: Path) -> list[dict[str, Any]]:
    embedded: list[dict[str, Any]] = []

    attachment_list = getattr(reader, "attachment_list", None)
    if attachment_list is not None:
        for i, attachment in enumerate(attachment_list):
            name = attachment.name or f"embedded_{i}"
            payload = attachment.content or b""
            safe_name = Path(name).name or f"embedded_{i}"
            out_path = embedded_dir / safe_name
            out_path.write_bytes(payload)
            embedded.append(
                {
                    "name": name,
                    "saved_to": str(out_path.resolve()),
                    "size_bytes": len(payload),
                    "info": {
                        "alternative_name": getattr(attachment, "alternative_name", None),
                    },
                }
            )
        return embedded

    for name, content_list in (reader.attachments or {}).items():
        for i, payload in enumerate(content_list):
            safe_name = Path(name).name or f"embedded_{i}"
            out_path = embedded_dir / safe_name
            out_path.write_bytes(payload)
            embedded.append(
                {
                    "name": name,
                    "saved_to": str(out_path.resolve()),
                    "size_bytes": len(payload),
                    "info": {"index": i},
                }
            )
    return embedded


def extract_pdf(pdf_path: Path, output_dir: Path, save_embedded: bool) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    embedded_dir = output_dir / "embedded_files"
    if save_embedded:
        embedded_dir.mkdir(parents=True, exist_ok=True)

    result: dict[str, Any] = {
        "source_pdf": str(pdf_path.resolve()),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "extractor": "pypdf",
        "document": {},
        "pages": [],
        "embedded_files": [],
    }

    reader = PdfReader(str(pdf_path))
    try:
        page_labels = list(reader.page_labels or [])
        result["document"] = {
            "page_count": len(reader.pages),
            "is_pdf": True,
            "is_encrypted": reader.is_encrypted,
            "needs_pass": reader.is_encrypted and not reader.user_access_permissions,
            "metadata": _serialize(_metadata_dict(reader)),
            "table_of_contents": _serialize(_flatten_outline(reader.outline, reader)),
            "page_layout": reader.page_layout,
            "page_mode": reader.page_mode,
        }

        if save_embedded:
            result["embedded_files"] = _extract_attachments(reader, embedded_dir)

        all_text_parts: list[str] = []

        for page_index, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            all_text_parts.append(text)

            images = []
            for img in page.images:
                images.append(
                    {
                        "name": img.name,
                        "size_bytes": len(img.data),
                        "is_inline": getattr(img, "is_inline", False),
                    }
                )

            links = _page_annotations(page)
            link_like = [a for a in links if a.get("subtype") in {"/Link", "/URI"}]

            page_data: dict[str, Any] = {
                "page_number": page_index + 1,
                "label": page_labels[page_index] if page_index < len(page_labels) else str(page_index + 1),
                "rect": _box_to_dict(page.mediabox),
                "rotation": page.rotation or 0,
                "text_char_count": len(text),
                "text_line_count": len(text.splitlines()),
                "image_count": len(images),
                "link_count": len(link_like),
                "annotation_count": len(links),
                "images": images,
                "annotations": links,
                "text": text,
            }
            result["pages"].append(page_data)

            page_txt_path = output_dir / f"page_{page_index + 1:04d}.txt"
            page_txt_path.write_text(text, encoding="utf-8")

        full_text = "\n\n".join(all_text_parts)
        (output_dir / f"{pdf_path.stem}_full_text.txt").write_text(full_text, encoding="utf-8")
    finally:
        reader.close()

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
        f"Extractor: {result.get('extractor', 'pypdf')}",
        "",
        "=== Document Properties ===",
    ]
    doc = result["document"]
    lines.append(f"Pages: {doc['page_count']}")
    lines.append(f"Encrypted: {doc['is_encrypted']}")
    lines.append(f"Needs password: {doc['needs_pass']}")
    if doc.get("page_layout"):
        lines.append(f"Page layout: {doc['page_layout']}")
    if doc.get("page_mode"):
        lines.append(f"Page mode: {doc['page_mode']}")
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
                f"Images: {page['image_count']}, Links: {page['link_count']}, Annotations: {page['annotation_count']}",
                "",
                page["text"],
            ]
        )

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract PDF content and properties with pypdf.")
    parser.add_argument("pdf", type=Path, help="Path to the input PDF file")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output directory (default: <pdf_stem>_extract_pypdf next to the PDF)",
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

    output_dir = args.output or pdf_path.parent / f"{pdf_path.stem}_extract_pypdf"

    try:
        result = extract_pdf(pdf_path, output_dir, save_embedded=not args.no_embedded)
        summary_path = write_output(result, output_dir, pdf_path.stem, args.format)
    except PdfReadError as exc:
        print(f"Error: could not read PDF: {exc}", file=sys.stderr)
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
