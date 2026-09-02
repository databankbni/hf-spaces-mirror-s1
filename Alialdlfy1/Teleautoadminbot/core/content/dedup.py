from __future__ import annotations
import sqlite3, time
from pathlib import Path

class DedupStore:
    def __init__(self,path="data/jobs.sqlite3"):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        self._init()
    def _conn(self):
        c=sqlite3.connect(self.path,timeout=30,isolation_level=None)
        c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA synchronous=FULL")
        return c
    def _init(self):
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS content_dedup(
                fingerprint TEXT PRIMARY KEY, source TEXT NOT NULL, article_id TEXT,
                created_at REAL NOT NULL)""")
    def seen(self,fp): 
        with self._conn() as c: return c.execute("SELECT 1 FROM content_dedup WHERE fingerprint=?",(fp,)).fetchone() is not None
    def remember(self,fp,source,article_id=None):
        with self._conn() as c:
            c.execute("INSERT OR IGNORE INTO content_dedup VALUES(?,?,?,?)",(fp,source,article_id,time.time()))

    def forget(self, fp):
        with self._conn() as c:
            c.execute("DELETE FROM content_dedup WHERE fingerprint=?", (fp,))
