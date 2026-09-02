"""
Bug Condition Exploration Tests — Property 1: Invalid HTTP Client Base URL

These tests MUST FAIL on unfixed code. Failure confirms that Bug C3 exists:
  - submission_node builds its httpx.AsyncClient with
    base_url=f"http://{settings.host}:{settings.port}"
  - settings.host defaults to "0.0.0.0" (a bind/listen address, NOT a valid
    outbound TCP destination)
  - On most platforms, attempts to connect to 0.0.0.0 are rejected by the OS,
    silently dropping every chatbot-originated submission.

Expected counterexample when running on UNFIXED code:
  - _http_client.base_url will contain "0.0.0.0"
  - AssertionError: assert "0.0.0.0" not in "http://0.0.0.0:8000/"

Validates: Requirements 1.3 (bug condition) → will validate 2.3 after fix.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.chatbot.session import AgentState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_prayer_state(**overrides) -> AgentState:
    """Return a minimal valid AgentState for the prayer flow."""
    base: AgentState = {
        "session_id": "bug-test",
        "messages": [],
        "language": "en",
        "intent": None,
        "flow": "prayer",
        "flow_step": "submit",
        "collected_fields": {
            "is_anonymous": "no",
            "name": "Test User",
            "request": "Please pray for my family.",
        },
        "missing_fields": [],
        "retrieved_context": None,
        "api_response": None,
        "error": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Bug Condition Exploration Test — C3: Chatbot HTTP client base_url
# ---------------------------------------------------------------------------

def test_submission_node_http_client_base_url_does_not_contain_0000():
    """
    Bug Condition C3 — submission_node HTTP client uses invalid outbound address.

    Capture the base_url of the module-level _http_client singleton and assert
    that it does NOT contain "0.0.0.0".

    EXPECTED TO FAIL ON UNFIXED CODE:
      The current code sets base_url=f"http://{settings.host}:{settings.port}"
      and settings.host defaults to "0.0.0.0".
      Counterexample: base_url = "http://0.0.0.0:8000/"

    This test will PASS after the fix changes "settings.host" → "127.0.0.1".

    Validates: Requirement 1.3 (bug condition), will validate 2.3 after fix.
    """
    import app.chatbot.nodes.submit as submit_module

    # Access the module-level singleton directly — no mocking needed.
    # The bug is in the construction of this object.
    client = submit_module._http_client
    base_url_str = str(client.base_url)

    # This assertion FAILS on unfixed code because base_url is "http://0.0.0.0:8000/"
    assert "0.0.0.0" not in base_url_str, (
        f"Bug C3 confirmed: _http_client.base_url is '{base_url_str}'. "
        "The HTTP client was constructed with settings.host ('0.0.0.0') — "
        "an OS bind address — instead of '127.0.0.1'. "
        "Chatbot submissions will fail with ECONNREFUSED on most platforms."
    )


@pytest.mark.asyncio
async def test_submission_node_post_url_does_not_target_0000():
    """
    Bug Condition C3 — submission_node sends HTTP POST to 0.0.0.0.

    Call submission_node with a valid prayer AgentState and capture the
    base_url that the HTTP client was constructed with. Assert that the
    base_url does NOT contain "0.0.0.0".

    EXPECTED TO FAIL ON UNFIXED CODE because the module-level _http_client
    is instantiated at import time with the wrong host.

    Validates: Requirement 1.3 (bug condition), will validate 2.3 after fix.
    """
    import app.chatbot.nodes.submit as submit_module

    # Mock _http_client.post so we don't make a real network call,
    # but inspect the real client's base_url (which is set at module load time).
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.content = b"{}"
    mock_response.json.return_value = {}

    real_base_url = str(submit_module._http_client.base_url)

    with patch.object(submit_module._http_client, "post", new=AsyncMock(return_value=mock_response)):
        from app.chatbot.nodes.submit import submission_node
        state = make_prayer_state()
        await submission_node(state)

    # The bug: base_url was set to http://0.0.0.0:{port} at import time.
    # This assertion FAILS on unfixed code.
    assert "0.0.0.0" not in real_base_url, (
        f"Bug C3 confirmed: _http_client.base_url captured as '{real_base_url}'. "
        "Expected '127.0.0.1' (loopback), got '0.0.0.0' (bind address). "
        "Every chatbot-originated POST is sent to an unreachable host."
    )
