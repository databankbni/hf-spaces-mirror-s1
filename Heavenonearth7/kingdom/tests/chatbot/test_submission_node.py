"""
Tests for submission node (Property 11 — Req §8.4–8.6).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from hypothesis import given, settings as h_settings
from hypothesis import strategies as st
from langchain_core.messages import HumanMessage

from app.chatbot.session import AgentState
from app.schemas.testimonial import TestimonialCreate
from app.schemas.prayer import PrayerRequestCreate
from app.schemas.partnership import PartnershipCreate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_state(**overrides) -> AgentState:
    base: AgentState = {
        "session_id": "test",
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


VALID_TESTIMONY = {
    "name": "Abel Tesfaye",
    "content": "God healed my family from a serious illness. " * 2,
    "category": "healing",
}

VALID_PRAYER = {
    "is_anonymous": "no",
    "name": "Sara",
    "request": "Please pray for my family.",
}

VALID_PARTNERSHIP = {
    "name": "Dawit",
    "email": "dawit@example.com",
    "partnership_type": "volunteer",
    "volunteer_areas": "worship, children ministry",
}


# ---------------------------------------------------------------------------
# Unit tests — successful submissions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_successful_testimony_resets_flow():
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.content = b"{}"
    mock_response.json.return_value = {}

    with patch("app.chatbot.nodes.submit._http_client") as mock_client:
        mock_client.post = AsyncMock(return_value=mock_response)
        from app.chatbot.nodes.submit import submission_node
        state = make_state(flow="testimony", collected_fields=dict(VALID_TESTIMONY))
        result = await submission_node(state)

    assert result["flow"] == "idle"
    assert result["collected_fields"] == {}
    assert result["missing_fields"] == []
    assert result["error"] is None


@pytest.mark.asyncio
async def test_successful_prayer_resets_flow():
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.content = b"{}"
    mock_response.json.return_value = {}

    with patch("app.chatbot.nodes.submit._http_client") as mock_client:
        mock_client.post = AsyncMock(return_value=mock_response)
        from app.chatbot.nodes.submit import submission_node
        state = make_state(flow="prayer", collected_fields=dict(VALID_PRAYER))
        result = await submission_node(state)

    assert result["flow"] == "idle"


@pytest.mark.asyncio
async def test_successful_partnership_resets_flow():
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.content = b"{}"
    mock_response.json.return_value = {}

    with patch("app.chatbot.nodes.submit._http_client") as mock_client:
        mock_client.post = AsyncMock(return_value=mock_response)
        from app.chatbot.nodes.submit import submission_node
        state = make_state(flow="partnership", collected_fields=dict(VALID_PARTNERSHIP))
        result = await submission_node(state)

    assert result["flow"] == "idle"


# ---------------------------------------------------------------------------
# Unit tests — validation failure (no HTTP call)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_invalid_testimony_no_http_call():
    """Content < 50 chars → ValidationError caught, httpx NOT called."""
    invalid = {"name": "Abel", "content": "short", "category": "healing"}

    with patch("app.chatbot.nodes.submit._http_client") as mock_client:
        mock_client.post = AsyncMock()
        from app.chatbot.nodes.submit import submission_node
        state = make_state(flow="testimony", collected_fields=invalid)
        result = await submission_node(state)

    mock_client.post.assert_not_called()
    assert result["error"] is not None
    assert result["flow"] == "testimony"  # not reset on validation error


# ---------------------------------------------------------------------------
# Unit tests — non-2xx response
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_non_2xx_response_no_exception():
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"
    mock_response.content = b"error"

    with patch("app.chatbot.nodes.submit._http_client") as mock_client:
        mock_client.post = AsyncMock(return_value=mock_response)
        from app.chatbot.nodes.submit import submission_node
        state = make_state(flow="testimony", collected_fields=dict(VALID_TESTIMONY))
        result = await submission_node(state)  # must not raise

    assert result["error"] is not None
    assert result["flow"] == "testimony"  # not reset on API error


# ---------------------------------------------------------------------------
# Property-based tests — Pydantic schema validation
# ---------------------------------------------------------------------------

@given(st.fixed_dictionaries({
    "name": st.text(min_size=2, max_size=50),
    "content": st.text(min_size=50, max_size=500),
    "category": st.sampled_from(["healing", "salvation", "provision", "deliverance", "general"]),
}))
@h_settings(max_examples=100)
def test_valid_testimony_passes_schema(fields):
    """Any complete testimony fields → passes TestimonialCreate (Property 11)."""
    model = TestimonialCreate(**fields)
    assert model.name == fields["name"]


@given(st.fixed_dictionaries({
    "request": st.text(min_size=10, max_size=500),
    "is_anonymous": st.booleans(),
}))
@h_settings(max_examples=100)
def test_valid_prayer_passes_schema(fields):
    """Any complete prayer fields → passes PrayerRequestCreate (Property 11)."""
    model = PrayerRequestCreate(**fields)
    assert model.request == fields["request"]


@given(st.fixed_dictionaries({
    "name": st.text(min_size=2, max_size=50),
    "email": st.emails(),
    "partnership_type": st.sampled_from(["financial", "volunteer", "material"]),
}))
@h_settings(max_examples=100)
def test_valid_partnership_passes_schema(fields):
    """Any complete partnership fields → passes PartnershipCreate (Property 11)."""
    model = PartnershipCreate(**fields)
    assert model.partnership_type == fields["partnership_type"]
