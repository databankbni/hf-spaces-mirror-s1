"""
Tests for KnowledgeBaseService (Properties 2, 4 — Req §3.1–3.4).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import numpy as np


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_mock_model(dim: int = 384):
    """Return a mock SentenceTransformer that produces random embeddings."""
    model = MagicMock()
    model.encode = MagicMock(
        side_effect=lambda texts, batch_size=32: np.random.rand(len(texts), dim).astype(np.float32)
    )
    return model


def make_service():
    from app.chatbot.knowledge_base import KnowledgeBaseService
    return KnowledgeBaseService(make_mock_model())


# ---------------------------------------------------------------------------
# Unit tests — embed
# ---------------------------------------------------------------------------

def test_embed_returns_correct_shape():
    service = make_service()
    texts = ["hello", "world", "test"]
    result = service.embed(texts)
    assert len(result) == 3
    assert len(result[0]) == 384


def test_embed_empty_list():
    service = make_service()
    result = service.embed([])
    assert result == []


# ---------------------------------------------------------------------------
# Unit tests — add_documents + query (mocked DB)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_documents_calls_db_add():
    service = make_service()
    mock_db = MagicMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()

    docs = [{
        "content": "Test content for the church",
        "source_type": "web_crawl",
        "source_url": "http://example.com",
        "source_id": None,
        "language": "en",
        "chunk_index": 0,
    }]
    await service.add_documents(docs, mock_db)
    mock_db.add.assert_called_once()
    mock_db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_add_documents_empty_does_nothing():
    service = make_service()
    mock_db = MagicMock()
    mock_db.flush = AsyncMock()
    await service.add_documents([], mock_db)
    mock_db.flush.assert_not_called()


# ---------------------------------------------------------------------------
# Unit tests — crawl_and_index (mocked httpx)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_crawl_and_index_inserts_web_crawl_chunks():
    service = make_service()
    mock_db = MagicMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(rowcount=0))

    html_content = "<html><body><p>" + "Church content about Jesus. " * 50 + "</p></body></html>"
    mock_response = MagicMock()
    mock_response.text = html_content
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client

        result = await service.crawl_and_index(["http://example.com"], mock_db)

    assert result["urls_crawled"] == 1
    assert result["chunks_created"] > 0
    assert result["errors"] == []
    # Verify source_type on added chunks
    for call_args in mock_db.add.call_args_list:
        chunk = call_args[0][0]
        assert chunk.source_type == "web_crawl"


# ---------------------------------------------------------------------------
# Unit tests — refresh_dynamic_content returns summary dict
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_returns_summary_keys():
    service = make_service()
    mock_db = MagicMock()

    # Mock event and ministry query results
    mock_event = MagicMock()
    mock_event.id = "evt-1"
    mock_event.title = "Sunday Service"
    mock_event.event_date = "2026-06-15"
    mock_event.location = "Main Hall"
    mock_event.description = "Weekly Sunday worship service"
    from datetime import datetime, timezone
    mock_event.updated_at = datetime.now(timezone.utc)

    mock_ministry = MagicMock()
    mock_ministry.id = "min-1"
    mock_ministry.title = "Youth Ministry"
    mock_ministry.description = "Ministry for young people"
    mock_ministry.leader_name = "Pastor John"
    mock_ministry.updated_at = datetime.now(timezone.utc)

    events_result = MagicMock()
    events_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[mock_event])))

    ministries_result = MagicMock()
    ministries_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[mock_ministry])))

    source_id_result = MagicMock()
    source_id_result.fetchall = MagicMock(return_value=[])

    mock_db.execute = AsyncMock(side_effect=[
        events_result,
        source_id_result,  # existing event chunk IDs
        ministries_result,
        source_id_result,  # existing ministry chunk IDs
    ])
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()

    with patch("sqlalchemy.delete", return_value=MagicMock(where=MagicMock(return_value=MagicMock()))):
        result = await service.refresh_dynamic_content(mock_db)

    assert "events_fetched" in result
    assert "ministries_fetched" in result
    assert "chunks_upserted" in result
    assert "chunks_deleted" in result
    assert "duration_ms" in result
