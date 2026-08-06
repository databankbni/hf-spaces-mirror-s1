"""Tests for intent classification: regex fallback classifier and
structured-output Pydantic model (IntentLabel).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from graph import (
    IntentLabel,
    _regex_classify,
    classify_intent,
    ALLOWED_INTENTS,
)
from prompts.system import INTENT_CLASSIFICATION_PROMPT

# ── regex classifier tests ──────────────────────────────────────────────────

REGEX_CASES = [
    ("precio de 311315990", "price"),
    ("Hola", "greeting"),
    ("hay stock de 311315990 en Obrero?", "stock"),
    ("especificaciones de la camara DS-2CD1023G0E-I", "specs"),
    ("generar cotización para Juan Pérez 311315990, 311315672", "quotation"),
    ("buenos días, ¿cómo estás?", "greeting"),
    ("cuánto cuesta el NVR?", "price"),
    ("diferencia entre 311315990 y 311315672", "compare_products"),
    ("necesito instalar 4 cámaras en un espacio de 30x20 metros", "installation"),
    ("qué accesorios recomiendas para 311315990", "cross_sell"),
    ("alguna cosa random que no es nada", "other"),
]


@pytest.mark.parametrize("text,expected", REGEX_CASES)
def test_regex_classify(text: str, expected: str) -> None:
    assert _regex_classify(text) == expected


# ── IntentLabel model tests ─────────────────────────────────────────────────


def test_intent_label_valid() -> None:
    """Valid labels are accepted."""
    for label in ALLOWED_INTENTS.__args__:
        obj = IntentLabel(label=label, rationale="test")
        assert obj.label == label
        assert obj.rationale == "test"


def test_intent_label_invalid_rejected() -> None:
    """Invalid labels raise ValidationError."""
    with pytest.raises(Exception):
        IntentLabel(label="invalid_label")


def test_intent_label_default_rationale() -> None:
    """Rationale defaults to empty string."""
    obj = IntentLabel(label="greeting")
    assert obj.rationale == ""


# ── classify_intent integration tests ───────────────────────────────────────


def _make_state(msg: str) -> dict:
    return {"messages": [{"role": "user", "content": msg}],
            "intent": "", "tool_result": "", "response": ""}


def test_classify_intent_structured_output() -> None:
    """classify_intent uses LLM structured output when available."""
    fake_label = IntentLabel(label="price", rationale="asks about price")

    mock_llm = MagicMock()
    mock_structured = MagicMock()
    mock_structured.invoke.return_value = fake_label
    mock_llm.with_structured_output.return_value = mock_structured

    with patch("graph.get_llm", return_value=mock_llm):
        state = _make_state("precio de 311315990")
        result = classify_intent(state)
        assert result["intent"] == "price"
        mock_llm.with_structured_output.assert_called_once_with(IntentLabel)
        mock_structured.invoke.assert_called_once()


def test_classify_intent_fallback_on_llm_failure() -> None:
    """When LLM raises, regex fallback still returns a valid label."""
    with patch("graph.get_llm", side_effect=RuntimeError("API down")):
        state = _make_state("precio de 311315990")
        result = classify_intent(state)
        assert result["intent"] == "price"


def test_classify_intent_fallback_on_structured_error() -> None:
    """When with_structured_output itself fails, regex fallback kicks in."""
    with patch("graph.get_llm", side_effect=ValueError("no structured")):
        state = _make_state("hay stock de 311315990 en Obrero?")
        result = classify_intent(state)
        assert result["intent"] == "stock"


def test_classify_intent_fallback_invoke_error() -> None:
    """When invoke raises, regex fallback still returns valid label."""
    mock_llm = MagicMock()
    mock_structured = MagicMock()
    mock_structured.invoke.side_effect = RuntimeError("parse error")
    mock_llm.with_structured_output.return_value = mock_structured

    with patch("graph.get_llm", return_value=mock_llm):
        state = _make_state("Hola, buenos días")
        result = classify_intent(state)
        assert result["intent"] == "greeting"


def test_classify_intent_fallback_default_other() -> None:
    """Unclassifiable text defaults to 'other'."""
    with patch("graph.get_llm", side_effect=RuntimeError("API down")):
        state = _make_state("xyzzy blorgh 12345")
        result = classify_intent(state)
        assert result["intent"] == "other"


# ── Edge cases ──────────────────────────────────────────────────────────────


def test_regex_classify_first_match_wins() -> None:
    """The first matching regex pattern determines the label."""
    # "cotizacion" matches quotation before "precio" matches price
    assert _regex_classify("precio de cotizacion 311315990") == "quotation"


def test_regex_classify_greeting_prioritized() -> None:
    """Greeting pattern uses ^ anchor so simple greetings match first."""
    # "hola, precio de..." — greeting matches first (starts with hola)
    assert _regex_classify("hola, precio de 311315990") == "greeting"
    # "cuánto cuesta, hola" — greeting won't match (^ anchor), price will
    assert _regex_classify("cuánto cuesta, hola") == "price"


def test_intent_label_model_dump() -> None:
    """IntentLabel supports model_dump (Pydantic v2)."""
    obj = IntentLabel(label="stock", rationale="user asked about inventory")
    dumped = obj.model_dump()
    assert dumped == {"label": "stock", "rationale": "user asked about inventory"}
