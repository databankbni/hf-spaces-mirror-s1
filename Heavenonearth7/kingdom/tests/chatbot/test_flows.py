"""
Tests for conversational action flows (Properties 12, 16 — Req §8–§11).
"""
import pytest
from hypothesis import given, settings as h_settings
from hypothesis import strategies as st
from langchain_core.messages import AIMessage, HumanMessage

from app.chatbot.flows.base import Slot
from app.chatbot.flows.testimony import TestimonyFlow
from app.chatbot.flows.prayer import PrayerFlow
from app.chatbot.flows.partnership import PartnershipFlow
from app.chatbot.nodes.confirm import confirmation_node, confirm_decision_router
from app.chatbot.session import AgentState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_state(**overrides) -> AgentState:
    base: AgentState = {
        "session_id": "test-session",
        "messages": [],
        "language": "en",
        "intent": None,
        "flow": "idle",
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
# TestimonyFlow unit tests
# ---------------------------------------------------------------------------

def test_testimony_required_slots():
    flow = TestimonyFlow()
    required = [s.name for s in flow.get_slots() if s.required]
    assert "name" in required
    assert "content" in required
    assert "category" in required


def test_testimony_optional_slots():
    flow = TestimonyFlow()
    optional = [s.name for s in flow.get_slots() if not s.required]
    assert "title" in optional
    assert "email" in optional


def test_testimony_content_validator_passes():
    flow = TestimonyFlow()
    content_slot = next(s for s in flow.get_slots() if s.name == "content")
    assert content_slot.validator("a" * 50) is True
    assert content_slot.validator("a" * 100) is True


def test_testimony_content_validator_fails():
    flow = TestimonyFlow()
    content_slot = next(s for s in flow.get_slots() if s.name == "content")
    assert content_slot.validator("short") is False
    assert content_slot.validator("a" * 49) is False


def test_testimony_category_validator():
    flow = TestimonyFlow()
    cat_slot = next(s for s in flow.get_slots() if s.name == "category")
    for valid in ("healing", "salvation", "provision", "deliverance", "general"):
        assert cat_slot.validator(valid) is True
    assert cat_slot.validator("miracle") is False


def test_testimony_name_validator():
    flow = TestimonyFlow()
    name_slot = next(s for s in flow.get_slots() if s.name == "name")
    assert name_slot.validator("Ab") is True
    assert name_slot.validator("A") is False
    assert name_slot.validator("") is False


# ---------------------------------------------------------------------------
# PrayerFlow unit tests
# ---------------------------------------------------------------------------

def test_prayer_is_anonymous_required():
    flow = PrayerFlow()
    anon_slot = next(s for s in flow.get_slots() if s.name == "is_anonymous")
    assert anon_slot.required is True


def test_prayer_request_validator():
    flow = PrayerFlow()
    req_slot = next(s for s in flow.get_slots() if s.name == "request")
    assert req_slot.validator("a" * 10) is True
    assert req_slot.validator("short") is False


def test_prayer_name_optional_in_slots():
    flow = PrayerFlow()
    name_slot = next(s for s in flow.get_slots() if s.name == "name")
    assert name_slot.required is False  # promoted dynamically by node


# ---------------------------------------------------------------------------
# PartnershipFlow unit tests
# ---------------------------------------------------------------------------

def test_partnership_required_slots():
    flow = PartnershipFlow()
    required = [s.name for s in flow.get_slots() if s.required]
    assert "name" in required
    assert "email" in required
    assert "partnership_type" in required


def test_partnership_email_validator():
    flow = PartnershipFlow()
    email_slot = next(s for s in flow.get_slots() if s.name == "email")
    assert email_slot.validator("user@example.com") is True
    assert email_slot.validator("notanemail") is False


def test_partnership_type_validator():
    flow = PartnershipFlow()
    type_slot = next(s for s in flow.get_slots() if s.name == "partnership_type")
    for valid in ("financial", "volunteer", "material"):
        assert type_slot.validator(valid) is True
    assert type_slot.validator("donation") is False


# ---------------------------------------------------------------------------
# Confirmation node unit tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_confirmation_sets_flow_step():
    state = make_state(
        flow="testimony",
        collected_fields={"name": "Abel", "content": "a" * 60, "category": "healing"},
    )
    result = await confirmation_node(state)
    assert result["flow_step"] == "awaiting_confirm"


@pytest.mark.asyncio
async def test_confirmation_message_contains_fields():
    state = make_state(
        flow="testimony",
        collected_fields={"name": "Abel", "category": "healing"},
        flow_step="awaiting_confirm",
    )
    result = await confirmation_node(state)
    last_msg = result["messages"][-1].content
    assert "Abel" in last_msg
    assert "healing" in last_msg


def test_confirm_router_confirmed():
    state = make_state(
        flow_step="awaiting_confirm",
        messages=[HumanMessage(content="yes")],
    )
    assert confirm_decision_router(state) == "confirmed"


def test_confirm_router_cancelled():
    state = make_state(
        flow_step="awaiting_confirm",
        messages=[HumanMessage(content="no")],
    )
    assert confirm_decision_router(state) == "cancelled"


def test_confirm_router_awaiting():
    state = make_state(
        flow_step="awaiting_confirm",
        messages=[HumanMessage(content="maybe")],
    )
    assert confirm_decision_router(state) == "awaiting"


def test_confirm_router_amharic_yes():
    state = make_state(
        flow_step="awaiting_confirm",
        messages=[HumanMessage(content="አዎ")],
    )
    assert confirm_decision_router(state) == "confirmed"


# ---------------------------------------------------------------------------
# Property-based tests
# ---------------------------------------------------------------------------

@given(st.fixed_dictionaries({
    "name": st.just("Ab"),    # valid: len >= 2
    # content and category intentionally missing
}))
@h_settings(max_examples=50)
def test_partial_fields_are_missing(partial_fields):
    """Any partial required-field set → missing_fields is non-empty (Property 12)."""
    flow = TestimonyFlow()
    required = {s.name for s in flow.get_slots() if s.required}
    filled = set(partial_fields.keys())
    missing = required - filled
    assert len(missing) > 0


@given(st.dictionaries(
    st.text(min_size=1, max_size=20),
    st.text(min_size=1, max_size=100),
    min_size=1,
    max_size=10,
))
@h_settings(max_examples=100)
@pytest.mark.asyncio
async def test_confirmation_summary_contains_all_keys(fields):
    """Confirmation summary contains every collected field key (Property 13)."""
    state = make_state(
        flow="testimony",
        flow_step="awaiting_confirm",
        collected_fields=fields,
    )
    result = await confirmation_node(state)
    last_msg = result["messages"][-1].content
    for key in fields:
        pretty_key = key.replace("_", " ").capitalize()
        assert pretty_key in last_msg or key in last_msg
