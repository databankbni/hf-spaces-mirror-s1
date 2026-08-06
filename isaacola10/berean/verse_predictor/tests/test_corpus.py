"""Corpus loading: canonical keys, languages, manifest."""
from conftest import needs_versions

import corpus


@needs_versions
def test_versions_have_language_metadata():
    info = corpus.version_info()
    codes = {v["code"] for v in info}
    assert "KJV" in codes
    # Every version reports a language.
    assert all(v["language"] for v in info)


@needs_versions
def test_canonical_keys_align_across_languages():
    verses = corpus.load_verses()
    by_key = {}
    for v in verses:
        by_key.setdefault(v["key"], set()).add(v["language"])
    # John 3:16 is book 43, chapter 3, verse 16.
    key = "43:3:16"
    assert key in by_key
    # If Spanish is installed, the same key should carry both languages.
    if any(v["language"] == "es" for v in verses):
        assert "en" in by_key[key] and "es" in by_key[key]


@needs_versions
def test_every_verse_has_required_fields():
    verses = corpus.load_verses(versions=["KJV"])
    assert len(verses) > 30000
    sample = verses[0]
    for field in ("version", "language", "book_no", "key", "ref", "text"):
        assert field in sample
