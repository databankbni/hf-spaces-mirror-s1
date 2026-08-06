"""Retrieval behaviour: reference shortcut, version preference, grouping,
no-match, and chapter lookup. Uses the real index (cross-encoder disabled)."""


def test_exact_reference_shortcut(matcher):
    results = matcher.predict("john 3 16")
    assert results, "expected a result"
    top = results[0]
    assert top["ref"] == "John 3:16"
    assert top["exact"] is True
    # A bare reference defaults to KJV when no version is chosen.
    assert top["version"] == "KJV"


def test_prefers_quoted_version(matcher):
    # YLT-specific phrasing ("did so love") should surface the YLT rendering.
    results = matcher.predict("for God did so love the world")
    top = results[0]
    assert top["ref"] == "John 3:16"
    assert top["version"] == "YLT"


def test_results_are_grouped_by_verse(matcher):
    results = matcher.predict("the lord is my shepherd I shall not want", top_k=5)
    refs = [r["ref"] for r in results]
    # No duplicate verse references (grouping collapses translations).
    assert len(refs) == len(set(refs))
    # Each hit carries every available translation of that verse.
    assert all(len(r["translations"]) >= 1 for r in results)
    assert results[0]["ref"] == "Psalms 23:1"


def test_version_filter_restricts_results(matcher):
    results = matcher.predict("I can do all things through Christ", version="KJV")
    assert results
    assert all(r["version"] == "KJV" for r in results)
    assert results[0]["ref"] == "Philippians 4:13"


def test_low_score_for_nonsense(matcher):
    results = matcher.predict("asdf qwerty zxcvb gibberish nonsense")
    # Either nothing, or a clearly low top score (drives "no confident match").
    if results:
        assert results[0]["score"] < 0.45


def test_get_chapter(matcher):
    chapter = matcher.get_chapter(19, 23, "KJV")  # Psalms 23
    assert chapter is not None
    assert chapter["chapter"] == 23
    assert len(chapter["verses"]) == 6
    assert chapter["verses"][0]["text"].lower().startswith("the lord is my shepherd")


def test_spanish_query_finds_verse(matcher):
    if "SpaRV" not in matcher.available_versions:
        import pytest

        pytest.skip("Spanish not installed")
    results = matcher.predict("porque de tal manera amo Dios al mundo")
    assert results[0]["ref"] == "John 3:16"
