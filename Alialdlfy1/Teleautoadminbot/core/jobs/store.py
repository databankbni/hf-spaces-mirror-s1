"""Compatibility facade over the Phase-15+ durable JobStore.

Legacy callers may keep using ``core.jobs.store.JobStore`` while all new runtime
code uses the canonical ``core.storage.job_store.JobStore`` implementation.
"""
from __future__ import annotations
import sqlite3
from core.storage.job_store import JobStore as _CanonicalJobStore

class JobStore(_CanonicalJobStore):
    def __init__(self, db_path):
        super().__init__(db_path)
        self.db_path = str(self.path)
        self._ensure_legacy_view()

    def _ensure_legacy_view(self):
        with self._conn() as c:
            exists = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone()
            if exists:
                return
            c.execute("""CREATE VIEW IF NOT EXISTS jobs AS
                SELECT id, kind AS type, payload, status, attempts,
                       5 AS max_attempts, available_at AS run_after,
                       worker_id AS locked_by, claimed_at AS locked_at,
                       last_error, created_at, updated_at
                FROM p29_jobs""")

    def enqueue(self, job_type, payload, max_attempts=5, run_after=None, job_id=None, delay=0):
        if run_after is not None:
            import datetime
            if hasattr(run_after, 'timestamp'):
                delay = max(0.0, run_after.timestamp() - __import__('time').time())
            else:
                try: delay = max(0.0, datetime.datetime.fromisoformat(str(run_after).replace('Z','+00:00')).timestamp() - __import__('time').time())
                except Exception: pass
        return super().enqueue(job_type, payload, delay=delay, job_id=job_id)

    def recover_stale(self, timeout_seconds=300, timeout=None):
        return super().recover_expired(float(timeout if timeout is not None else timeout_seconds))
