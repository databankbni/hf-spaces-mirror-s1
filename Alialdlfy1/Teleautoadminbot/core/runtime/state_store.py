from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from threading import RLock


class RuntimeStateStore:
    """Small durable store for section/control-plane state.

    It is intentionally additive and namespaced so legacy tables are untouched.
    """
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._init()

    def _conn(self):
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=FULL")
        c.execute("PRAGMA busy_timeout=30000")
        return c

    def _init(self):
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS p29_runtime_state(
                namespace TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at REAL NOT NULL
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS p29_runtime_schema(
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            )""")
            c.execute("INSERT OR REPLACE INTO p29_runtime_schema(key,value) VALUES('version','1')")

    def get(self, namespace: str, default=None):
        with self._conn() as c:
            row = c.execute("SELECT value FROM p29_runtime_state WHERE namespace=?", (namespace,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except Exception:
            return default

    def set(self, namespace: str, value) -> None:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True)
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO p29_runtime_state(namespace,value,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(namespace) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                (namespace, raw, time.time()),
            )
