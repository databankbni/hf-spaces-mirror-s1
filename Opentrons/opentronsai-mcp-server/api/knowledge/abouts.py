"""Generate Claude-written <about> blurbs for API doc routing."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Dict, List, Optional

from anthropic import Anthropic

DEFAULT_ABOUT_MODEL = "claude-sonnet-5"
DEFAULT_ABOUT_WORKERS = 8
MAX_SOURCE_CHARS = 12000
MAX_ABOUT_CHARS = 700
ABOUT_PROMPT = """You write routing summaries for an LLM that selects Opentrons Python API docs.

FILE: {relative_path}
TITLE: {title}

<content>
{content}
</content>

Write ONE short paragraph (50-90 words) describing what this documentation file covers.
Focus on concepts that help match user questions: modules, pipettes, labware, robot
types (Flex/OT-2), liquid classes, runtime parameters, commands, versioning, and
API methods or features named in the page.

Rules:
- Use only facts present in the content. Do not invent unsupported version claims.
- If the page states current/latest API or robot software versions, include those exact values.
- No markdown headings, bullet lists, code fences, or quotes of code.
- No "This file..." opener; start with the topic.
- Finish the paragraph completely; do not trail off mid-sentence.
- Return only the paragraph text.
"""


def _truncate_about(text: str, limit: int = MAX_ABOUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    snippet = text[:limit].rstrip()
    sentence_end = max(snippet.rfind(". "), snippet.rfind("? "), snippet.rfind("! "))
    if sentence_end >= int(limit * 0.55):
        return snippet[: sentence_end + 1].strip()
    return snippet.rstrip(",;: ") + "..."


def _clean_about_text(text: str) -> str:
    cleaned = text.strip()
    cleaned = cleaned.strip("\"'")
    cleaned = re.sub(r"^#+\s*", "", cleaned)
    cleaned = re.sub(r"```.*?```", " ", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return _truncate_about(cleaned)


def generate_about_with_claude(
    *,
    client: Anthropic,
    model: str,
    relative_path: str,
    title: str,
    content: str,
) -> str:
    """Ask Claude for a single-paragraph about blurb for one markdown page."""
    truncated = content if len(content) <= MAX_SOURCE_CHARS else content[:MAX_SOURCE_CHARS]
    response = client.messages.create(
        model=model,
        max_tokens=512,
        messages=[
            {
                "role": "user",
                "content": ABOUT_PROMPT.format(
                    relative_path=relative_path,
                    title=title,
                    content=truncated,
                ),
            }
        ],
    )
    text = response.content[0].text if response.content else ""
    about = _clean_about_text(text)
    if not about:
        raise RuntimeError(f"Empty about response for {relative_path}")
    return about


def enrich_abouts_with_claude(
    content_root: Path,
    items: List[Dict[str, str]],
    *,
    api_key: str,
    model: str = DEFAULT_ABOUT_MODEL,
    max_workers: int = DEFAULT_ABOUT_WORKERS,
    progress: Optional[Callable[[str], None]] = None,
) -> List[Dict[str, str]]:
    """
    Replace extract_about fallbacks with Claude-written blurbs.

    On per-file failure, keep the existing about text so sync still succeeds.
    """
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is required to generate Claude abouts. "
            "Set it in .env or pass --no-claude-abouts."
        )

    client = Anthropic(api_key=api_key)
    enriched = [dict(item) for item in items]
    index_by_path = {item["relative_path"]: index for index, item in enumerate(enriched)}

    def _work(item: Dict[str, str]) -> tuple[str, str]:
        relative_path = item["relative_path"]
        path = content_root / relative_path
        content = path.read_text(encoding="utf-8")
        about = generate_about_with_claude(
            client=client,
            model=model,
            relative_path=relative_path,
            title=item.get("title") or relative_path,
            content=content,
        )
        return relative_path, about

    total = len(items)
    completed = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_work, item): item["relative_path"] for item in items}
        for future in as_completed(futures):
            relative_path = futures[future]
            completed += 1
            try:
                path, about = future.result()
                enriched[index_by_path[path]]["about"] = about
                if progress:
                    progress(f"[{completed}/{total}] about: {path}")
            except Exception as exc:
                if progress:
                    progress(f"[{completed}/{total}] about fallback: {relative_path} ({exc})")
    return enriched
