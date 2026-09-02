from __future__ import annotations
import sqlite3, json, time, uuid
from pathlib import Path
from threading import RLock
from typing import Any, Optional

class JobStore:
    """Crash-safe persistent job queue. Claims expire so crashed workers can recover jobs."""
    def __init__(self, path: str = "data/jobs.sqlite3"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._init()

    def _conn(self):
        c=sqlite3.connect(self.path, timeout=30, isolation_level=None)
        c.row_factory=sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=FULL")
        c.execute("PRAGMA busy_timeout=30000")
        return c

    def _init(self):
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS p29_jobs(
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                attempts INTEGER NOT NULL DEFAULT 0,
                available_at REAL NOT NULL,
                claimed_at REAL,
                worker_id TEXT,
                last_error TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_p29_jobs_ready ON p29_jobs(status,available_at)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_p29_jobs_claim ON p29_jobs(status,claimed_at)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_p29_jobs_dead ON p29_jobs(status,updated_at)")
            c.execute("""CREATE TABLE IF NOT EXISTS p29_schema_meta(
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            )""")
            c.execute(
                "INSERT OR REPLACE INTO p29_schema_meta(key,value) VALUES('job_store_version','2')"
            )
            # Compatibility migration from the two pre-phase-15 `jobs` schemas.
            self._migrate_legacy_jobs(c)

    def enqueue(self, kind: str, payload: Any, delay: float = 0, job_id: Optional[str]=None) -> str:
        jid=job_id or str(uuid.uuid4()); now=time.time()
        with self._lock, self._conn() as c:
            c.execute("""INSERT OR IGNORE INTO p29_jobs
                (id,kind,payload,status,available_at,created_at,updated_at)
                VALUES(?,?,?,'queued',?,?,?)""",
                (jid,kind,json.dumps(payload,ensure_ascii=False),now+max(0,delay),now,now))
        return jid

    def recover_expired(self, timeout: float = 300) -> int:
        cutoff=time.time()-timeout
        with self._conn() as c:
            cur=c.execute("""UPDATE p29_jobs SET status='queued',claimed_at=NULL,worker_id=NULL,
                             updated_at=?,last_error=COALESCE(last_error,'worker lease expired')
                             WHERE status='running' AND claimed_at<?""",(time.time(),cutoff))
            return cur.rowcount

    def claim(self, worker_id: str) -> Optional[dict]:
        now=time.time()
        with self._lock, self._conn() as c:
            row=c.execute("""SELECT * FROM p29_jobs WHERE status='queued' AND available_at<=?
                             ORDER BY created_at LIMIT 1""",(now,)).fetchone()
            if not row: return None
            cur=c.execute("""UPDATE p29_jobs SET status='running',claimed_at=?,worker_id=?,
                             attempts=attempts+1,updated_at=? WHERE id=? AND status='queued'""",
                          (now,worker_id,now,row["id"]))
            if cur.rowcount != 1: return None
            d=dict(row); d["attempts"]=d["attempts"]+1
            d["payload"]=json.loads(d["payload"]); return d

    def heartbeat(self, job_id: str, worker_id: str) -> bool:
        with self._conn() as c:
            cur = c.execute(
                "UPDATE p29_jobs SET claimed_at=?,updated_at=? WHERE id=? AND status='running' AND worker_id=?",
                (time.time(), time.time(), job_id, worker_id),
            )
            return cur.rowcount == 1

    def complete(self, job_id: str, worker_id: str | None = None):
        with self._conn() as c:
            if worker_id is None:
                c.execute("UPDATE p29_jobs SET status='done',updated_at=?,claimed_at=NULL,worker_id=NULL WHERE id=?",(time.time(),job_id))
            else:
                c.execute("UPDATE p29_jobs SET status='done',updated_at=?,claimed_at=NULL,worker_id=NULL WHERE id=? AND worker_id=?",(time.time(),job_id,worker_id))

    def fail(self, job_id: str, error: str, retry_delay: float = 60, max_attempts: int = 5):
        now=time.time()
        with self._conn() as c:
            row=c.execute("SELECT attempts FROM p29_jobs WHERE id=?",(job_id,)).fetchone()
            if not row:return
            status='dead' if row["attempts"]>=max_attempts else 'queued'
            c.execute("""UPDATE p29_jobs SET status=?,available_at=?,last_error=?,updated_at=?,
                         claimed_at=NULL,worker_id=NULL WHERE id=?""",
                      (status, now+(retry_delay if status=='queued' else 0), str(error)[:4000], now, job_id))


    def _migrate_legacy_jobs(self, c):
        exists = c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'"
        ).fetchone()
        if not exists:
            return
        columns = {row[1] for row in c.execute("PRAGMA table_info(jobs)").fetchall()}
        try:
            if {"id", "kind", "available_at", "claimed_at", "worker_id"} <= columns:
                rows = c.execute(
                    "SELECT id,kind,payload,status,attempts,available_at,claimed_at,worker_id,last_error,created_at,updated_at FROM jobs"
                ).fetchall()
                for r in rows:
                    c.execute(
                        """INSERT OR IGNORE INTO p29_jobs
                        (id,kind,payload,status,attempts,available_at,claimed_at,worker_id,last_error,created_at,updated_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?)""", tuple(r)
                    )
            elif {"id", "type", "run_after", "locked_at", "locked_by"} <= columns:
                rows = c.execute(
                    "SELECT id,type,payload,status,attempts,run_after,locked_at,locked_by,last_error,created_at,updated_at FROM jobs"
                ).fetchall()
                import datetime
                def ts(v):
                    if isinstance(v, (int, float)):
                        return float(v)
                    try:
                        return datetime.datetime.fromisoformat(str(v).replace("Z","+00:00")).timestamp()
                    except Exception:
                        return time.time()
                for r in rows:
                    c.execute(
                        """INSERT OR IGNORE INTO p29_jobs
                        (id,kind,payload,status,attempts,available_at,claimed_at,worker_id,last_error,created_at,updated_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (r[0], r[1], r[2], r[3], r[4], ts(r[5]), ts(r[6]) if r[6] else None,
                         r[7], r[8], ts(r[9]), ts(r[10]))
                    )
        except Exception:
            # Migration is additive; a malformed legacy row must not prevent startup.
            # The health monitor will expose any runtime data issue separately.
            pass


    def list_jobs(self, status: str | None = None, limit: int = 50) -> list[dict]:
        limit = max(1, min(500, int(limit)))
        with self._conn() as c:
            if status:
                rows = c.execute(
                    "SELECT * FROM p29_jobs WHERE status=? ORDER BY updated_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM p29_jobs ORDER BY updated_at DESC LIMIT ?", (limit,)
                ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            try:
                item["payload"] = json.loads(item["payload"])
            except Exception:
                pass
            out.append(item)
        return out

    def requeue_dead(self, job_id: str, delay: float = 0) -> bool:
        now = time.time()
        with self._conn() as c:
            cur = c.execute(
                "UPDATE p29_jobs SET status='queued', available_at=?, claimed_at=NULL, worker_id=NULL, "
                "last_error=NULL, updated_at=? WHERE id=? AND status='dead'",
                (now + max(0, float(delay)), now, job_id),
            )
            return cur.rowcount == 1

    def get_stats(self) -> dict:
        with self._conn() as c:
            rows=c.execute("SELECT status,COUNT(*) AS n FROM p29_jobs GROUP BY status").fetchall()
        out={"queued":0,"running":0,"done":0,"dead":0}
        out.update({r["status"]: int(r["n"]) for r in rows})
        return out

    def get(self, job_id: str):
        with self._conn() as c:
            row=c.execute("SELECT * FROM p29_jobs WHERE id=?",(job_id,)).fetchone()
            return dict(row) if row else None
