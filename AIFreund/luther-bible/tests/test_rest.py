"""
test_rest.py — Unit tests for the REST /search endpoint (luther_mcp.server.handle_search).

The handler is an async Starlette endpoint. We drive it directly with a
hand-built Request (no httpx / TestClient needed) and read the JSONResponse
body. The sentence-transformers model and ChromaDB client are mocked by the
autouse fixture below, mirroring tests/test_server.py.
"""

import asyncio
import json
from unittest.mock import MagicMock

import pytest
from starlette.requests import Request


def _query_response(docs, metadatas, distances):
    return {
        "documents": [docs],
        "metadatas": [metadatas],
        "distances": [distances],
    }


def _john_316_meta(translation="GerBoLut"):
    book = "Johannes" if translation == "GerBoLut" else "John"
    return {
        "book": book,
        "book_en": "John",
        "book_number": 43,
        "chapter": 3,
        "verse": 16,
        "translation": translation,
        "testament": "NT",
    }


@pytest.fixture(autouse=True)
def patch_globals():
    import luther_mcp.server as srv

    mock_model = MagicMock()
    mock_model.encode.return_value = MagicMock(tolist=lambda: [0.1] * 384)

    mock_chroma = MagicMock()
    col = MagicMock()
    col.query.return_value = _query_response(
        docs=["Johannes 3:16 — Denn also hat Gott die Welt geliebet..."],
        metadatas=[_john_316_meta()],
        distances=[0.15],
    )
    mock_chroma.get_collection.return_value = col

    original_model = srv._model
    original_chroma = srv._chroma_client
    srv._model = mock_model
    srv._chroma_client = mock_chroma

    yield mock_model, mock_chroma, col

    srv._model = original_model
    srv._chroma_client = original_chroma


def _make_request(query_string: str) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/search",
        "query_string": query_string.encode(),
        "headers": [],
    }
    return Request(scope)


def _call(query_string: str):
    from luther_mcp.server import handle_search

    response = asyncio.run(handle_search(_make_request(query_string)))
    body = json.loads(bytes(response.body))
    return response.status_code, body


class TestHandleSearch:
    def test_returns_results(self):
        status, body = _call("query=God+loves+the+world")
        assert status == 200
        assert body["query"] == "God loves the world"
        assert body["translation"] == "GerBoLut"
        assert body["count"] == 1
        assert body["results"][0]["reference_en"] == "John 3:16"
        assert 0.0 <= body["results"][0]["score"] <= 1.0

    def test_missing_query_is_400(self):
        status, body = _call("translation=KJV")
        assert status == 400
        assert "error" in body

    def test_blank_query_is_400(self):
        status, body = _call("query=+")
        assert status == 400
        assert "error" in body

    def test_invalid_translation_is_400(self):
        status, body = _call("query=love&translation=NIV")
        assert status == 400
        assert "error" in body

    def test_non_integer_n_results_is_400(self):
        status, body = _call("query=love&n_results=lots")
        assert status == 400
        assert "error" in body

    def test_n_results_is_clamped(self, patch_globals):
        _, _, col = patch_globals
        _call("query=love&n_results=999")
        assert col.query.call_args[1]["n_results"] == 50

    def test_n_results_floor_is_one(self, patch_globals):
        _, _, col = patch_globals
        _call("query=love&n_results=0")
        assert col.query.call_args[1]["n_results"] == 1

    def test_testament_filter_passed_through(self, patch_globals):
        _, _, col = patch_globals
        _call("query=love&testament=NT")
        assert col.query.call_args[1].get("where") == {"testament": "NT"}

    def test_translation_all_allowed(self):
        status, body = _call("query=love&translation=all")
        assert status == 200
        assert body["translation"] == "all"
