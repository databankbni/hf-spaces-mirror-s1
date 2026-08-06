"""Session store for the SWMM MCP server.

Each uploaded model gets a session with its own working directory under
/tmp/swmm_sessions. Sessions expire after SESSION_TTL_HOURS (default 6) and
are swept lazily on access. State is process-local: the HF Space runs a
single uvicorn worker, matching the stateful-session conclusion from the
WNTR MCP architecture work (one backend, session-ID state).
"""
from __future__ import annotations

import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

SESSION_ROOT = Path(os.environ.get("SWMM_SESSION_ROOT", "/tmp/swmm_sessions"))
SESSION_TTL_S = float(os.environ.get("SESSION_TTL_HOURS", "6")) * 3600.0
MAX_SESSIONS = int(os.environ.get("MAX_SESSIONS", "40"))


class Session:
    def __init__(self, session_id: str, workdir: Path):
        self.id = session_id
        self.workdir = workdir
        self.created = time.time()
        self.touched = time.time()
        self.data: dict[str, Any] = {}

    def touch(self) -> None:
        self.touched = time.time()


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        SESSION_ROOT.mkdir(parents=True, exist_ok=True)

    def create(self) -> Session:
        with self._lock:
            self._sweep_locked()
            if len(self._sessions) >= MAX_SESSIONS:
                oldest = min(self._sessions.values(), key=lambda s: s.touched)
                self._drop_locked(oldest.id)
            sid = uuid.uuid4().hex[:12]
            workdir = SESSION_ROOT / sid
            workdir.mkdir(parents=True, exist_ok=True)
            session = Session(sid, workdir)
            self._sessions[sid] = session
            return session

    def get(self, session_id: str) -> Session:
        with self._lock:
            self._sweep_locked()
            session = self._sessions.get(str(session_id))
            if session is None:
                raise KeyError(
                    f"Unknown or expired session '{session_id}'. Call upload_model first "
                    f"(sessions expire after {SESSION_TTL_S/3600:.0f} h of inactivity)."
                )
            session.touch()
            return session

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            self._sweep_locked()
            return [
                {
                    "session_id": s.id,
                    "model": s.data.get("filename"),
                    "simulated": bool(s.data.get("results")),
                    "age_minutes": round((time.time() - s.created) / 60.0, 1),
                }
                for s in self._sessions.values()
            ]

    def drop(self, session_id: str) -> bool:
        with self._lock:
            return self._drop_locked(str(session_id))

    # -- internal --
    def _drop_locked(self, session_id: str) -> bool:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        shutil.rmtree(session.workdir, ignore_errors=True)
        return True

    def _sweep_locked(self) -> None:
        now = time.time()
        for sid in [s for s, v in self._sessions.items() if now - v.touched > SESSION_TTL_S]:
            self._drop_locked(sid)


STORE = SessionStore()
