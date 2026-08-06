# ---------------------------------------------------------------------------
# users/bookmarks.py — Phase C2.
#
# Remembers where each user (by email) left off, so the next session can
# resume from the exact next verse. Stored in users.sqlite (separate from the
# verse corpus) so a deploy never erases reading positions.
#
#   email          TEXT PRIMARY KEY
#   last_verse_id  TEXT      the verse to resume FROM
#   updated_at     TEXT
#
# A brand-new user has no row → load_position returns the first verse.
# ---------------------------------------------------------------------------

import sqlite3
from datetime import datetime, timezone

from config import FIRST_VERSE_ID, USERS_DB_PATH
from users.migrate import migrate_user_tables

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bookmarks (
    email         TEXT PRIMARY KEY,
    last_verse_id TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BookmarkStore:
    """Per-user resume position, keyed by email."""

    def __init__(self, db_path=USERS_DB_PATH, default_verse_id: str = FIRST_VERSE_ID):
        migrate_user_tables(db_path)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._default_verse_id = default_verse_id

    def load_position(self, email: str) -> str:
        """Return the verse_id this user should resume from. New users get
        the configured default (first verse of the book)."""
        row = self._conn.execute(
            "SELECT last_verse_id FROM bookmarks WHERE email = ?",
            (email.strip().lower(),),
        ).fetchone()
        return row["last_verse_id"] if row else self._default_verse_id

    def save_position(self, email: str, verse_id: str) -> None:
        """Upsert the user's resume position."""
        self._conn.execute(
            """
            INSERT INTO bookmarks (email, last_verse_id, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                last_verse_id = excluded.last_verse_id,
                updated_at = excluded.updated_at
            """,
            (email.strip().lower(), verse_id, _now()),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
