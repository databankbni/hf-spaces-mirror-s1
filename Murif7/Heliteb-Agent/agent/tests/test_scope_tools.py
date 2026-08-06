"""Tests for scope_tools_by_intent: validates ScopeToolsSchema Pydantic,
the _regex_scope fallback, and that scope_tools_by_intent maps scope →
legacy intent correctly (compat with main.py endpoint and test_mandatory_scenarios).

Replaces the old test_intent_classification.py (Paso 8 migration).
Old tests validated IntentLabel + classify_intent; new tests validate
ScopeToolsSchema + scope_tools_by_intent.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from graph import (
    ScopeToolsSchema,
    _regex_scope,
    scope_tools_by_intent,
    _SCOPE_TO_TOOLS,
    _SCOPE_TO_LEGACY_INTENT,
)


# ── _regex_scope tests (replaces REGEX_CASES from old test) ─────────────────
# Each tuple: (text, expected_scope, expected_legacy_intent).

REGEX_SCOPE_CASES = [
    ("precio de 311315990", "product_query", "price"),
    ("Hola", "greeting", "greeting"),
    ("hay stock de 311315990 en Obrero?", "stock", "stock"),
    ("especificaciones de la camara DS-2CD1023G0E-I", "product_query", "specs"),
    ("generar cotización para Juan Pérez 311315990, 311315672", "quotation", "quotation"),
    ("buenos días, ¿cómo estás?", "greeting", "greeting"),
    ("cuánto cuesta el NVR?", "product_query", "price"),
    ("diferencia entre 311315990 y 311315672", "compare", "compare_products"),
    ("qué accesorios recomiendas para 311315990", "cross_sell", "cross_sell"),
    ("alguna cosa random que no es nada", "other", "other"),
]


@pytest.mark.parametrize("text,expected_scope,expected_intent", REGEX_SCOPE_CASES)
def test_regex_scope_returns_correct_shape(text: str, expected_scope: str, expected_intent: str) -> None:
    """_regex_scope returns a ScopeToolsSchema with the right scope."""
    result = _regex_scope(text)
    assert isinstance(result, ScopeToolsSchema), f"_regex_scope should return ScopeToolsSchema, got {type(result)}"
    assert result.scope == expected_scope, f"Expected scope={expected_scope} for {text!r}, got {result.scope}"
    # tools_subset should match the static mapping
    assert result.tools_subset == _SCOPE_TO_TOOLS[expected_scope]


# ── ScopeToolsSchema Pydantic model tests ────────────────────────────────────


def test_scope_tools_schema_valid() -> None:
    """Valid scope values are accepted."""
    for scope in ScopeToolsSchema.model_fields["scope"].annotation.__args__:
        obj = ScopeToolsSchema(scope=scope)
        assert obj.scope == scope
        assert obj.tools_subset == []
        assert obj.needs_user_input is False


def test_scope_tools_schema_invalid_rejected() -> None:
    """Invalid scope values raise ValidationError."""
    with pytest.raises(Exception):
        ScopeToolsSchema(scope="invalid_scope")


def test_scope_tools_schema_with_tools() -> None:
    """Can construct with tools_subset and needs_user_input."""
    obj = ScopeToolsSchema(
        scope="quotation",
        tools_subset=["buscar_producto", "generar_cotizacion"],
        needs_user_input=True,
    )
    assert obj.scope == "quotation"
    assert obj.tools_subset == ["buscar_producto", "generar_cotizacion"]
    assert obj.needs_user_input is True


def test_scope_tools_schema_model_dump() -> None:
    """ScopeToolsSchema supports model_dump (Pydantic v2)."""
    obj = ScopeToolsSchema(scope="stock", tools_subset=["buscar_producto", "consultar_stock"])
    dumped = obj.model_dump()
    assert dumped == {
        "scope": "stock",
        "tools_subset": ["buscar_producto", "consultar_stock"],
        "needs_user_input": False,
    }


# ── scope_tools_by_intent integration tests ─────────────────────────────────


def _make_state(msg: str) -> dict:
    """Build a minimal state for invoking scope_tools_by_intent."""
    return {
        "messages": [{"role": "user", "content": msg}],
        "intent": "",
    }


def test_scope_tools_by_intent_structured_output() -> None:
    """scope_tools_by_intent uses LLM structured output and maps scope → intent."""
    fake_schema = ScopeToolsSchema(
        scope="product_query",
        tools_subset=["buscar_producto", "ficha_producto"],
        needs_user_input=False,
    )

    mock_llm = MagicMock()
    mock_structured = MagicMock()
    mock_structured.invoke.return_value = fake_schema
    mock_llm.with_structured_output.return_value = mock_structured

    with patch("graph.get_llm", return_value=mock_llm):
        state = _make_state("precio de 311315990")
        result = scope_tools_by_intent(state)
        # "precio" matches _PRICE_RE → intent = "price"
        assert result["intent"] == "price"
        assert result["tools_scope"]["scope"] == "product_query"
        mock_llm.with_structured_output.assert_called_once_with(ScopeToolsSchema)
        mock_structured.invoke.assert_called_once()


def test_scope_tools_by_intent_fallback_on_llm_failure() -> None:
    """When LLM raises, _regex_scope fallback still returns a valid scope."""
    with patch("graph.get_llm", side_effect=RuntimeError("API down")):
        state = _make_state("hay stock de 311315990 en Obrero?")
        result = scope_tools_by_intent(state)
        assert result["intent"] == "stock"
        assert result["tools_scope"]["scope"] == "stock"


def test_scope_tools_by_intent_fallback_default_other() -> None:
    """Unclassifiable text defaults to scope=other / intent=other."""
    with patch("graph.get_llm", side_effect=RuntimeError("API down")):
        state = _make_state("xyzzy blorgh 12345")
        result = scope_tools_by_intent(state)
        assert result["intent"] == "other"
        assert result["tools_scope"]["scope"] == "other"
        assert result["tools_scope"]["tools_subset"] == []


def test_scope_tools_by_intent_re_classifies_greeting_as_product_query() -> None:
    """If LLM says greeting but msg contains product query signals, override to product_query."""
    # "dame cámaras" → LLM might say greeting (wrong), but _PRODUCT_QUERY_RE
    # matches "dame" → scope_tools_by_intent should re-classify to product_query.
    fake_schema = ScopeToolsSchema(scope="greeting", tools_subset=[], needs_user_input=False)

    mock_llm = MagicMock()
    mock_structured = MagicMock()
    mock_structured.invoke.return_value = fake_schema
    mock_llm.with_structured_output.return_value = mock_structured

    with patch("graph.get_llm", return_value=mock_llm):
        state = _make_state("dame cámaras wifi baratas")
        result = scope_tools_by_intent(state)
        assert result["tools_scope"]["scope"] == "product_query"
        assert result["tools_scope"]["tools_subset"] == ["buscar_producto", "ficha_producto"]


def test_scope_tools_by_intent_price_detected_via_price_regex() -> None:
    """For product_query scope, _PRICE_RE maps intent to 'price' if price signal present."""
    fake_schema = ScopeToolsSchema(scope="product_query", tools_subset=["buscar_producto"])

    mock_llm = MagicMock()
    mock_structured = MagicMock()
    mock_structured.invoke.return_value = fake_schema
    mock_llm.with_structured_output.return_value = mock_structured

    with patch("graph.get_llm", return_value=mock_llm):
        # "cuánto cuesta" should trigger _PRICE_RE
        state = _make_state("cuánto cuesta el NVR de 16 canales?")
        result = scope_tools_by_intent(state)
        assert result["intent"] == "price"

        # "especificaciones" should NOT trigger _PRICE_RE → intent = "specs"
        state2 = _make_state("especificaciones del DS-2CD1023G0E-I")
        result2 = scope_tools_by_intent(state2)
        assert result2["intent"] == "specs"


# ── Edge cases ──────────────────────────────────────────────────────────────


def test_regex_scope_greeting_prioritized() -> None:
    """Greeting pattern uses ^ anchor so pure greetings match first."""
    # "hola, precio de..." starts with hola → greeting
    result = _regex_scope("hola, precio de 311315990")
    assert result.scope == "greeting"
    # "cuánto cuesta, hola" doesn't start with hola → product_query
    result2 = _regex_scope("cuánto cuesta, hola")
    assert result2.scope == "product_query"


def test_regex_scope_quotation_before_price() -> None:
    """Quotation pattern should match before price when 'cotización' + 'precio' both present."""
    result = _regex_scope("precio de cotizacion 311315990")
    assert result.scope == "quotation"


def test_scope_tools_legacy_intent_mapping_complete() -> None:
    """Every scope in _SCOPE_TO_TOOLS has a mapping in _SCOPE_TO_LEGACY_INTENT."""
    for scope in _SCOPE_TO_TOOLS:
        assert scope in _SCOPE_TO_LEGACY_INTENT, f"Missing legacy intent for scope {scope!r}"


def test_scope_tools_tools_subset_consistent_with_registry() -> None:
    """Every tool name in _SCOPE_TO_TOOLS exists in the tool registry (import)."""
    # We can't import TOOL_REGISTRY here at test time without loading BGE-M3,
    # so we just check the tool names are the documented 5.
    VALID_TOOL_NAMES = {
        "buscar_producto", "ficha_producto", "consultar_stock",
        "sugerir_complementos", "generar_cotizacion",
    }
    for scope, tools in _SCOPE_TO_TOOLS.items():
        for tool_name in tools:
            assert tool_name in VALID_TOOL_NAMES, f"Unknown tool {tool_name!r} in scope {scope!r}"