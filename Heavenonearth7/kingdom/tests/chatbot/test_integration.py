"""
Integration tests for the chat API endpoint (Property 15 — Req §8, §9, §12).
"""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from langchain_core.messages import AIMessage


# ---------------------------------------------------------------------------
# App fixture with mocked state
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_session_manager():
    from app.chatbot.session import SessionManager, ConversationSession
    from datetime import datetime, timezone
    sm = SessionManager(ttl_minutes=30)
    return sm


@pytest.fixture
def mock_knowledge_base():
    kb = MagicMock()
    kb.query = AsyncMock(return_value=[])
    kb.refresh_dynamic_content = AsyncMock(return_value={
        "events_fetched": 0, "ministries_fetched": 0,
        "chunks_upserted": 0, "chunks_deleted": 0, "duration_ms": 10.0
    })
    return kb


@pytest.fixture
def app_client(mock_session_manager, mock_knowledge_base):
    """FastAPI test client with chatbot state mocked on app.state."""
    import os
    os.environ.setdefault("GROQ_API_KEY", "test-key")
    os.environ.setdefault("CHATBOT_CRAWL_URLS", "http://example.com")
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
    os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
    os.environ.setdefault("SUPABASE_KEY", "test-key")
    os.environ.setdefault("JWT_SECRET_KEY", "a" * 32)
    os.environ.setdefault("ADMIN_EMAIL", "admin@test.com")
    os.environ.setdefault("ADMIN_PASSWORD", "testpassword123")

    from app.main import app
    app.state.session_manager = mock_session_manager
    app.state.knowledge_base = mock_knowledge_base
    return app


# ---------------------------------------------------------------------------
# Integration: Q&A flow via HTTP POST
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_qa_flow_returns_non_empty_response(app_client, mock_session_manager):
    """Q&A flow via POST /message — mocked Groq — returns non-empty content."""
    mock_final_state = {
        "session_id": "test",
        "messages": [AIMessage(content="Heaven on Earth meets every Sunday at 9am.")],
        "language": "en",
        "flow": "idle",
        "flow_step": "",
        "collected_fields": {},
        "missing_fields": [],
        "retrieved_context": None,
        "api_response": None,
        "error": None,
    }

    with patch("app.chatbot.agent.chatbot_graph") as mock_graph:
        mock_graph.ainvoke = AsyncMock(return_value=mock_final_state)

        async with AsyncClient(
            transport=ASGITransport(app=app_client),
            base_url="http://test",
        ) as client:
            session_id = str(uuid.uuid4())
            response = await client.post(
                "/api/v1/chat/message",
                json={"session_id": session_id, "message": "When do you meet?"},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["message"] != ""
    assert data["is_final"] is True


# ---------------------------------------------------------------------------
# Integration: rate limit enforcement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rate_limit_enforcement(app_client):
    """31 requests from same IP → 31st returns HTTP 429 (Property 15)."""
    mock_final_state = {
        "session_id": "test",
        "messages": [AIMessage(content="Hello!")],
        "language": "en",
        "flow": "idle",
        "flow_step": "",
        "collected_fields": {},
        "missing_fields": [],
        "retrieved_context": None,
        "api_response": None,
        "error": None,
    }

    with patch("app.chatbot.agent.chatbot_graph") as mock_graph:
        mock_graph.ainvoke = AsyncMock(return_value=mock_final_state)

        async with AsyncClient(
            transport=ASGITransport(app=app_client),
            base_url="http://test",
            headers={"X-Forwarded-For": "10.0.0.1"},
        ) as client:
            session_id = str(uuid.uuid4())
            responses = []
            for _ in range(31):
                r = await client.post(
                    "/api/v1/chat/message",
                    json={"session_id": session_id, "message": "test"},
                )
                responses.append(r.status_code)

    # At least one response should be 429
    assert 429 in responses
