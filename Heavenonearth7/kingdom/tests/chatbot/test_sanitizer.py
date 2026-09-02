"""
Tests for input sanitizer (Property 14 — Req §12.5–12.6).
"""
import pytest
from hypothesis import given, settings as h_settings
from hypothesis import strategies as st

from app.chatbot.sanitizer import sanitize_input


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

def test_strips_whitespace():
    assert sanitize_input("  hello  ") == "hello"


def test_truncates_to_2000():
    long = "a" * 3000
    result = sanitize_input(long)
    assert len(result) == 2000


def test_2000_char_boundary_kept():
    exact = "a" * 2000
    assert sanitize_input(exact) == exact


def test_removes_null_bytes():
    assert "\x00" not in sanitize_input("hello\x00world")


def test_removes_control_chars():
    # BEL (\x07), BS (\x08) should be removed
    assert sanitize_input("hello\x07\x08world") == "helloworld"


def test_preserves_tab():
    assert "\t" in sanitize_input("col1\tcol2")


def test_preserves_newline():
    assert "\n" in sanitize_input("line1\nline2")


def test_preserves_carriage_return():
    assert "\r" in sanitize_input("line1\r\nline2")


def test_empty_string():
    assert sanitize_input("") == ""


def test_only_whitespace():
    assert sanitize_input("   \t  ") == ""


# ---------------------------------------------------------------------------
# Property-based tests
# ---------------------------------------------------------------------------

@given(st.text())
@h_settings(max_examples=300)
def test_output_max_2000(text):
    """Output is always ≤ 2000 chars (Property 14)."""
    assert len(sanitize_input(text)) <= 2000


@given(st.text())
@h_settings(max_examples=300)
def test_no_forbidden_control_chars(text):
    """Output contains no null bytes or disallowed control chars (Property 14)."""
    result = sanitize_input(text)
    for ch in result:
        code = ord(ch)
        if 0x00 <= code <= 0x1F:
            # Only \t (9), \n (10), \r (13) are allowed
            assert code in (9, 10, 13), (
                f"Disallowed control char U+{code:04X} found in output"
            )
