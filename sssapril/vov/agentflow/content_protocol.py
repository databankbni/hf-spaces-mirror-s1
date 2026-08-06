from __future__ import annotations

import re

REFS_BLOCK_NAME = "REFS"
TRACE_BLOCK_NAME = "TRACE"

# LLM 文本格式工具调用标记（如 [TOOL_CALL]...[/TOOL_CALL]）
_TOOL_CALL_BLOCK_RE = re.compile(r"\[TOOL_CALL\]\s*.*?\s*\[/TOOL_CALL\]", re.DOTALL | re.IGNORECASE)
_TOOL_CALL_LINE_RE = re.compile(r"^\[Tool Call\]\s+.*$", re.MULTILINE)
_TOOL_RESULT_LINE_RE = re.compile(r"^\[Tool Result\]\s+.*$", re.MULTILINE)
_TOOL_ERROR_LINE_RE = re.compile(r"^\[Tool Error\]\s+.*$", re.MULTILINE)
# agentflow stream_process 在 LLM 只调工具不产文本时, 会用 on_token 推送
# "\n<tool_call_pos />\n" 作为位置标记. 这些标记不应被持久化到 DB packet content.
_TOOL_CALL_POS_RE = re.compile(r"<tool_call_pos\s*/>", re.IGNORECASE)


def _compiled_block_pattern(block_name: str, *, allow_unclosed_tail: bool) -> re.Pattern[str]:
    normalized = re.escape(str(block_name or "").strip().upper())
    if allow_unclosed_tail:
        return re.compile(
            rf"(?is)(?:^|\n)\s*\[\[{normalized}\]\]\s*[\r\n]?[\s\S]*?(?:[\r\n]\s*\[\[/{normalized}\]\]|$)"
        )
    return re.compile(rf"(?is)(?:^|\n)\s*\[\[{normalized}\]\]\s*[\r\n]?[\s\S]*?[\r\n]\s*\[\[/{normalized}\]\]")


TRACE_BLOCK_RE = _compiled_block_pattern(TRACE_BLOCK_NAME, allow_unclosed_tail=True)


def strip_protocol_blocks(text: str, *, block_names: list[str] | tuple[str, ...]) -> str:
    normalized = str(text or "")
    if not normalized or not block_names:
        return normalized

    filtered = normalized
    for block_name in block_names:
        pattern = _compiled_block_pattern(block_name, allow_unclosed_tail=True)
        filtered = pattern.sub("", filtered)

    # Collapse only repeated blank lines introduced by block stripping.
    filtered = re.sub(r"\n{3,}", "\n\n", filtered)
    return filtered.strip()


def strip_hidden_trace_blocks(text: str) -> str:
    return strip_protocol_blocks(str(text or ""), block_names=[TRACE_BLOCK_NAME])


def strip_tool_call_markers(text: str) -> str:
    """Strip LLM text-format tool call markers from content.

    Removes patterns like:
    - [TOOL_CALL] {tool => "name", args => {...}} [/TOOL_CALL]
    - [Tool Call] name arguments=...
    - [Tool Result] ...
    - [Tool Error] ...
    - <tool_call_pos />
    """
    result = str(text or "")
    result = _TOOL_CALL_BLOCK_RE.sub("", result)
    result = _TOOL_CALL_LINE_RE.sub("", result)
    result = _TOOL_RESULT_LINE_RE.sub("", result)
    result = _TOOL_ERROR_LINE_RE.sub("", result)
    result = _TOOL_CALL_POS_RE.sub("", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def contains_protocol_block(text: str, block_name: str) -> bool:
    if not str(text or "").strip():
        return False
    pattern = _compiled_block_pattern(block_name, allow_unclosed_tail=False)
    return pattern.search(str(text)) is not None


__all__ = [
    "REFS_BLOCK_NAME",
    "TRACE_BLOCK_NAME",
    "contains_protocol_block",
    "strip_hidden_trace_blocks",
    "strip_protocol_blocks",
    "strip_tool_call_markers",
]
