from __future__ import annotations
import sqlite3, time, hashlib
from pathlib import Path
from threading import RLock
from typing import Optional

class PublishLedger:
    """
    Durable idempotency ledger for remote publishing.

    Key rule:
      same (target, article_id) => one logical publish operation.
    remote_id is recorded before/after completion when the target supports it.
    """
    def __init__(self, path: str = "data/jobs.sqlite3"):
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
            c.execute("""CREATE TABLE IF NOT EXISTS publish_ledger(
                idempotency_key TEXT PRIMARY KEY,
                target TEXT NOT NULL,
                article_id TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                remote_id TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                attempt_started_at REAL,
                UNIQUE(target, article_id)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_publish_status ON publish_ledger(status)")
            columns = {row[1] for row in c.execute("PRAGMA table_info(publish_ledger)").fetchall()}
            if "attempt_started_at" not in columns:
                c.execute("ALTER TABLE publish_ledger ADD COLUMN attempt_started_at REAL")

    @staticmethod
    def make_key(target: str, article_id: str) -> str:
        raw = f"{target}\0{article_id}".encode()
        return hashlib.sha256(raw).hexdigest()

    def begin(self, target: str, article_id: str, content: str) -> dict:
        key = self.make_key(target, article_id)
        now = time.time()
        content_hash = hashlib.sha256(content.encode("utf-8", "ignore")).hexdigest()
        with self._lock, self._conn() as c:
            row = c.execute("SELECT * FROM publish_ledger WHERE idempotency_key=?", (key,)).fetchone()
            if row:
                item = dict(row)
                if item.get("status") == "publishing":
                    started = float(item.get("attempt_started_at") or item.get("updated_at") or 0)
                    if started and now - started > 300:
                        c.execute("UPDATE publish_ledger SET status='pending', updated_at=?, attempt_started_at=NULL, last_error=? WHERE idempotency_key=?",
                                  (now, "stale publishing lease recovered", key))
                        item = dict(c.execute("SELECT * FROM publish_ledger WHERE idempotency_key=?", (key,)).fetchone())
                return item
            c.execute("""INSERT INTO publish_ledger
                (idempotency_key,target,article_id,content_hash,status,attempts,created_at,updated_at)
                VALUES(?,?,?,?, 'pending',0,?,?)""",
                (key, target, article_id, content_hash, now, now))
            return dict(c.execute("SELECT * FROM publish_ledger WHERE idempotency_key=?", (key,)).fetchone())


    def claim_attempt(self, key: str) -> bool:
        """Atomically claim a publish lease for one idempotency key.

        This closes the final race where two workers both observed ``pending``
        before either called ``mark_attempt``. Only one worker can transition the
        row into ``publishing`` at a time.
        """
        now = time.time()
        with self._lock, self._conn() as c:
            cur = c.execute(
                "UPDATE publish_ledger SET attempts=attempts+1,status='publishing',"
                "updated_at=?,attempt_started_at=? "
                "WHERE idempotency_key=? AND status IN ('pending','failed')",
                (now, now, key),
            )
            return cur.rowcount == 1

    def mark_attempt(self, key: str):
        with self._conn() as c:
            c.execute("""UPDATE publish_ledger SET attempts=attempts+1,status='publishing',
                         updated_at=?,attempt_started_at=? WHERE idempotency_key=?""", (time.time(), time.time(), key))

    def mark_published(self, key: str, remote_id: Optional[str] = None):
        with self._conn() as c:
            c.execute("""UPDATE publish_ledger SET status='published',remote_id=?,
                         updated_at=?,last_error=NULL,attempt_started_at=NULL WHERE idempotency_key=?""",
                      (remote_id, time.time(), key))

    def mark_failed(self, key: str, error: str):
        with self._conn() as c:
            c.execute("""UPDATE publish_ledger SET status='failed',last_error=?,
                         updated_at=?,attempt_started_at=NULL WHERE idempotency_key=?""",
                      (str(error)[:4000], time.time(), key))

    def get(self, key: str):
        with self._conn() as c:
            row = c.execute("SELECT * FROM publish_ledger WHERE idempotency_key=?", (key,)).fetchone()
            return dict(row) if row else None

    def recover_stale(self, timeout: float = 300) -> int:
        cutoff = time.time() - max(1, float(timeout))
        with self._conn() as c:
            cur = c.execute("UPDATE publish_ledger SET status='pending', attempt_started_at=NULL, updated_at=?, last_error=? WHERE status='publishing' AND COALESCE(attempt_started_at, updated_at) < ?",
                            (time.time(), "stale publishing lease recovered", cutoff))
            return cur.rowcount

    def can_attempt(self, target: str, article_id: str) -> bool:
        row = self.get(self.make_key(target, article_id))
        return not row or row["status"] not in {"published", "publishing"}
