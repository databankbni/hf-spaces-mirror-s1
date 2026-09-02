"""Helpers to persist retrieval source lists beside merge drafts."""

from __future__ import annotations

import json
from pathlib import Path


def unique_source_names(names: list[str] | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in names or []:
        name = (raw or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def format_sources_text(names: list[str] | None, *, header: str = "") -> str:
    items = [n.strip() for n in (names or []) if (n or "").strip()]
    # Preserve order but keep exact lines (may include para indices).
    lines: list[str] = []
    if header.strip():
        lines.append(header.strip())
        lines.append("")
    if not items:
        lines.append("(none)")
        return "\n".join(lines) + "\n"
    for i, name in enumerate(items, 1):
        lines.append(f"{i}. {name}")
    return "\n".join(lines) + "\n"


def source_names_from_chunks(
    chunks: list[dict] | None,
    *,
    unique: bool = True,
    include_paragraph_index: bool = False,
) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for chunk in chunks or []:
        if not isinstance(chunk, dict):
            continue
        name = (
            chunk.get("source_filename")
            or chunk.get("source_file")
            or chunk.get("doc_id")
            or ""
        )
        name = str(name).strip()
        if not name:
            continue
        if include_paragraph_index:
            idx = chunk.get("paragraph_index")
            if idx is not None and str(idx) != "":
                name = f"{name} [para {idx}]"
        if unique:
            if name in seen:
                continue
            seen.add(name)
        names.append(name)
    return names


def source_names_from_manifest_section(
    manifest_path: str | Path | None,
    section_id: str,
    *,
    unique: bool = True,
    include_paragraph_index: bool = False,
) -> list[str]:
    if not manifest_path:
        return []
    path = Path(manifest_path)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    sections = data.get("sections") or {}
    sec = sections.get(section_id) or sections.get(section_id.upper()) or {}
    if not isinstance(sec, dict):
        return []
    return source_names_from_chunks(
        sec.get("chunks_used") or [],
        unique=unique,
        include_paragraph_index=include_paragraph_index,
    )


def write_sources_file(
    path: Path,
    names: list[str] | None,
    *,
    header: str = "",
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_sources_text(names, header=header), encoding="utf-8")
    return path
