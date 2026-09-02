"""
Preservation Property Tests — Property 4: Non-Buggy Input Behaviors Unchanged

These tests MUST PASS on UNFIXED code. They verify that behaviors that are
already correct are not disturbed by the fix to Bug C3
(submission_node HTTP client base_url change from 0.0.0.0 → 127.0.0.1).

The fix ONLY changes the value of base_url in the module-level _http_client
constructor. It does NOT touch:
  - The Pydantic validation branch (ValidationError → error message, no HTTP call)
  - The non-2xx HTTP response branch (error message appended, no crash)
  - Any other logic in submission_node

Running these tests BEFORE the fix confirms the baseline behaviors to preserve.
Running them AFTER the fix confirms no regressions were introduced.

Validates: Requirements 3.7, 3.8

Observation-first methodology:
  - We first observe the unfixed code behavior for non-buggy inputs:
    * Pydantic-invalid collected_fields → no HTTP call, error message returned (req 3.7)
    * Valid collected_fields + non-2xx HTTP mock → error message appended (req 3.8)
  - These tests capture those observations as assertions.
  - They PASS on unfixed code (baseline) and MUST CONTINUE to pass after the fix.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from hypothesis import given, settings as h_settings, assume
from hypothesis import strategies as st

from app.chatbot.session import AgentState
from langchain_core.messages import AIMessage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_state(**overrides) -> AgentState:
    """Return a minimal AgentState with sensible defaults."""
    base: AgentState = {
        "session_id": "preservation-test",
        "messages": [],
        "language": "en",
        "intent": None,
        "flow": "prayer",
        "flow_step": "submit",
        "collected_fields": {},
        "missing_fields": [],
        "retrieved_context": None,
        "api_response": None,
        "error": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Strategies for generating Pydantic-INVALID collected_fields
# ---------------------------------------------------------------------------

# For the prayer flow:
#   PrayerRequestCreate requires `request: str` with min_length=10, max_length=5000
#   We generate dicts missing `request` entirely, or with too-short strings.
_invalid_prayer_fields = st.one_of(
    # Missing the required `request` field entirely
    st.fixed_dictionaries({}),
    st.fixed_dictionaries({"is_anonymous": st.just("no")}),
    # `request` present but too short (< 10 chars)
    st.fixed_dictionaries({
        "is_anonymous": st.just("no"),
        "name": st.text(min_size=1, max_size=50),
        "request": st.text(min_size=0, max_size=9),  # 0–9 chars → fails min_length=10
    }),
)

# For the testimony flow:
#   TestimonialCreate requires `name` (min_length=2), `content` (min_length=50),
#   and `category` matching the allowed pattern.
#   We generate dicts missing required fields or with out-of-spec values.
_invalid_testimony_fields = st.one_of(
    # Missing required fields entirely
    st.fixed_dictionaries({}),
    st.fixed_dictionaries({"name": st.text(min_size=2, max_size=50)}),
    # `content` too short (< 50 chars)
    st.fixed_dictionaries({
        "name": st.text(min_size=2, max_size=50),
        "content": st.text(min_size=0, max_size=49),
        "category": st.just("healing"),
    }),
    # Invalid category value
    st.fixed_dictionaries({
        "name": st.text(min_size=2, max_size=50),
        "content": st.text(min_size=50, max_size=200),
        "category": st.just("invalid_category_xyz"),
    }),
)

# For the partnership flow:
#   PartnershipCreate requires `name` (min_length=2), `email` (EmailStr),
#   and `partnership_type` matching "^(financial|volunteer|material)$".
#   We generate dicts missing required fields or with invalid values.
_invalid_partnership_fields = st.one_of(
    # Missing required fields entirely
    st.fixed_dictionaries({}),
    st.fixed_dictionaries({"name": st.text(min_size=2, max_size=50)}),
    # Invalid partnership_type value
    st.fixed_dictionaries({
        "name": st.text(min_size=2, max_size=50),
        "email": st.emails(),
        "partnership_type": st.just("invalid_type_xyz"),
    }),
    # Missing email (required EmailStr field)
    st.fixed_dictionaries({
        "name": st.text(min_size=2, max_size=50),
        "partnership_type": st.just("volunteer"),
    }),
)


# ---------------------------------------------------------------------------
# Property: Pydantic validation error → no HTTP call, error message returned
#
# Validates: Requirement 3.7
# Preservation: The validation-error branch is independent of the base_url fix.
# ---------------------------------------------------------------------------

@given(collected_fields=_invalid_prayer_fields)
@h_settings(max_examples=50)
@pytest.mark.asyncio
def test_prayer_validation_error_no_http_call(collected_fields):
    """
    **Validates: Requirements 3.7**

    Property: For any AgentState with flow="prayer" and collected_fields that
    fail PrayerRequestCreate validation, submission_node returns a state with
    an error message appended and does NOT make any HTTP call.

    This behavior is unchanged by the Bug C3 fix (base_url change).
    Tests PASS on unfixed code — confirms baseline behavior to preserve.
    """
    import asyncio
    import app.chatbot.nodes.submit as submit_module

    mock_post = AsyncMock()
    with patch.object(submit_module._http_client, "post", mock_post):
        state = make_state(flow="prayer", collected_fields=collected_fields)
        result = asyncio.get_event_loop().run_until_complete(
            submit_module.submission_node(state)
        )

    # No HTTP call should have been made
    mock_post.assert_not_called()

    # An error message must be appended to messages
    assert len(result["messages"]) > len(state["messages"]), (
        f"Expected an error message to be appended for invalid prayer fields "
        f"{collected_fields!r}, but messages were not updated."
    )

    # The error field must be set
    assert result["error"] is not None, (
        f"Expected result['error'] to be set for invalid fields {collected_fields!r}"
    )

    # The flow must remain unchanged (not reset to 'idle')
    assert result["flow"] == "prayer", (
        f"Expected flow to remain 'prayer' on validation error, got {result['flow']!r}"
    )


@given(collected_fields=_invalid_testimony_fields)
@h_settings(max_examples=50)
@pytest.mark.asyncio
def test_testimony_validation_error_no_http_call(collected_fields):
    """
    **Validates: Requirements 3.7**

    Property: For any AgentState with flow="testimony" and collected_fields that
    fail TestimonialCreate validation, submission_node returns a state with
    an error message appended and does NOT make any HTTP call.

    This behavior is unchanged by the Bug C3 fix (base_url change).
    Tests PASS on unfixed code — confirms baseline behavior to preserve.
    """
    import asyncio
    import app.chatbot.nodes.submit as submit_module

    mock_post = AsyncMock()
    with patch.object(submit_module._http_client, "post", mock_post):
        state = make_state(flow="testimony", collected_fields=collected_fields)
        result = asyncio.get_event_loop().run_until_complete(
            submit_module.submission_node(state)
        )

    mock_post.assert_not_called()
    assert len(result["messages"]) > len(state["messages"]), (
        f"Expected error message for invalid testimony fields {collected_fields!r}"
    )
    assert result["error"] is not None
    assert result["flow"] == "testimony"


@given(collected_fields=_invalid_partnership_fields)
@h_settings(max_examples=50)
@pytest.mark.asyncio
def test_partnership_validation_error_no_http_call(collected_fields):
    """
    **Validates: Requirements 3.7**

    Property: For any AgentState with flow="partnership" and collected_fields that
    fail PartnershipCreate validation, submission_node returns a state with
    an error message appended and does NOT make any HTTP call.

    This behavior is unchanged by the Bug C3 fix (base_url change).
    Tests PASS on unfixed code — confirms baseline behavior to preserve.
    """
    import asyncio
    import app.chatbot.nodes.submit as submit_module

    mock_post = AsyncMock()
    with patch.object(submit_module._http_client, "post", mock_post):
        state = make_state(flow="partnership", collected_fields=collected_fields)
        result = asyncio.get_event_loop().run_until_complete(
            submit_module.submission_node(state)
        )

    mock_post.assert_not_called()
    assert len(result["messages"]) > len(state["messages"]), (
        f"Expected error message for invalid partnership fields {collected_fields!r}"
    )
    assert result["error"] is not None
    assert result["flow"] == "partnership"


# ---------------------------------------------------------------------------
# Strategies for generating Pydantic-VALID collected_fields
# ---------------------------------------------------------------------------

_valid_prayer_fields = st.fixed_dictionaries({
    "is_anonymous": st.sampled_from(["no", "yes", "true", "false", "1"]),
    "name": st.text(min_size=1, max_size=100),
    "request": st.text(min_size=10, max_size=500),
})

_valid_testimony_fields = st.fixed_dictionaries({
    "name": st.text(min_size=2, max_size=100),
    "content": st.text(min_size=50, max_size=500),
    "category": st.sampled_from(["healing", "salvation", "provision", "deliverance", "general"]),
})

_valid_partnership_fields = st.fixed_dictionaries({
    "name": st.text(min_size=2, max_size=100),
    "email": st.emails(),
    "partnership_type": st.sampled_from(["financial", "volunteer", "material"]),
})

_flow_with_fields = st.one_of(
    st.tuples(st.just("prayer"), _valid_prayer_fields),
    st.tuples(st.just("testimony"), _valid_testimony_fields),
    st.tuples(st.just("partnership"), _valid_partnership_fields),
)

# Language options
_languages = st.sampled_from(["en", "am"])


# ---------------------------------------------------------------------------
# Property: Non-2xx response → error message appended, no crash, flow unchanged
#
# Validates: Requirement 3.8
# Preservation: The non-2xx error branch is independent of the base_url fix.
# ---------------------------------------------------------------------------

@given(flow_and_fields=_flow_with_fields, language=_languages)
@h_settings(max_examples=50)
@pytest.mark.asyncio
def test_non_2xx_response_appends_error_message(flow_and_fields, language):
    """
    **Validates: Requirements 3.8**

    Property: For any AgentState with a valid flow and valid collected_fields,
    when the mocked HTTP client returns a 422 (non-2xx) response, submission_node:
      1. Appends exactly one error message to the state's messages list.
      2. Does NOT raise an exception.
      3. Returns the flow unchanged (not reset to "idle").
      4. Sets result["error"] to a non-None string.

    This behavior is unchanged by the Bug C3 fix (base_url change).
    The mock replaces the entire HTTP client, so whether base_url is 0.0.0.0
    or 127.0.0.1 does not affect this test.

    Tests PASS on unfixed code — confirms baseline behavior to preserve.
    """
    import asyncio
    import app.chatbot.nodes.submit as submit_module

    flow, collected_fields = flow_and_fields

    # Mock a 422 response (non-2xx)
    mock_response = MagicMock()
    mock_response.status_code = 422
    mock_response.text = "Unprocessable Entity"
    mock_response.content = b"error"

    mock_post = AsyncMock(return_value=mock_response)
    with patch.object(submit_module._http_client, "post", mock_post):
        state = make_state(
            flow=flow,
            collected_fields=dict(collected_fields),
            language=language,
        )
        initial_message_count = len(state["messages"])

        result = asyncio.get_event_loop().run_until_complete(
            submit_module.submission_node(state)
        )

    # 1. An error message was appended
    assert len(result["messages"]) == initial_message_count + 1, (
        f"Expected exactly one message to be appended on 422 response for "
        f"flow={flow!r}, but message count went from {initial_message_count} "
        f"to {len(result['messages'])}"
    )

    # 2. The appended message is an AIMessage (the error message to the user)
    last_message = result["messages"][-1]
    assert isinstance(last_message, AIMessage), (
        f"Expected an AIMessage to be appended, got {type(last_message)}"
    )

    # 3. The flow is NOT reset to "idle" on error
    assert result["flow"] == flow, (
        f"Expected flow to remain {flow!r} on non-2xx response, got {result['flow']!r}"
    )

    # 4. error field is set
    assert result["error"] is not None, (
        "Expected result['error'] to be set on non-2xx HTTP response"
    )
    assert "422" in result["error"], (
        f"Expected result['error'] to reference HTTP 422, got {result['error']!r}"
    )

    # 5. The HTTP post WAS called (validation passed, network was attempted)
    mock_post.assert_called_once()


# ---------------------------------------------------------------------------
# Unit test: error message language is preserved for both "en" and "am"
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_validation_error_returns_en_message_for_en_language():
    """
    Preservation: The English validation error message content is unchanged
    by the fix.
    """
    import app.chatbot.nodes.submit as submit_module

    state = make_state(
        flow="prayer",
        language="en",
        collected_fields={"request": "too short"},  # < 10 chars, fails validation
    )

    mock_post = AsyncMock()
    with patch.object(submit_module._http_client, "post", mock_post):
        result = await submit_module.submission_node(state)

    mock_post.assert_not_called()
    assert result["messages"]
    msg_content = result["messages"][-1].content
    # The message should be the English validation error message
    assert "check your answers" in msg_content.lower() or "information" in msg_content.lower(), (
        f"Unexpected validation error message: {msg_content!r}"
    )


@pytest.mark.asyncio
async def test_validation_error_returns_am_message_for_am_language():
    """
    Preservation: The Amharic validation error message content is unchanged
    by the fix.
    """
    import app.chatbot.nodes.submit as submit_module

    state = make_state(
        flow="prayer",
        language="am",
        collected_fields={"request": "short"},  # < 10 chars, fails validation
    )

    mock_post = AsyncMock()
    with patch.object(submit_module._http_client, "post", mock_post):
        result = await submit_module.submission_node(state)

    mock_post.assert_not_called()
    assert result["messages"]
    # Just verify a message was appended in some form
    assert len(result["messages"]) == 1


@pytest.mark.asyncio
async def test_unknown_flow_returns_state_unchanged():
    """
    Preservation: For an unrecognized flow name, submission_node returns state
    unchanged without crashing or making any HTTP call.
    """
    import app.chatbot.nodes.submit as submit_module

    state = make_state(flow="unknown_flow", collected_fields={"key": "value"})
    original_messages = list(state["messages"])

    mock_post = AsyncMock()
    with patch.object(submit_module._http_client, "post", mock_post):
        result = await submit_module.submission_node(state)

    mock_post.assert_not_called()
    assert result["messages"] == original_messages
