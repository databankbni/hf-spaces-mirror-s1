"""
test_server.py — Unit tests for luther_mcp.server

Mocks sentence-transformers model and ChromaDB. No external calls needed.

Run with:
    python -m pytest tests/ -v
"""

from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers to build mock ChromaDB query / get responses
# ---------------------------------------------------------------------------

def _query_response(docs, metadatas, distances):
    return {
        "documents": [docs],
        "metadatas": [metadatas],
        "distances": [distances],
    }


def _get_response(doc_id, doc, metadata):
    return {
        "ids": [doc_id],
        "documents": [doc],
        "metadatas": [metadata],
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_globals():
    """Inject mock sentence-transformers model and ChromaDB client into the server module."""
    import luther_mcp.server as srv

    mock_model = MagicMock()
    mock_model.encode.return_value = MagicMock(tolist=lambda: [0.1] * 384)

    mock_chroma = MagicMock()

    original_model = srv._model
    original_chroma = srv._chroma_client
    srv._model = mock_model
    srv._chroma_client = mock_chroma

    yield mock_model, mock_chroma

    srv._model = original_model
    srv._chroma_client = original_chroma


# ---------------------------------------------------------------------------
# resolve_book_number
# ---------------------------------------------------------------------------

class TestResolveBookNumber:
    def test_english_name(self):
        from luther_mcp.server import resolve_book_number
        assert resolve_book_number("John") == 43

    def test_german_name(self):
        from luther_mcp.server import resolve_book_number
        assert resolve_book_number("Johannes") == 43

    def test_case_insensitive(self):
        from luther_mcp.server import resolve_book_number
        assert resolve_book_number("JOHN") == resolve_book_number("john") == 43

    def test_genesis(self):
        from luther_mcp.server import resolve_book_number
        assert resolve_book_number("Genesis") == 1
        assert resolve_book_number("1. Mose") == 1

    def test_revelation(self):
        from luther_mcp.server import resolve_book_number
        assert resolve_book_number("Revelation") == 66
        assert resolve_book_number("Offenbarung") == 66

    def test_unknown_returns_none(self):
        from luther_mcp.server import resolve_book_number
        assert resolve_book_number("Narnia") is None

    def test_whitespace_stripped(self):
        from luther_mcp.server import resolve_book_number
        assert resolve_book_number("  John  ") == 43


# ---------------------------------------------------------------------------
# score_from_distance
# ---------------------------------------------------------------------------

class TestScoreFromDistance:
    def test_zero_distance_is_perfect(self):
        from luther_mcp.server import score_from_distance
        assert score_from_distance(0.0) == 1.0

    def test_distance_one_is_zero(self):
        from luther_mcp.server import score_from_distance
        assert score_from_distance(1.0) == 0.0

    def test_clamps_below_zero(self):
        from luther_mcp.server import score_from_distance
        assert score_from_distance(1.5) == 0.0

    def test_midpoint(self):
        from luther_mcp.server import score_from_distance
        assert score_from_distance(0.5) == 0.5


# ---------------------------------------------------------------------------
# tool_search_bible
# ---------------------------------------------------------------------------

class TestSearchBible:
    def _make_collection(self, mock_chroma, translation="GerBoLut"):
        col = MagicMock()
        col.query.return_value = _query_response(
            docs=["Johannes 3:16 — Denn also hat Gott die Welt geliebet..."],
            metadatas=[_john_316_meta(translation)],
            distances=[0.15],
        )
        mock_chroma.get_collection.return_value = col
        return col

    def test_returns_list(self, patch_globals):
        from luther_mcp.server import tool_search_bible
        _, mock_chroma = patch_globals
        self._make_collection(mock_chroma)
        results = tool_search_bible("God loves the world")
        assert isinstance(results, list)
        assert len(results) == 1

    def test_result_fields(self, patch_globals):
        from luther_mcp.server import tool_search_bible
        _, mock_chroma = patch_globals
        self._make_collection(mock_chroma)
        result = tool_search_bible("God loves the world")[0]
        assert result["reference"] == "Johannes 3:16"
        assert result["reference_en"] == "John 3:16"
        assert result["translation"] == "GerBoLut"
        assert 0.0 <= result["score"] <= 1.0

    def test_no_internal_keys(self, patch_globals):
        from luther_mcp.server import tool_search_bible
        _, mock_chroma = patch_globals
        self._make_collection(mock_chroma)
        result = tool_search_bible("love")[0]
        assert not any(k.startswith("_") for k in result)

    def test_testament_filter_applied(self, patch_globals):
        from luther_mcp.server import tool_search_bible
        _, mock_chroma = patch_globals
        col = self._make_collection(mock_chroma)
        tool_search_bible("love", testament="NT")
        call_kwargs = col.query.call_args[1]
        assert call_kwargs.get("where") == {"testament": "NT"}

    def test_no_testament_filter_when_none(self, patch_globals):
        from luther_mcp.server import tool_search_bible
        _, mock_chroma = patch_globals
        col = self._make_collection(mock_chroma)
        tool_search_bible("love", testament=None)
        call_kwargs = col.query.call_args[1]
        assert "where" not in call_kwargs

    def test_model_encode_called(self, patch_globals):
        from luther_mcp.server import tool_search_bible
        mock_model, mock_chroma = patch_globals
        self._make_collection(mock_chroma)
        tool_search_bible("something")
        mock_model.encode.assert_called_once()
        # E5 convention: query prefix
        call_args = mock_model.encode.call_args[0][0]
        assert call_args.startswith("query: ")

    def test_missing_collection_returns_empty(self, patch_globals):
        from luther_mcp.server import tool_search_bible
        _, mock_chroma = patch_globals
        mock_chroma.get_collection.side_effect = Exception("not found")
        results = tool_search_bible("anything")
        assert results == []

    def test_all_deduplicates(self, patch_globals):
        """When translation='all', same verse from multiple collections
        should appear only once (best score wins)."""
        from luther_mcp.server import tool_search_bible
        _, mock_chroma = patch_globals

        def make_col(translation, distance):
            col = MagicMock()
            col.query.return_value = _query_response(
                docs=["Johannes 3:16 — text"],
                metadatas=[_john_316_meta(translation)],
                distances=[distance],
            )
            return col

        cols = {
            "GerBoLut": make_col("GerBoLut", 0.2),
            "KJV": make_col("KJV", 0.1),
            "web": make_col("web", 0.3),
        }
        mock_chroma.get_collection.side_effect = lambda name, **_: cols[name]

        results = tool_search_bible("love", translation="all", n_results=10)
        assert len(results) == 1
        assert results[0]["score"] == pytest.approx(0.9)  # 1 - 0.1


# ---------------------------------------------------------------------------
# tool_get_verse
# ---------------------------------------------------------------------------

class TestGetVerse:
    def _make_collection(self, mock_chroma, translation="GerBoLut"):
        meta = _john_316_meta(translation)
        book = meta["book"]
        doc = f"{book} 3:16 — Denn also hat Gott die Welt geliebet..."
        col = MagicMock()
        col.get.return_value = _get_response(
            f"{translation}_43_3_16", doc, meta
        )
        mock_chroma.get_collection.return_value = col
        return col

    def test_returns_dict_for_single_translation(self, patch_globals):
        from luther_mcp.server import tool_get_verse
        _, mock_chroma = patch_globals
        self._make_collection(mock_chroma)
        result = tool_get_verse("John", 3, 16)
        assert isinstance(result, dict)
        assert result["reference"] == "Johannes 3:16"
        assert result["reference_en"] == "John 3:16"
        assert "Gott" in result["text"]

    def test_german_book_name_resolves(self, patch_globals):
        from luther_mcp.server import tool_get_verse
        _, mock_chroma = patch_globals
        self._make_collection(mock_chroma)
        result = tool_get_verse("Johannes", 3, 16)
        assert "error" not in result

    def test_unknown_book_returns_error(self, patch_globals):
        from luther_mcp.server import tool_get_verse
        _, _ = patch_globals
        result = tool_get_verse("Narnia", 1, 1)
        assert "error" in result

    def test_missing_verse_returns_error(self, patch_globals):
        from luther_mcp.server import tool_get_verse
        _, mock_chroma = patch_globals
        col = MagicMock()
        col.get.return_value = {"ids": [], "documents": [], "metadatas": []}
        mock_chroma.get_collection.return_value = col
        result = tool_get_verse("John", 3, 16)
        assert "error" in result

    def test_all_returns_list(self, patch_globals):
        from luther_mcp.server import tool_get_verse
        _, mock_chroma = patch_globals

        def make_col(translation):
            col = MagicMock()
            meta = _john_316_meta(translation)
            book = meta["book"]
            doc = f"{book} 3:16 — text"
            col.get.return_value = _get_response(f"{translation}_43_3_16", doc, meta)
            return col

        cols = {t: make_col(t) for t in ["GerBoLut", "KJV", "web"]}
        mock_chroma.get_collection.side_effect = lambda name, **_: cols[name]

        result = tool_get_verse("John", 3, 16, translation="all")
        assert isinstance(result, list)
        assert len(result) == 3
        translations = {r["translation"] for r in result}
        assert translations == {"GerBoLut", "KJV", "web"}

    def test_doc_id_format(self, patch_globals):
        from luther_mcp.server import tool_get_verse
        _, mock_chroma = patch_globals
        col = self._make_collection(mock_chroma)
        tool_get_verse("John", 3, 16)
        col.get.assert_called_once_with(
            ids=["GerBoLut_43_3_16"],
            include=["documents", "metadatas"],
        )


# ---------------------------------------------------------------------------
# tool_list_translations
# ---------------------------------------------------------------------------

class TestListTranslations:
    def test_returns_all_three(self, patch_globals):
        from luther_mcp.server import tool_list_translations
        _, mock_chroma = patch_globals
        col = MagicMock()
        col.count.return_value = 31102
        mock_chroma.get_collection.return_value = col
        result = tool_list_translations()
        assert len(result) == 3
        ids = {r["id"] for r in result}
        assert ids == {"GerBoLut", "KJV", "web"}

    def test_result_fields(self, patch_globals):
        from luther_mcp.server import tool_list_translations
        _, mock_chroma = patch_globals
        col = MagicMock()
        col.count.return_value = 31102
        mock_chroma.get_collection.return_value = col
        result = tool_list_translations()
        for r in result:
            assert "id" in r
            assert "language" in r
            assert "description" in r
            assert "verse_count" in r
            assert "indexed" in r

    def test_unavailable_collection(self, patch_globals):
        from luther_mcp.server import tool_list_translations
        _, mock_chroma = patch_globals
        mock_chroma.get_collection.side_effect = Exception("not found")
        result = tool_list_translations()
        for r in result:
            assert r["verse_count"] == 0
            assert r["indexed"] is False
