"""
Tests for intent router node (Property 10 — Req §7.2, §8.3–8.4).
"""
import pytest
from unittest.mock import MagicMock, patch
from hypothesis import given, settings as h_settings
from hypothesis import strategies as st
from langchain_core.messages import HumanMessage

from app.chatbot.nodes.router import intent_router_node
from app.chatbot.session import AgentState


VALID_INTENTS = {"testimony", "prayer", "partnership", "qa", "unknown"}


def make_state(message: str, flow: str = "idle", **overrides) -> AgentState:
    base: AgentState = {
        "session_id": "test",
        "messages": [HumanMessage(content=message)],
        "language": "en",
        "intent": None,
        "flow": flow,
        "flow_step": "",
        "collected_fields": {},
        "missing_fields": [],
        "retrieved_context": None,
        "api_response": None,
        "error": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Unit tests — in-flow preservation
# ---------------------------------------------------------------------------

def test_in_flow_non_exit_preserves_flow():
    """Message without exit keywords while in testimony flow → intent stays testimony."""
    state = make_state("My name is Abel", flow="testimony")
    result = intent_router_node(state)
    assert result["intent"] == "testimony"


def test_exit_keyword_cancel_resets_flow():
    state = make_state("cancel", flow="testimony")
    result = intent_router_node(state)
    assert result["flow"] == "idle"


def test_exit_keyword_stop():
    state = make_state("please stop", flow="prayer")
    result = intent_router_node(state)
    assert result["flow"] == "idle"


def test_exit_keyword_quit():
    state = make_state("quit", flow="partnership")
    result = intent_router_node(state)
    assert result["flow"] == "idle"


# ---------------------------------------------------------------------------
# Unit tests — Groq classification (mocked)
# ---------------------------------------------------------------------------

def _mock_groq(intent: str):
    mock_response = MagicMock()
    mock_response.content = intent
    mock_llm = MagicMock()
    mock_llm.invoke = MagicMock(return_value=mock_response)
    return mock_llm


@patch("app.chatbot.nodes.router.ChatGroq")
def test_testimony_keyword_classified(mock_groq_class):
    mock_groq_class.return_value = _mock_groq("testimony")
    state = make_state("I want to share my testimony")
    result = intent_router_node(state)
    assert result["intent"] == "testimony"


@patch("app.chatbot.nodes.router.ChatGroq")
def test_unknown_message_classified(mock_groq_class):
    mock_groq_class.return_value = _mock_groq("unknown")
    state = make_state("what is 2+2")
    result = intent_router_node(state)
    assert result["intent"] == "unknown"


@patch("app.chatbot.nodes.router.ChatGroq")
def test_invalid_groq_response_defaults_unknown(mock_groq_class):
    mock_groq_class.return_value = _mock_groq("INVALID_VALUE")
    state = make_state("some random message")
    result = intent_router_node(state)
    assert result["intent"] == "unknown"


# ---------------------------------------------------------------------------
# Property-based tests
# ---------------------------------------------------------------------------

@given(st.text(min_size=1, max_size=200))
@h_settings(max_examples=100)
@patch("app.chatbot.nodes.router.ChatGroq")
def test_intent_always_valid(mock_groq_class, text):
    """intent_router_node always returns a valid intent value (Property 10)."""
    mock_groq_class.return_value = _mock_groq("unknown")
    state = make_state(text)
    result = intent_router_node(state)
    assert result["intent"] in VALID_INTENTS
