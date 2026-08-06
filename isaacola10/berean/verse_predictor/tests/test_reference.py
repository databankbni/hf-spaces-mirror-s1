"""Reference parser — pure, fast, no models."""
import pytest

from reference import parse_reference


@pytest.mark.parametrize(
    "query,expected",
    [
        ("John 3:16", (43, 3, 16)),
        ("john 3 16", (43, 3, 16)),
        ("jn 3:16", (43, 3, 16)),
        ("John chapter 3 verse 16", (43, 3, 16)),
        ("first corinthians 13", (46, 13, None)),
        ("1 cor 13:4", (46, 13, 4)),
        ("second timothy 3 verse 16", (55, 3, 16)),
        ("psalm 23", (19, 23, None)),
        ("psalms 23:1", (19, 23, 1)),
        ("revelation 22 21", (66, 22, 21)),
        ("genesis 1 1", (1, 1, 1)),
        ("3 john 4", (64, 4, None)),
    ],
)
def test_parses_reference(query, expected):
    assert parse_reference(query) == expected


@pytest.mark.parametrize(
    "query",
    [
        "the lord is my shepherd",
        "for god so loved the world",
        "",
        "hello there",
    ],
)
def test_non_references_return_none(query):
    assert parse_reference(query) is None


def test_chapter_verse_word_form():
    from reference import format_reference, parse_reference
    assert parse_reference("Matthew chapter five verse two") == (40, 5, 2)
    assert parse_reference("in the book of Romans chapter 8 verse 28") == (45, 8, 28)
    assert parse_reference("John three sixteen") == (43, 3, 16)
    assert format_reference(40, 5, 2) == "Matthew 5:2"
    assert format_reference(40, 5, 2, style="v") == "Matthew 5v2"


def test_no_false_positive_from_short_alias():
    from reference import parse_reference
    # "is" used to (wrongly) match Isaiah; regression check.
    assert parse_reference("as it is written in psalm 23") == (19, 23, None)
