"""Database adapter: Supabase Postgres in production, SQLite for local dev.

Set DATABASE_URL (Supabase → Project Settings → Database → connection string,
use the pooled URI) and every record lives in Supabase — external to the app
containers, so **deploys can never delete data**. Without DATABASE_URL the
store falls back to the local SQLite file (VERSEO_DB), same as before.

The adapter exposes a tiny uniform API used by store.py:
    with get_db() as db:
        rows = db.q("SELECT * FROM t WHERE x=?", (1,))   # list[dict]
        row  = db.one("SELECT ... RETURNING id", (...))  # dict | None
        db.exec("UPDATE ...", (...))
Placeholders are written as `?` and translated to `%s` for Postgres.
Schema is additive only (CREATE TABLE IF NOT EXISTS) — nothing is ever
dropped or truncated by the application.
"""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL") or ""
IS_PG = DATABASE_URL.startswith(("postgres://", "postgresql://"))

SQLITE_PATH = Path(os.environ.get("VERSEO_DB", Path(__file__).parent / "data" / "verseo.db"))

# Dialect helpers used when building the schema.
ID_PK = "BIGSERIAL PRIMARY KEY" if IS_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
TS = "DOUBLE PRECISION" if IS_PG else "REAL"


class DB:
    def __init__(self, conn):
        self._conn = conn

    def _tr(self, sql: str) -> str:
        return sql.replace("?", "%s") if IS_PG else sql

    def q(self, sql: str, params=()) -> list[dict]:
        cur = self._conn.execute(self._tr(sql), params)
        return [dict(r) for r in cur.fetchall()]

    def one(self, sql: str, params=()) -> dict | None:
        cur = self._conn.execute(self._tr(sql), params)
        row = cur.fetchone()
        return dict(row) if row is not None else None

    def exec(self, sql: str, params=()):
        self._conn.execute(self._tr(sql), params)


@contextmanager
def get_db():
    if IS_PG:
        import psycopg
        from psycopg.rows import dict_row

        # prepare_threshold=None disables server-side prepared statements —
        # required because Supabase's pooled connection (PgBouncer, transaction
        # mode) recycles the underlying server connection between requests, and
        # a prepared statement from one request can collide with the next.
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, prepare_threshold=None)
    else:
        SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(SQLITE_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield DB(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def backend_name() -> str:
    return "supabase/postgres" if IS_PG else "sqlite"
