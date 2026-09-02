"""Materialize AI guides and MkDocs API docs from a knowledge corpus."""

from __future__ import annotations

import json
import re
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

import zstandard as zstd

AI_DOCS_SOURCE_PREFIX = "opentrons-ai-server/api/storage/docs/"
API_DOCS_SOURCE_PREFIX = "docs/python-api/docs/"
DEFAULT_API_LEVEL = "2.28"
VERSION_MARKER_NAME = ".knowledge-version"
FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)
FENCED_CODE_RE = re.compile(r"```[\s\S]*?```")
ADMONITION_RE = re.compile(r"^!!!\s*[^\n]*(?:\n[ \t]+[^\n]*)*", re.MULTILINE)
QUESTION_ADMONITION_RE = re.compile(r"^\?\?\?\s*[^\n]*(?:\n[ \t]+[^\n]*)*", re.MULTILINE)
TABBED_BLOCK_RE = re.compile(r'^===\s*"[^"]*"\s*(?:\n[ \t]+[^\n]*)*', re.MULTILINE)
API_VERSION_TABLE_ROW_RE = re.compile(r"\|\s*(2\.\d+)\s*\|\s*([\d.]+)\s*\|")


def _read_jsonl_zst(path: Path) -> List[Dict[str, Any]]:
    decompressor = zstd.ZstdDecompressor()
    with path.open("rb") as raw, decompressor.stream_reader(raw) as reader:
        text = reader.read().decode("utf-8")
    records: List[Dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def _load_manifest_fields(manifest_path: Path) -> Dict[str, Any]:
    """Parse a few scalar fields from manifest.yaml without requiring PyYAML."""
    fields: Dict[str, Any] = {}
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if ":" not in line or line.startswith(" ") or line.startswith("-"):
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key in {"version", "target_opentrons_release", "name"}:
            fields[key] = value
    return fields


def _order_sections(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id = {section["section_id"]: section for section in sections}
    ordered: List[Dict[str, Any]] = []
    seen: set[str] = set()

    def walk(section: Optional[Dict[str, Any]]) -> None:
        while section is not None:
            section_id = section["section_id"]
            if section_id in seen:
                break
            ordered.append(section)
            seen.add(section_id)
            for child_id in section.get("child_section_ids") or []:
                child = by_id.get(child_id)
                if child is not None and child["section_id"] not in seen:
                    walk(child)
            next_id = section.get("next_section_id")
            section = by_id.get(next_id) if next_id else None

    roots = [
        section
        for section in sections
        if section.get("previous_section_id") is None and section.get("parent_section_id") is None
    ]
    if not roots:
        roots = [section for section in sections if section.get("previous_section_id") is None]
    if not roots and sections:
        roots = [sections[0]]

    for root in roots:
        walk(root)

    for section in sections:
        if section["section_id"] not in seen:
            ordered.append(section)
    return ordered


def reconstruct_document_markdown(
    sections: List[Dict[str, Any]],
    *,
    document_title: Optional[str] = None,
) -> str:
    """Rebuild a markdown document from corpus section records."""
    parts: List[str] = []
    for section in _order_sections(sections):
        title = (section.get("title") or "").strip()
        body = (section.get("content_markdown") or section.get("content") or "").strip()
        level = (section.get("metadata") or {}).get("level")
        if level is None:
            level = len(section.get("heading_path") or [1]) or 1
        try:
            level_int = max(1, int(level))
        except (TypeError, ValueError):
            level_int = 1

        # Corpus uses a synthetic "root" section for docs without an H1.
        if title.lower() == "root":
            title = (document_title or "").strip()
            level_int = 1

        if title:
            parts.append(f"{'#' * level_int} {title}")
        if body:
            parts.append(body)
    return "\n\n".join(parts).strip() + "\n"


def apply_doc_templates(markdown: str, *, api_level: str, robot_stack_version: str) -> str:
    """Replace MkDocs template placeholders with values from the knowledge pin."""
    return (
        markdown.replace("{{ apiLevel }}", api_level)
        .replace("{{ robot_stack_version }}", robot_stack_version)
        .replace("{{apiLevel}}", api_level)
        .replace("{{robot_stack_version}}", robot_stack_version)
    )


def _strip_mkdocs_noise(text: str) -> str:
    """Remove code fences, admonitions, and tabbed blocks from markdown."""
    cleaned = FRONTMATTER_RE.sub("", text, count=1)
    cleaned = FENCED_CODE_RE.sub(" ", cleaned)
    # Drop orphan fence markers left by incomplete corpus sections.
    cleaned = re.sub(r"```+\w*", " ", cleaned)
    cleaned = ADMONITION_RE.sub(" ", cleaned)
    cleaned = QUESTION_ADMONITION_RE.sub(" ", cleaned)
    cleaned = TABBED_BLOCK_RE.sub(" ", cleaned)
    return cleaned


def _looks_like_code(text: str) -> bool:
    """Heuristic: skip Python-ish assignment/call blocks in about prose."""
    lowered = text.lower()
    if "```" in text:
        return True
    code_markers = (
        " = protocol.",
        " = pipette.",
        "protocol.load_",
        "pipette.",
        ".load_module(",
        ".load_labware(",
        ".move_labware(",
        "def run(",
        "from opentrons",
        "import ",
    )
    return any(marker in lowered for marker in code_markers)


def _clean_inline_markdown(text: str) -> str:
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    cleaned = re.sub(r"\[([^\]]+)\]\[[^\]]*\]", r"\1", cleaned)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"__([^_]+)__", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{2,}", "\n", cleaned)
    return cleaned.strip()


def _truncate_at_sentence(text: str, limit: int = 500) -> str:
    if len(text) <= limit:
        return text
    snippet = text[:limit].rstrip()
    sentence_end = max(snippet.rfind(". "), snippet.rfind("? "), snippet.rfind("! "))
    if sentence_end >= int(limit * 0.55):
        return snippet[: sentence_end + 1].strip()
    return snippet.rstrip(",;: ") + "..."


def _extract_version_facts(text: str) -> str:
    """Pull latest API/robot software pair from the versioning compatibility table."""
    matches = API_VERSION_TABLE_ROW_RE.findall(text)
    if not matches:
        return ""
    api_version, robot_version = matches[0]
    return (
        f"Latest documented API version is {api_version} "
        f"(introduced in robot software {robot_version})."
    )


def extract_about(text: str, title: str, headings: Iterable[str]) -> str:
    """
    Build a compact about blurb from the current markdown page.

    Strips MkDocs noise (code fences, admonitions, tabs) and prefers prose
    plus section headings so routing stays aligned with the synced corpus.
    """
    parts: List[str] = []
    if title and title.lower() != "root":
        parts.append(f"{title.strip()}.")

    useful_headings = [
        heading.strip()
        for heading in headings
        if heading and heading.strip() and heading.strip().lower() != "root"
    ][:10]
    if useful_headings:
        parts.append("Sections: " + "; ".join(useful_headings) + ".")

    version_facts = _extract_version_facts(text)
    if version_facts:
        parts.append(version_facts)

    body = _strip_mkdocs_noise(text).strip()
    prose_chunks: List[str] = []
    for block in re.split(r"\n\s*\n", body):
        stripped = block.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith(("!!!", "???", "===", "    ", "\t", "|")):
            continue
        cleaned = _clean_inline_markdown(stripped)
        if not cleaned or cleaned.startswith(("```", "!!!")):
            continue
        if all(line.lstrip().startswith(("- ", "* ")) for line in cleaned.splitlines() if line.strip()):
            bullets = [
                line.lstrip()[2:].strip()
                for line in cleaned.splitlines()
                if line.strip().startswith(("- ", "* "))
            ]
            cleaned = "Topics: " + "; ".join(bullets[:8])
        else:
            cleaned = " ".join(cleaned.split())
        if _looks_like_code(cleaned):
            continue
        # Skip near-duplicate of the title line.
        if title and cleaned.lower().rstrip(".") == title.strip().lower():
            continue
        prose_chunks.append(cleaned)
        if len(" ".join(prose_chunks)) >= 320:
            break

    parts.extend(prose_chunks)
    about = " ".join(parts).strip()
    if not about:
        about = f"Documentation page for {title or 'API docs'}."
    return _truncate_at_sentence(about, limit=500)


def _relative_api_path(source_path: str) -> Optional[str]:
    if not source_path.startswith(API_DOCS_SOURCE_PREFIX):
        return None
    if not source_path.endswith(".md"):
        return None
    relative = source_path[len(API_DOCS_SOURCE_PREFIX) :]
    if relative.startswith("img/") or "/img/" in relative:
        return None
    return relative


def _ai_docs_filename(source_path: str) -> Optional[str]:
    if not source_path.startswith(AI_DOCS_SOURCE_PREFIX):
        return None
    relative = source_path[len(AI_DOCS_SOURCE_PREFIX) :]
    if not relative or "/" in relative:
        # Only top-level AI guides are part of the runtime pin.
        return None
    if not relative.endswith(".md"):
        return None
    return relative


def generate_api_docs_struct(
    api_files: List[Dict[str, str]],
    output_path: Path,
    *,
    version: str,
    api_level: str,
    docs_tag: str,
    about_source: str = "extract",
    about_model: str = "",
) -> None:
    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    about_line = f"About source: {about_source}"
    if about_model:
        about_line = f"{about_line} ({about_model})"
    lines = [
        "# Opentrons API Documentation Structure",
        "",
        "This file provides detailed analysis of key files in the Opentrons Python API v2 "
        "documentation for LLM context understanding.",
        "",
        f"Generated on: {generated_at}",
        f"Knowledge corpus: {version}",
        f"Documentation tag: {docs_tag}",
        f"Default apiLevel: {api_level}",
        about_line,
        "",
        "## Overview",
        "",
        "This documentation covers the Opentrons Python API v2, used to write protocols for "
        "Opentrons robots (OT-2 and Flex/OT-3). The API allows users to control pipettes, "
        "modules, labware, and execute automated laboratory protocols.",
        "",
        "Each entry below includes an `<about>` section describing what the file covers. "
        "When selecting relevant docs, use the exact relative paths shown below "
        "(for example `modules/index.md`).",
        "",
        "## File-by-File Analysis",
        "",
    ]

    for index, item in enumerate(api_files, start=1):
        lines.extend(
            [
                f"### {index}. {item['relative_path']}",
                "",
                "<about>",
                item["about"],
                "</about>",
                "",
                "---",
                "",
            ]
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def _prepare_output_dirs(ai_docs_dir: Path, api_docs_content_root: Path, api_docs_path: Path) -> None:
    """Wipe runtime doc trees so only freshly materialized files remain."""
    if ai_docs_dir.exists():
        shutil.rmtree(ai_docs_dir)
    ai_docs_dir.mkdir(parents=True, exist_ok=True)

    if api_docs_path.exists():
        shutil.rmtree(api_docs_path)
    api_docs_content_root.mkdir(parents=True, exist_ok=True)


def materialize_runtime_docs(
    corpus_root: Path,
    runtime_root: Path,
    *,
    version: str,
    force: bool = False,
    api_level: str = DEFAULT_API_LEVEL,
    ai_docs_dirname: str = "docs",
    use_claude_abouts: bool = True,
    about_model: str = "claude-sonnet-5",
    anthropic_api_key: Optional[str] = None,
    about_workers: int = 8,
    progress: Optional[Callable[[str], None]] = None,
) -> Path:
    """
    Expand corpus JSONL into the committed storage layout:

      storage/docs/*.md
      storage/api_docs/docs/v2/**/*.md
      storage/api_docs/api_docs_struct.md
      storage/api_docs/.api-level
      storage/api_docs/.knowledge-version

    By default, `<about>` blurbs are rewritten with Claude against the freshly
    materialized markdown. Pass use_claude_abouts=False for extract-only offline sync.
    """
    api_docs_path = runtime_root / "api_docs"
    marker = api_docs_path / VERSION_MARKER_NAME
    struct_path = api_docs_path / "api_docs_struct.md"
    if marker.is_file() and struct_path.is_file() and not force:
        if marker.read_text(encoding="utf-8").strip() == version:
            return runtime_root

    documents_path = corpus_root / "corpus" / "documents.jsonl.zst"
    sections_path = corpus_root / "corpus" / "sections.jsonl.zst"
    if not documents_path.is_file() or not sections_path.is_file():
        raise RuntimeError(f"Corpus is missing documents/sections under {corpus_root}")

    documents = _read_jsonl_zst(documents_path)
    sections = _read_jsonl_zst(sections_path)
    sections_by_doc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for section in sections:
        sections_by_doc[section["document_id"]].append(section)

    manifest = _load_manifest_fields(corpus_root / "manifest.yaml")
    docs_tag = "mkdocs-from-knowledge"
    for source in (corpus_root / "manifest.yaml").read_text(encoding="utf-8").splitlines():
        if "tag:" in source and "mkdocs-" in source:
            docs_tag = source.split(":", 1)[1].strip().strip("'\"")
            break

    ai_docs_dir = runtime_root / ai_docs_dirname
    api_docs_content_root = api_docs_path / "docs" / "v2"
    _prepare_output_dirs(ai_docs_dir, api_docs_content_root, api_docs_path)

    robot_stack_version = str(manifest.get("target_opentrons_release") or "").lstrip("v") or "9.0.0"
    api_struct_items: List[Dict[str, str]] = []
    ai_count = 0

    for document in sorted(documents, key=lambda item: item.get("source_path") or ""):
        source_path = document.get("source_path") or ""
        doc_sections = sections_by_doc.get(document["document_id"], [])
        markdown = reconstruct_document_markdown(
            doc_sections,
            document_title=document.get("title"),
        )
        if not markdown.strip():
            continue

        ai_name = _ai_docs_filename(source_path)
        if ai_name is not None:
            (ai_docs_dir / ai_name).write_text(markdown, encoding="utf-8")
            ai_count += 1
            continue

        relative = _relative_api_path(source_path)
        if relative is None:
            continue

        markdown = apply_doc_templates(
            markdown,
            api_level=api_level,
            robot_stack_version=robot_stack_version,
        )
        dest = api_docs_content_root / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(markdown, encoding="utf-8")
        title = document.get("title") or relative
        api_struct_items.append(
            {
                "relative_path": relative,
                "title": title,
                "about": extract_about(
                    markdown,
                    title,
                    document.get("headings") or [],
                ),
            }
        )

    if ai_count == 0:
        raise RuntimeError("No AI guide documents were materialized from the corpus")
    if not api_struct_items:
        raise RuntimeError("No Python API documents were materialized from the corpus")

    about_source = "extract"
    used_about_model = ""
    if use_claude_abouts:
        from api.knowledge.abouts import enrich_abouts_with_claude

        if progress:
            progress(f"Generating Claude abouts with {about_model} for {len(api_struct_items)} pages...")
        api_struct_items = enrich_abouts_with_claude(
            api_docs_content_root,
            api_struct_items,
            api_key=anthropic_api_key or "",
            model=about_model,
            max_workers=about_workers,
            progress=progress,
        )
        about_source = "claude"
        used_about_model = about_model

    generate_api_docs_struct(
        api_struct_items,
        struct_path,
        version=manifest.get("version", version),
        api_level=api_level,
        docs_tag=docs_tag,
        about_source=about_source,
        about_model=used_about_model,
    )
    (api_docs_path / ".api-level").write_text(f"{api_level}\n", encoding="utf-8")
    marker.write_text(f"{version}\n", encoding="utf-8")
    return runtime_root
