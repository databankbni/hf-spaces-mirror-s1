# ---------------------------------------------------------------------------
# agent/tools/jump_to.py — Phase E3.
#
# smolagents tool: let the user jump the reader to a specific verse by
# saying e.g. "jump to chapter 4 verse 7". The tool validates the target
# and records it in a shared "sink" dict; app.py reads that sink right
# after agent.run() and moves the reader there.
#
# v1 caveat: the sink is shared per agent instance. Since v1 is effectively
# single-user (local / personal Space), this is fine. A multi-user version
# would key the pending jump by session.
# ---------------------------------------------------------------------------

from typing import Any

from smolagents import Tool

from reader.verse_store import VerseStore


class JumpToTool(Tool):
    name = "jump_to"
    description = (
        "Move the reader to a specific Bhagavad Gita verse so reading "
        "resumes from there. Use when the user asks to jump/go to a "
        "chapter and verse (e.g. 'jump to chapter 4 verse 7')."
    )
    inputs: dict[str, dict[str, Any]] = {
        "chapter": {
            "type": "integer",
            "description": "Target chapter number, 1-18.",
        },
        "verse": {
            "type": "integer",
            "description": "Target verse number within the chapter.",
        },
    }
    output_type = "string"

    def __init__(self, store: VerseStore, sink: dict) -> None:
        super().__init__()
        self._store = store
        self._sink = sink

    def forward(self, chapter: int, verse: int) -> str:
        v = self._store.get_by_chapter_verse(int(chapter), int(verse))
        if v is None:
            return f"error: no verse found for chapter {chapter}, verse {verse}"
        # Record the requested jump for app.py to apply.
        self._sink["verse_id"] = v.verse_id
        return f"Reader will resume from {v.ref}."
