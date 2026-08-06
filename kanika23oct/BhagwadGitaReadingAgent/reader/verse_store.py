# ---------------------------------------------------------------------------
# reader/verse_store.py — Phase B1.
#
# Read-only API over the SQLite `verses` table. This is the source of truth
# for ordered traversal of the book. No LLM, no embeddings — just indexed
# lookups by verse_id and by (chapter, verse) order.
# ---------------------------------------------------------------------------

import sqlite3
from dataclasses import dataclass

from config import DB_PATH, FIRST_VERSE_ID


@dataclass(frozen=True)
class Verse:
    verse_id: str
    chapter: int
    verse: int
    title: str
    sanskrit: str
    english: str
    hindi: str
    sa_seconds: float | None
    en_seconds: float | None
    hi_seconds: float | None = None

    @property
    def total_seconds(self) -> float:
        """Combined Sanskrit + English playback time. 0 if not yet built."""
        return (self.sa_seconds or 0.0) + (self.en_seconds or 0.0)

    @property
    def ref(self) -> str:
        """Human-friendly reference, e.g. 'BG 2.47'."""
        return f"BG {self.chapter}.{self.verse}"


def _row_to_verse(row: sqlite3.Row) -> Verse:
    keys = row.keys()
    return Verse(
        verse_id=row["verse_id"],
        chapter=row["chapter"],
        verse=row["verse"],
        title=row["title"] or "",
        sanskrit=row["sanskrit"],
        english=row["english"],
        hindi=row["hindi"] or "",
        sa_seconds=row["sa_seconds"],
        en_seconds=row["en_seconds"],
        hi_seconds=row["hi_seconds"] if "hi_seconds" in keys else None,
    )


class VerseStore:
    """Ordered, read-only access to the Gita verses in SQLite."""

    def __init__(self, db_path=DB_PATH):
        # check_same_thread=False so Gradio worker threads can share one
        # store instance for read-only queries.
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    def get_verse(self, verse_id: str) -> Verse | None:
        row = self._conn.execute(
            "SELECT * FROM verses WHERE verse_id = ?", (verse_id,)
        ).fetchone()
        return _row_to_verse(row) if row else None

    def get_by_chapter_verse(self, chapter: int, verse: int) -> Verse | None:
        row = self._conn.execute(
            "SELECT * FROM verses WHERE chapter = ? AND verse = ?",
            (chapter, verse),
        ).fetchone()
        return _row_to_verse(row) if row else None

    def first_verse(self) -> Verse:
        row = self._conn.execute(
            "SELECT * FROM verses ORDER BY chapter, verse LIMIT 1"
        ).fetchone()
        if row is None:
            raise RuntimeError(
                "No verses in the database. Run ingestion.build_corpus first."
            )
        return _row_to_verse(row)

    def first_verse_id(self) -> str:
        try:
            return self.first_verse().verse_id
        except RuntimeError:
            return FIRST_VERSE_ID

    def next_verse_after(self, verse_id: str) -> Verse | None:
        """The verse immediately after `verse_id` in reading order, or None
        if `verse_id` is the last verse of the book."""
        current = self.get_verse(verse_id)
        if current is None:
            return None
        row = self._conn.execute(
            """
            SELECT * FROM verses
            WHERE chapter > ? OR (chapter = ? AND verse > ?)
            ORDER BY chapter, verse
            LIMIT 1
            """,
            (current.chapter, current.chapter, current.verse),
        ).fetchone()
        return _row_to_verse(row) if row else None

    def verse_ids_up_to(self, verse_id: str) -> list[str]:
        """Every verse_id from the start of the book up to and INCLUDING
        `verse_id`, in reading order. Used to ground the sage in only what the
        seeker has heard so far. Returns [] if `verse_id` is unknown."""
        current = self.get_verse(verse_id)
        if current is None:
            return []
        rows = self._conn.execute(
            """
            SELECT verse_id FROM verses
            WHERE chapter < ? OR (chapter = ? AND verse <= ?)
            ORDER BY chapter, verse
            """,
            (current.chapter, current.chapter, current.verse),
        ).fetchall()
        return [r["verse_id"] for r in rows]

    def close(self) -> None:
        self._conn.close()
