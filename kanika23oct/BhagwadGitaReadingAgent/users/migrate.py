# ---------------------------------------------------------------------------
# users/migrate.py
#
# One-time migration: user profiles and bookmarks used to live in the same
# SQLite file as the verse corpus (gita.sqlite). That file gets re-uploaded on
# every deploy, which wiped real users' data. We now keep user data in its own
# users.sqlite. This module copies any existing `users` / `bookmarks` rows out
# of gita.sqlite into users.sqlite the first time we open the new database.
#
# It is idempotent and safe to call on every startup: once users.sqlite has
# the tables (and we've stamped a marker), it does nothing.
# ---------------------------------------------------------------------------

import sqlite3
from pathlib import Path

from config import DB_PATH

# Tables that belong to the user database (not the verse corpus).
_USER_TABLES = ("users", "bookmarks")

_MARKER_TABLE = "_migrated_from_gita"


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def migrate_user_tables(users_db_path) -> None:
    """Copy `users`/`bookmarks` from the legacy gita.sqlite into the new
    users.sqlite, once. Does nothing if already migrated or if there's nothing
    to copy."""
    users_db_path = Path(users_db_path)
    users_db_path.parent.mkdir(parents=True, exist_ok=True)

    dst = sqlite3.connect(str(users_db_path))
    try:
        # Already migrated? Bail out fast.
        if _table_exists(dst, _MARKER_TABLE):
            return

        legacy = Path(DB_PATH)
        copied_any = False
        if legacy.exists():
            src = sqlite3.connect(str(legacy))
            src.row_factory = sqlite3.Row
            try:
                for table in _USER_TABLES:
                    if not _table_exists(src, table):
                        continue
                    rows = src.execute(f"SELECT * FROM {table}").fetchall()
                    if not rows:
                        continue
                    cols = rows[0].keys()
                    # Recreate the table in the destination from the legacy
                    # schema, then copy rows (ignoring any that already exist).
                    create_sql = src.execute(
                        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                        (table,),
                    ).fetchone()[0]
                    dst.execute(create_sql)
                    placeholders = ", ".join("?" for _ in cols)
                    collist = ", ".join(cols)
                    dst.executemany(
                        f"INSERT OR IGNORE INTO {table} ({collist}) "
                        f"VALUES ({placeholders})",
                        [tuple(r[c] for c in cols) for r in rows],
                    )
                    copied_any = True
            finally:
                src.close()

        # Stamp the marker so we never migrate again.
        dst.execute(f"CREATE TABLE IF NOT EXISTS {_MARKER_TABLE} (done INTEGER)")
        dst.execute(f"INSERT INTO {_MARKER_TABLE} (done) VALUES (1)")
        dst.commit()
        if copied_any:
            print("[migrate] copied existing users/bookmarks into users.sqlite")
    finally:
        dst.close()
