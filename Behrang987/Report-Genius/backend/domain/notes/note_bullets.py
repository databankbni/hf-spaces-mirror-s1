"""Normalize messy inspector notes into bullet lines."""

from __future__ import annotations

import re


def explode_note_lines(bullets: list[str]) -> list[str]:
    """Split dense note blobs into separate lines (semicolons, pipes, long sentences)."""
    out: list[str] = []
    for raw in bullets:
        text = str(raw or "").strip()
        if not text:
            continue
        if len(text) <= 320 and text.count(";") + text.count("|") == 0:
            out.append(text)
            continue
        chunks = re.split(r"[;\n|]+", text)
        if len(chunks) == 1 and len(text) > 320:
            chunks = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9£])", text)
        for piece in chunks:
            p = piece.strip()
            if len(p) >= 2:
                out.append(p)
    return out


def format_bullets_for_prompt(bullets: list[str], max_chars: int = 3500) -> str:
    """Join bullets for LLM prompts with a character budget."""
    lines = explode_note_lines(bullets)
    parts: list[str] = []
    used = 0
    for line in lines:
        t = re.sub(r"^[-•*]+\s*", "", line).strip()
        if not t:
            continue
        if used + len(t) + 2 > max_chars:
            break
        parts.append(f"- {t}")
        used += len(t) + 2
    return "\n".join(parts) if parts else "(none)"
