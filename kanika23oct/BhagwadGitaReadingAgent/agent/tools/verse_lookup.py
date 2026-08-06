# ---------------------------------------------------------------------------
# agent/tools/verse_lookup.py — Phase E1.
#
# smolagents tool: fetch a specific verse by chapter + verse number and
# return its Sanskrit shloka and English translation. Useful when the user
# asks "read me chapter 2 verse 47" or "what is BG 4.7".
# ---------------------------------------------------------------------------

from typing import Any

from smolagents import Tool

from reader.verse_store import VerseStore


class VerseLookupTool(Tool):
    name = "verse_lookup"
    description = (
        "Look up one specific Bhagavad Gita verse by its chapter and verse "
        "number. Returns the Sanskrit shloka and the English translation. "
        "Use this when the user names a chapter and verse (e.g. 'chapter 2 "
        "verse 47' or 'BG 4.7')."
    )
    inputs: dict[str, dict[str, Any]] = {
        "chapter": {
            "type": "integer",
            "description": "Chapter number, 1-18.",
        },
        "verse": {
            "type": "integer",
            "description": "Verse number within the chapter.",
        },
    }
    output_type = "string"

    def __init__(self, store: VerseStore) -> None:
        super().__init__()
        self._store = store

    def forward(self, chapter: int, verse: int) -> str:
        v = self._store.get_by_chapter_verse(int(chapter), int(verse))
        if v is None:
            return f"error: no verse found for chapter {chapter}, verse {verse}"
        return (
            f"{v.ref} ({v.title})\n\n"
            f"Sanskrit:\n{v.sanskrit}\n\n"
            f"English:\n{v.english}"
        )
