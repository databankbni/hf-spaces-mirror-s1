"""
Tests for language detection (Property 8, 9 — Req §6.1–6.2).
"""
import pytest
from hypothesis import given, settings as h_settings
from hypothesis import strategies as st

from app.chatbot.nodes.language import detect_language


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

def test_pure_english():
    assert detect_language("Hello, how are you?") == "en"


def test_pure_amharic():
    assert detect_language("ሰላም እንዴት ነህ?") == "am"


def test_mixed_above_15_percent():
    # ~20% Ethiopic characters
    amharic_chars = "ሰላም"   # 3 chars
    english_chars = "hello world"  # 11 chars
    text = amharic_chars + english_chars  # 3/14 = ~21%
    assert detect_language(text) == "am"


def test_empty_string():
    assert detect_language("") == "en"


def test_exactly_15_percent_boundary():
    # Exactly 15% Ethiopic — should return "en" (ratio must be > 0.15)
    # 3 Ethiopic, 17 non-Ethiopic = 3/20 = 0.15 exactly
    text = "ሰሰሰ" + "a" * 17  # 3 Ethiopic / 20 total = 0.15
    assert detect_language(text) == "en"


def test_just_above_15_percent():
    # 16/100 = 0.16 > 0.15 → "am"
    text = "ሰ" * 16 + "a" * 84
    assert detect_language(text) == "am"


def test_single_ethiopic_char():
    # 1/1 = 1.0 > 0.15
    assert detect_language("ሰ") == "am"


def test_numbers_and_punctuation():
    assert detect_language("12345 !@#$%") == "en"


# ---------------------------------------------------------------------------
# Property-based tests
# ---------------------------------------------------------------------------

@given(st.text())
@h_settings(max_examples=200)
def test_idempotency(text):
    """detect_language(detect_language(t)) == detect_language(t) (Property 9)."""
    result = detect_language(text)
    assert detect_language(text) == result


@given(st.text(alphabet=st.characters(
    whitelist_categories=("Lo",),
    whitelist_characters="",
    min_codepoint=0x1200,
    max_codepoint=0x137F,
), min_size=1))
@h_settings(max_examples=100)
def test_all_ethiopic_is_am(text):
    """Pure Ethiopic text always → 'am' (Property 8)."""
    assert detect_language(text) == "am"
