"""
Tests for SessionManager (Properties 5, 6, 7 — Req §5.1–5.4).
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import given, settings as h_settings
from hypothesis import strategies as st

from app.chatbot.session import SessionManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fresh_manager(ttl_minutes: int = 30) -> SessionManager:
    return SessionManager(ttl_minutes=ttl_minutes)


def new_uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

def test_new_session_defaults():
    sm = fresh_manager()
    sid = new_uuid()
    session = sm.get_or_create(sid)
    assert session.language == "en"
    assert session.flow == "idle"
    assert session.collected_fields == {}
    assert session.missing_fields == []
    assert session.messages == []


def test_same_session_returned():
    sm = fresh_manager()
    sid = new_uuid()
    s1 = sm.get_or_create(sid)
    s2 = sm.get_or_create(sid)
    assert s1 is s2


def test_expired_session_returns_fresh():
    sm = fresh_manager(ttl_minutes=1)
    sid = new_uuid()
    session = sm.get_or_create(sid)
    # Manually age the session
    session.last_active = datetime.now(timezone.utc) - timedelta(minutes=2)
    new_session = sm.get_or_create(sid)
    assert new_session.flow == "idle"
    assert new_session.collected_fields == {}


def test_evict_stale_removes_expired():
    sm = fresh_manager(ttl_minutes=1)
    sid1 = new_uuid()
    sid2 = new_uuid()
    s1 = sm.get_or_create(sid1)
    s2 = sm.get_or_create(sid2)
    # Age s1
    s1.last_active = datetime.now(timezone.utc) - timedelta(minutes=2)
    evicted = sm._evict_stale()
    assert evicted == 1
    assert sid1 not in sm._sessions
    assert sid2 in sm._sessions


def test_evict_returns_zero_when_none_stale():
    sm = fresh_manager()
    sm.get_or_create(new_uuid())
    assert sm._evict_stale() == 0


def test_update_patches_fields():
    sm = fresh_manager()
    sid = new_uuid()
    sm.get_or_create(sid)
    sm.update(sid, language="am", flow="testimony")
    session = sm._sessions[sid]
    assert session.language == "am"
    assert session.flow == "testimony"


def test_session_isolation():
    sm = fresh_manager()
    sid_a = new_uuid()
    sid_b = new_uuid()
    sm.get_or_create(sid_a)
    sm.get_or_create(sid_b)
    sm.update(sid_a, language="am", collected_fields={"name": "Abel"})
    session_b = sm._sessions[sid_b]
    assert session_b.language == "en"
    assert session_b.collected_fields == {}


# ---------------------------------------------------------------------------
# Property-based tests
# ---------------------------------------------------------------------------

@given(st.uuids())
@h_settings(max_examples=100)
def test_new_uuid_gets_default_state(uid):
    """Any new UUID → fresh session with defaults (Property 5)."""
    sm = fresh_manager()
    session = sm.get_or_create(str(uid))
    assert session.language == "en"
    assert session.flow == "idle"
    assert session.collected_fields == {}


@given(st.uuids(), st.uuids())
@h_settings(max_examples=100)
def test_session_isolation_property(uid_a, uid_b):
    """Mutations to A don't affect B (Property 6)."""
    if uid_a == uid_b:
        return  # skip same UUID
    sm = fresh_manager()
    sm.get_or_create(str(uid_a))
    sm.get_or_create(str(uid_b))
    sm.update(str(uid_a), language="am", flow="testimony")
    b = sm._sessions[str(uid_b)]
    assert b.language == "en"
    assert b.flow == "idle"
