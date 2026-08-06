"""Tests for PDF quotation generation: branding, structure, and formatting."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from main import (
    QuotationRequest,
    _format_cop,
    _generate_quotation_pdf_bytes,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _mock_product(marca: str, modelo: str, precio: float) -> MagicMock:
    """Build a mock Supabase product response."""
    resp = MagicMock()
    resp.data = {
        "marca": marca,
        "modelo": modelo,
        "heliteb_precios": [{"precio_msrp_cop": precio}],
    }
    return resp


def _make_request(
    codigos: list[str] | None = None,
    nombre: str = "Juan Pérez",
    consulta: str = "",
) -> QuotationRequest:
    return QuotationRequest(
        codigos_sap=codigos or ["311315990"],
        cliente_nombre=nombre,
        cliente_whatsapp="+573001234567",
        notas="Entrega urgente",
        consulta=consulta,
    )


# ── _format_cop tests ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, "$ 0 COP"),
        (1000, "$ 1.000 COP"),
        (1500000, "$ 1.500.000 COP"),
        (123456789, "$ 123.456.789 COP"),
        (999, "$ 999 COP"),
        (1000000, "$ 1.000.000 COP"),
    ],
)
def test_format_cop(value: float, expected: str) -> None:
    assert _format_cop(value) == expected


# ── PDF generation tests ────────────────────────────────────────────────────


@patch("main.get_product_by_sap")
def test_pdf_bytes_non_empty(mock_get: MagicMock) -> None:
    """_generate_quotation_pdf_bytes returns non-empty PDF bytes."""
    mock_get.return_value = _mock_product("Hikvision", "DS-2CD1023G0E-I", 450000)
    req = _make_request()
    pdf_bytes, filename, mime = _generate_quotation_pdf_bytes(req)
    assert len(pdf_bytes) > 0
    assert pdf_bytes[:5] == b"%PDF-"
    assert filename.endswith(".pdf")
    assert mime == "application/pdf"


@patch("main.get_product_by_sap")
def test_pdf_contains_branding_colors(mock_get: MagicMock) -> None:
    """PDF should contain HELITEB branding elements (title text present)."""
    mock_get.return_value = _mock_product("Hikvision", "DS-2CD1023G0E-I", 450000)
    req = _make_request()
    pdf_bytes, _, _ = _generate_quotation_pdf_bytes(req)
    # fpdf2 produces valid PDF — check key strings are in the raw bytes
    raw = pdf_bytes.decode("latin-1", errors="ignore")
    assert "HELITEB SAS" in raw
    assert "Soluciones en Seguridad" in raw
    assert "Términos y Condiciones" in raw


@patch("main.get_product_by_sap")
def test_pdf_contains_product_table(mock_get: MagicMock) -> None:
    """PDF body should include product codes and model names."""
    mock_get.return_value = _mock_product("Hikvision", "DS-2CD1023G0E-I", 450000)
    req = _make_request(codigos=["311315990"])
    pdf_bytes, _, _ = _generate_quotation_pdf_bytes(req)
    raw = pdf_bytes.decode("latin-1", errors="ignore")
    assert "311315990" in raw
    assert "DS-2CD1023G0E-I" in raw


@patch("main.get_product_by_sap")
def test_pdf_dot_thousands_format(mock_get: MagicMock) -> None:
    """Prices must use dot-thousands formatting, not comma-thousands."""
    mock_get.return_value = _mock_product("Hikvision", "DS-2CD1023G0E-I", 1500000)
    req = _make_request(codigos=["311315990"])
    pdf_bytes, _, _ = _generate_quotation_pdf_bytes(req)
    raw = pdf_bytes.decode("latin-1", errors="ignore")
    # 1.500.000 not 1,500,000
    assert "1.500.000" in raw


@patch("main.get_product_by_sap")
def test_pdf_totals_included(mock_get: MagicMock) -> None:
    """PDF must include product details and consultation header."""
    req = _make_request(codigos=["311315990"], consulta="linea monitores")
    mock_get.return_value = _mock_product("Hikvision", "DS-2CD1023G0E-I", 100000)
    pdf_bytes, _, _ = _generate_quotation_pdf_bytes(req)
    raw = pdf_bytes.decode("latin-1", errors="ignore")
    assert "311315990" in raw
    assert "linea monitores" in raw


@patch("main.get_product_by_sap")
def test_pdf_filename_format(mock_get: MagicMock) -> None:
    """Filename should follow Cotizacion_HELITEB_{name}_{cot_num}.pdf."""
    mock_get.return_value = _mock_product("Hikvision", "DS-2CD1023G0E-I", 100000)
    req = _make_request(nombre="Carlos López")
    _, filename, _ = _generate_quotation_pdf_bytes(req)
    assert filename.startswith("Cotizacion_HELITEB_Carlos_López_COT-")
    assert filename.endswith(".pdf")


@patch("main.get_product_by_sap")
def test_pdf_multiple_products(mock_get: MagicMock) -> None:
    """PDF generation works with multiple products."""
    def side_effect(codigo: str):
        products = {
            "311315990": _mock_product("Hikvision", "DS-2CD1023G0E-I", 450000),
            "311315672": _mock_product("Hikvision", "DS-2CD2023G0E-I", 680000),
        }
        return products.get(codigo, MagicMock(data=None))

    mock_get.side_effect = side_effect
    req = _make_request(codigos=["311315990", "311315672"])
    pdf_bytes, filename, _ = _generate_quotation_pdf_bytes(req)
    raw = pdf_bytes.decode("latin-1", errors="ignore")
    assert "311315990" in raw
    assert "311315672" in raw
    # Both individual prices must appear (totals section removed)
    assert "450.000" in raw or "$ 450.000" in raw
    assert "680.000" in raw or "$ 680.000" in raw


@patch("main.get_product_by_sap")
def test_pdf_no_products_raises_404(mock_get: MagicMock) -> None:
    """If no products found, should raise HTTPException 404."""
    mock_get.return_value = MagicMock(data=None)
    req = _make_request(codigos=["INVALID"])
    with pytest.raises(Exception) as exc_info:
        _generate_quotation_pdf_bytes(req)
    assert exc_info.value.status_code == 404  # type: ignore[attr-defined]


@patch("main.get_product_by_sap")
def test_pdf_notes_included(mock_get: MagicMock) -> None:
    """When notas is provided, it should appear in the PDF."""
    mock_get.return_value = _mock_product("Hikvision", "DS-2CD1023G0E-I", 450000)
    req = _make_request()
    req.notas = "Instalación incluida"
    pdf_bytes, _, _ = _generate_quotation_pdf_bytes(req)
    raw = pdf_bytes.decode("latin-1", errors="ignore")
    assert "Instalación incluida" in raw


@patch("main.get_product_by_sap")
def test_pdf_terms_section(mock_get: MagicMock) -> None:
    """Terms and conditions section must be present."""
    mock_get.return_value = _mock_product("Hikvision", "DS-2CD1023G0E-I", 450000)
    req = _make_request()
    pdf_bytes, _, _ = _generate_quotation_pdf_bytes(req)
    raw = pdf_bytes.decode("latin-1", errors="ignore")
    assert "Garantía oficial" in raw
    assert "7 días hábiles" in raw
    assert "HELITEB SAS - Seguridad Electr" in raw
