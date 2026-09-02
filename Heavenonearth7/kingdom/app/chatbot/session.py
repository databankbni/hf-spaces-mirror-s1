"""
Heaven on Earth CMS Backend — Session Manager

Manages in-memory conversation sessions for the AI chatbot.  Each session
stores LangGraph agent state so multi-turn conversations are coherent within
a 30-minute idle window.

References
----------
- Design § "Data Models" → "ConversationSession"
- Arch §4 "Backend Chatbot Module" → session.py
- Req §5 (Session Manager), acceptance criteria 5.1–5.4
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from langchain_core.messages import BaseMessage
from typing_extensions import TypedDict


# ---------------------------------------------------------------------------
# 5.1  AgentState — LangGraph state TypedDict
# ---------------------------------------------------------------------------


class AgentState(TypedDict):
    """
    Typed state object threaded through every node of the LangGraph agent.

    Fields
    ------
    session_id:
        UUID of the conversation session.
    messages:
        Full LangChain message history for this session.
    language:
        Active language — ``"en"`` (English) or ``"am"`` (Amharic).
    intent:
        Last detected intent: ``"testimony"``, ``"prayer"``,
        ``"partnership"``, ``"qa"``, ``"unknown"``, or ``None`` when
        not yet classified.
    flow:
        Currently active action flow name (``"idle"`` when none is active).
    flow_step:
        Step within the active flow (e.g. ``"collect_name"``).
    collected_fields:
        Slot-filled field values accumulated during the current flow.
    missing_fields:
        Required slots that have not yet been provided by the user.
    retrieved_context:
        RAG results joined into a single string for the LLM prompt.
    api_response:
        Result dict from the last successful form submission, or ``None``.
    error:
        Human-readable error message from the last failed operation, or
        ``None``.
    """

    session_id: str
    messages: list[BaseMessage]
    language: Literal["en", "am"]
    intent: Optional[str]
    flow: Optional[str]
    flow_step: Optional[str]
    collected_fields: dict
    missing_fields: list[str]
    retrieved_context: Optional[str]
    api_response: Optional[dict]
    error: Optional[str]


# ---------------------------------------------------------------------------
# 5.2  ConversationSession — in-memory session record
# ---------------------------------------------------------------------------


@dataclass
class ConversationSession:
    """
    Represents one active chat session.

    Instances are stored in the ``SessionManager._sessions`` dict and
    serialised to/from ``AgentState`` on each agent invocation.

    Fields
    ------
    session_id:
        Unique identifier (UUID v4).
    language:
        Active conversation language (``"en"`` or ``"am"``).
    messages:
        LangChain message history list.
    flow:
        Active action flow (``"idle"`` when none is active).
    flow_step:
        Step within the active flow.
    collected_fields:
        Accumulated slot values for the current flow.
    missing_fields:
        Required slots still outstanding.
    created_at:
        UTC timestamp when the session was first created.
    last_active:
        UTC timestamp of the most recent interaction; used for TTL checks.
    """

    session_id: str
    language: str
    messages: list = field(default_factory=list)
    flow: str = "idle"
    flow_step: str = ""
    collected_fields: dict = field(default_factory=dict)
    missing_fields: list = field(default_factory=list)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_active: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ---------------------------------------------------------------------------
# 5.3  SessionManager
# ---------------------------------------------------------------------------


class SessionManager:
    """
    In-memory session store with TTL-based expiry and stale-session eviction.

    A single ``SessionManager`` instance is created at application startup
    and held on ``app.state.session_manager``.

    Parameters
    ----------
    ttl_minutes:
        Number of minutes of inactivity after which a session is considered
        expired.  Defaults to 30 (matches ``settings.chat_session_ttl_minutes``).
    """

    def __init__(self, ttl_minutes: int = 30) -> None:
        self._ttl_minutes: int = ttl_minutes
        self._sessions: dict[str, ConversationSession] = {}

    # -----------------------------------------------------------------------
    # 5.4  get_or_create
    # -----------------------------------------------------------------------

    def get_or_create(self, session_id: str) -> ConversationSession:
        """
        Return the existing session for *session_id* if it is still active,
        otherwise create and return a fresh default session.

        A session is considered **active** if its ``last_active`` timestamp
        is within ``_ttl_minutes`` of the current UTC time.  Expired sessions
        are replaced by a brand-new session with default values.

        The ``last_active`` timestamp is refreshed on every successful
        retrieval of an existing session.

        Parameters
        ----------
        session_id:
            The session UUID provided by the client.

        Returns
        -------
        ConversationSession
            The existing (refreshed) or newly-created session.
        """
        now = datetime.now(timezone.utc)
        expiry_cutoff = now - timedelta(minutes=self._ttl_minutes)

        existing = self._sessions.get(session_id)

        if existing is not None:
            # Ensure last_active is timezone-aware for comparison
            last_active = existing.last_active
            if last_active.tzinfo is None:
                last_active = last_active.replace(tzinfo=timezone.utc)

            if last_active > expiry_cutoff:
                # Session is still alive — refresh its activity timestamp
                existing.last_active = now
                return existing

        # Session doesn't exist OR has expired — create a fresh one
        session = ConversationSession(
            session_id=session_id,
            language="en",
            messages=[],
            flow="idle",
            flow_step="",
            collected_fields={},
            missing_fields=[],
            created_at=now,
            last_active=now,
        )
        self._sessions[session_id] = session
        return session

    # -----------------------------------------------------------------------
    # 5.5  update
    # -----------------------------------------------------------------------

    def update(self, session_id: str, **kwargs) -> None:
        """
        Patch named fields on the session identified by *session_id*.

        Any keyword argument whose name matches a field on
        ``ConversationSession`` will be applied via ``setattr``.  Unknown
        field names are silently ignored to allow forward-compatible callers.

        ``last_active`` is always updated to ``datetime.now(timezone.utc)``
        after applying the patches, regardless of whether it was included
        in *kwargs*.

        Parameters
        ----------
        session_id:
            The target session UUID.
        **kwargs:
            Field-name → new-value pairs to apply.

        Raises
        ------
        KeyError
            If *session_id* does not exist in the session store.
        """
        session = self._sessions[session_id]

        for key, value in kwargs.items():
            if hasattr(session, key):
                setattr(session, key, value)

        session.last_active = datetime.now(timezone.utc)

    # -----------------------------------------------------------------------
    # 5.6  _evict_stale
    # -----------------------------------------------------------------------

    def _evict_stale(self) -> int:
        """
        Remove sessions whose ``last_active`` timestamp is older than
        ``_ttl_minutes`` ago.

        Intended to be called periodically (e.g. every 5 minutes) by a
        background asyncio task registered in the FastAPI ``lifespan``.

        Returns
        -------
        int
            The number of sessions removed from the store.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=self._ttl_minutes)

        stale_ids: list[str] = []
        for sid, session in self._sessions.items():
            last_active = session.last_active
            if last_active.tzinfo is None:
                last_active = last_active.replace(tzinfo=timezone.utc)
            if last_active <= cutoff:
                stale_ids.append(sid)

        for sid in stale_ids:
            del self._sessions[sid]

        return len(stale_ids)
