from __future__ import annotations

from typing import List, Optional


_START_MARKER = "[TOOL_CALL]"
_END_MARKERS = ["[/TOOL_CALL]", "</minimax:tool_call>"]


def extract_tool_call_blocks(text: str) -> Optional[List[str]]:
    if _START_MARKER not in text:
        return None

    blocks: List[str] = []
    pos = 0

    while pos < len(text):
        start = text.find(_START_MARKER, pos)
        if start == -1:
            break

        content_start = start + len(_START_MARKER)

        earliest_end = -1
        earliest_end_len = 0
        for marker in _END_MARKERS:
            idx = text.find(marker, content_start)
            if idx != -1 and (earliest_end == -1 or idx < earliest_end):
                earliest_end = idx
                earliest_end_len = len(marker)

        if earliest_end != -1:
            blocks.append(text[content_start:earliest_end].strip())
            pos = earliest_end + earliest_end_len
        else:
            invoke_end = text.find("</invoke>", content_start)
            if invoke_end != -1:
                blocks.append(text[content_start:invoke_end + len("</invoke>")].strip())
                pos = invoke_end + len("</invoke>")
            else:
                break

    return blocks if blocks else None
