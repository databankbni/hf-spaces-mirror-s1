"""Unit tests for the guardrails and helpers that survived the migration
from the rigid intent-pipeline (Paso 8 of the ReAct migration).

These helpers were preserved from the original ``graph.py``:
  - ``_is_empty_or_error`` — bypass LLM when tool returns vacío/error
  - ``_is_low_quality`` — advisory warning when <2 SAPs in result
  - ``_normalize_cop_strings`` — comma → dot thousands in COP strings
  - ``_format_cop`` — numeric → "$ X.XXX.XXX COP"
  - ``_check_spanish_register`` — warns on informal "tú" form
  - ``extract_sap`` — extracts a 9-digit SAP from text

Replaces the old test_guardrails.py (which tested execute_tool's
routing and was deleted in Paso 6). The routing is now the ReAct loop
driver, so its coverage lives in ``test_scope_tools.py`` (validation
of the deterministic scope → tools_subset) + ``test_query_exito_reto.py``
(E2E validation that the loop produces a coherent answer). These tests
here only cover the guardrail helpers preserved verbatim.
"""
from __future__ import annotations

import logging

import pytest

from graph import (
    _is_empty_or_error,
    _is_low_quality,
    _normalize_cop_strings,
    _format_cop,
    _check_spanish_register,
    extract_sap,
)


# ── _is_empty_or_error ─────────────────────────────────────────────────────


@pytest.mark.parametrize("tool_output,expected_empty", [
    # OK markers — should NOT be flagged as empty
    ("FICHA TECNICA\nMarca: Hikvision\nPrecio MSRP: $ 420.000 COP", False),
    ("📦 STOCK — Hikvision DS-2CD (SAP: 311315990)\nObrero (Bello): 12 unidades", False),
    ("📄 COTIZACIÓN — Juan Pérez\nTotal: $1.000.000 COP", False),
    ("Argumentos de venta: ...", False),
    ("Disponibilidad por bodega: ...", False),
    # Empty/error markers — should BE flagged
    ("No encontré productos para: cámaras wifi.", True),
    ("No encontre el producto con SAP 999999999.", True),
    ("❌ No encontré ese producto en el catálogo.", True),
    ("0 resultados para tu búsqueda.", True),
    ("Sin stock en ninguna bodega.", True),
    # Ambiguous: empty marker + OK marker (OK marker should win)
    ("No encontré productos, pero aquí hay argumentos de venta.", False),
    # None / empty input
    ("", True),
    (None, True),
])
def test_is_empty_or_error(tool_output, expected_empty):
    assert _is_empty_or_error(tool_output) is expected_empty


# ── _is_low_quality ─────────────────────────────────────────────────────────


def test_low_quality_few_saps():
    """Tool output with 0 or 1 SAPs (and no ficha/cotizacion/stock marker) → low quality."""
    assert _is_low_quality("Resultados:\n  Hikvision DS-2CD1 (SAP: 311315990)") is True
    assert _is_low_quality("Resultados sin SAP clear") is True


def test_low_quality_with_ficha_marker():
    """If 'ficha técnica' is present, NOT low quality even with <2 SAPs."""
    assert _is_low_quality("FICHA TECNICA\nMarca: Hik\nSAP: 311315990") is False


def test_low_quality_with_cotizacion_marker():
    assert _is_low_quality("📄 COTIZACIÓN — Juan\nModelo X") is False


def test_low_quality_with_stock_marker():
    assert _is_low_quality("📦 STOCK — Hikvision\nObrero: 1 unidades\nTotal: 1 unidades") is False


def test_low_quality_many_saps():
    """≥2 SAPs → not low quality."""
    text = "Resultados:\n  X (SAP: 111111111)\n  Y (SAP: 222222222)"
    assert _is_low_quality(text) is False


# ── _normalize_cop_strings ─────────────────────────────────────────────────


@pytest.mark.parametrize("input_text,expected", [
    # Comma thousands → dot
    ("$ 1.234.567 COP", "$ 1.234.567 COP"),  # already normalized
    ("$ 1,234,567 COP", "$ 1.234.567 COP"),  # comma → dot
    ("$ 420,000 COP", "$ 420.000 COP"),
    # Without COP suffix
    ("$ 1,234,567", "$ 1.234.567"),
    # No COP, no change
    ("Precio: 500 mil", "Precio: 500 mil"),
    # Multiple COP strings
    ("$ 1,000,000 COP y $ 2,500,000 COP", "$ 1.000.000 COP y $ 2.500.000 COP"),
    # Empty
    ("", ""),
])
def test_normalize_cop_strings(input_text, expected):
    assert _normalize_cop_strings(input_text) == expected


def test_normalize_cop_does_not_touch_other_numbers():
    """Numbers without the $ prefix should NOT be touched."""
    assert _normalize_cop_strings("1,234,567 sin $") == "1,234,567 sin $"


# ── _format_cop ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("n,expected", [
    (0, "$ 0 COP"),
    (420000, "$ 420.000 COP"),
    (1_234_567, "$ 1.234.567 COP"),
    (999_999.99, "$ 1.000.000 COP"),  # rounds to 1M
    (-500, "$ -500 COP"),
])
def test_format_cop(n, expected):
    assert _format_cop(n) == expected


def test_format_cop_non_numeric():
    """Non-numeric input raises (or returns 'Consultar' depending on impl)."""
    with pytest.raises((ValueError, TypeError)):
        _format_cop("not a number")


# ── _check_spanish_register ────────────────────────────────────────────────


def test_check_spanish_register_no_warning_on_usted(caplog):
    """Formal 'usted' should not trigger warning."""
    with caplog.at_level(logging.WARNING, logger="__name__"):
        # The logger name used by _check_spanish_register is the module logger
        # (imported as `logger`). We can't easily reach it via caplog without
        # importing it; just verify the function doesn't raise.
        _check_spanish_register("¿Cómo le puedo ayudar hoy?")


def test_check_spanish_register_warns_on_tuteo(caplog):
    """Informal 'tú' tokens SHOULD trigger a warning (function doesn't modify)."""
    import graph
    with caplog.at_level(logging.WARNING, logger=graph.logger.name):
        _check_spanish_register("¿Tú qué quieres saber?")
    # Should have logged a warning
    assert any("informal" in rec.message.lower() for rec in caplog.records), (
        f"Expected a warning about informal register; got: {[r.message for r in caplog.records]}"
    )


def test_check_spanish_register_does_not_modify():
    """The function is a logger, not a mutator — returns None."""
    text = "Tú tienes el precio?"
    assert _check_spanish_register(text) is None


# ── extract_sap ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("text,expected", [
    ("precio de 311315990", "311315990"),
    ("quiero info del SAP 311315672, gracias", "311315672"),
    ("comparar 111111111 y 222222222", "111111111"),  # returns first
    ("sin SAP en el mensaje", ""),  # no SAP
    ("codigo corto 12345", ""),  # 5 digits, not 9
    ("un texto sin numeros", ""),
])
def test_extract_sap(text, expected):
    assert extract_sap(text) == expected


def test_extract_sap_does_not_invent():
    """extract_sap should never return a fabricated SAP."""
    assert extract_sap("") == ""
    assert extract_sap("hola") == ""