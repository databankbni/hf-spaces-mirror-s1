"""In-memory, session-based conversation memory with TTL eviction."""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from threading import RLock

logger = logging.getLogger(__name__)


class ConversationMemory:
    """Store recent conversation turns per session.

    Sessions expire after `ttl_seconds` of inactivity and only the last
    `max_turns` exchanges are kept, so memory stays bounded on a free-tier Space.
    """

    def __init__(
        self,
        max_turns: int = 6,
        ttl_seconds: int = 1800,
        max_sessions: int = 500,
    ) -> None:
        self.max_turns = max_turns
        self.ttl_seconds = ttl_seconds
        self.max_sessions = max_sessions
        self._lock = RLock()
        # session_id -> (last_active_ts, [(role, content), ...])
        self._sessions: OrderedDict[str, tuple[float, list[tuple[str, str]]]] = OrderedDict()

    def get_history(self, session_id: str) -> list[tuple[str, str]]:
        """Return (role, content) tuples for the session, oldest first."""
        with self._lock:
            self._purge_expired()
            entry = self._sessions.get(session_id)
            if entry is None:
                return []
            self._sessions.move_to_end(session_id)
            return list(entry[1])

    def append_exchange(self, session_id: str, user_message: str, assistant_message: str) -> None:
        """Record one user/assistant exchange for the session."""
        with self._lock:
            self._purge_expired()
            _, messages = self._sessions.get(session_id, (0.0, []))
            messages.append(("user", user_message))
            messages.append(("assistant", assistant_message))

            # Keep only the last `max_turns` exchanges (2 messages per turn).
            max_messages = self.max_turns * 2
            if len(messages) > max_messages:
                messages = messages[-max_messages:]

            self._sessions[session_id] = (time.time(), messages)
            self._sessions.move_to_end(session_id)

            while len(self._sessions) > self.max_sessions:
                evicted, _ = self._sessions.popitem(last=False)
                logger.info("Evicted oldest session %s (capacity reached).", evicted)

    def clear(self, session_id: str) -> bool:
        """Delete a session. Returns True if it existed."""
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def active_sessions(self) -> int:
        with self._lock:
            self._purge_expired()
            return len(self._sessions)

    def _purge_expired(self) -> None:
        now = time.time()
        expired = [
            session_id
            for session_id, (last_active, _) in self._sessions.items()
            if now - last_active > self.ttl_seconds
        ]
        for session_id in expired:
            del self._sessions[session_id]
