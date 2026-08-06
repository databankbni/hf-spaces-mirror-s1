# ---------------------------------------------------------------------------
# agent/reflection_store.py — durable cache of the sage's AI reflections.
#
# A reflection (the LLM's 2-3 sentence commentary on a verse) is the same for
# every seeker, so it only needs to be generated ONCE per (verse, language).
# We persist it in its own SQLite database which is mirrored to the durable HF
# dataset (see users/remote_store.py). On a restart the Space pulls this file,
# so a reflection is never regenerated — saving Inference tokens/credits.
# ---------------------------------------------------------------------------

from __future__ import annotations

import sqlite3

from config import REFLECTIONS_DB_PATH


class ReflectionStore:
    """SQLite-backed store for generated reflections, keyed by (verse_id, lang)."""

    def __init__(self, db_path=REFLECTIONS_DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False so Gradio worker threads can share it.
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reflections (
                verse_id   TEXT NOT NULL,
                lang       TEXT NOT NULL,
                text       TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (verse_id, lang)
            )
            """
        )
        self._conn.commit()

    def get(self, verse_id: str, lang: str) -> str | None:
        row = self._conn.execute(
            "SELECT text FROM reflections WHERE verse_id = ? AND lang = ?",
            (verse_id, lang),
        ).fetchone()
        return row[0] if row else None

    def put(self, verse_id: str, lang: str, text: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO reflections (verse_id, lang, text) "
            "VALUES (?, ?, ?)",
            (verse_id, lang, text),
        )
        self._conn.commit()

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM reflections").fetchone()[0]

    def close(self) -> None:
        self._conn.close()
