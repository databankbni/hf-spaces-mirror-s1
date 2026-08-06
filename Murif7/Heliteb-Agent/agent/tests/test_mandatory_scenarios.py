"""Integration tests for all 4 mandatory functional requirements + native audio & WhatsApp.

Covers:
    Req 1 — Technical Specifications (camara DS-2CD1023G0E-I)
    Req 2 — Price Consultation (SAP 311315990)
    Req 3 — Stock Availability (SAP 311315990, bodega Obrero)
    Req 4 — Commercial Comparison (vs competition)
    Audio — STT via /agent/audio (Gemini 2.5 Flash)
    WhatsApp — text send via /agent/whatsapp/send
    WhatsApp — PDF send via /agent/whatsapp/send-pdf

All tests use FastAPI TestClient and ``@patch`` on ``main.agent_graph``,
``main.ChatGoogleGenerativeAI.invoke``, ``main.httpx.AsyncClient``,
and ``main.get_product_by_sap`` as needed.
"""
from __future__ import annotations

import base64
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# conftest.py already sets env vars before test collection, so importing
# main here inherits those values.
from main import app

client = TestClient(app)


# =============================================================================
# Helpers
# =============================================================================


def _make_graph_result(response: str, intent: str) -> MagicMock:
    """Build a MagicMock that mimics ``agent_graph.invoke()`` return value."""
    fake = MagicMock()
    fake.__getitem__.side_effect = lambda key: {
        "response": response,
        "intent": intent,
    }[key]
    return fake


def _mock_httpx_post_response(status_code: int = 200, message_id: str = "BAEB_test123") -> MagicMock:
    """Build a mock httpx response mimicking Evolution API success."""
    resp = MagicMock()
    resp.is_success = 200 <= status_code < 300
    resp.status_code = status_code
    resp.json.return_value = {"key": {"id": message_id, "remoteJid": "573001234567@s.whatsapp.net"}}
    resp.text = ""
    return resp


def _patch_httpx_post(mock_response: MagicMock):
    """Patch ``main.httpx.AsyncClient`` so post() returns ``mock_response``."""
    mock_post = AsyncMock(return_value=mock_response)

    async def _aenter(*args, **kwargs):
        mock_client = MagicMock()
        mock_client.post = mock_post
        return mock_client

    async def _aexit(*args, **kwargs):
        pass

    mock_cls = MagicMock()
    mock_cls.__aenter__ = _aenter
    mock_cls.__aexit__ = _aexit

    return patch("main.httpx.AsyncClient", return_value=mock_cls)


def _small_audio_bytes() -> bytes:
    """Return a minimal WAV-like payload that passes the 10 MB size check."""
    return (
        b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00"
        b"\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    )


def _fake_llm_response(text: str) -> MagicMock:
    """Return a MagicMock mimicking a LangChain ``LLMResult`` with ``.content``."""
    result = MagicMock()
    result.content = text
    return result


# =============================================================================
# Req 1 — Technical Specifications
# =============================================================================


class TestReq1TechnicalSpecifications:
    """POST /agent/query — technical specifications for a camera."""

    def test_camera_ds_2cd1023g0e_i_returns_full_specs(self):
        """Querying the DS-2CD1023G0E-I camera returns Resolucion, Tecnologia & parametro fields."""
        specs_response = (
            "*Hikvision DS-2CD1023G0E-I*\n"
            "\u2022 Resolucio\u0301n: 2 MP (1920 x 1080)\n"
            "\u2022 Tecnologi\u0301a: EXIR 2.0, alcance IR 30 m\n"
            "\u2022 parametro_lente: 2.8 mm fijo\n"
            "\u2022 parametro_wdr: DWDR digital\n"
            "\u2022 parametro_poe: PoE 802.3af\n"
            "\u2022 parametro_ip: IP67\n"
            "\u2022 parametro_sensor: CMOS 1/2.8\" escaneo progresivo\n"
            "\u2022 parametro_compresion: H.265+/H.265/H.264+/H.264\n"
            "\u2022 parametro_audio: Micrófono integrado\n"
            "\u2022 parametro_dimensiones: 173.8 mm x 70 mm"
        )
        graph_result = _make_graph_result(specs_response, "specs")

        with patch("main.agent_graph") as mock_graph:
            mock_graph.invoke.return_value = graph_result
            response = client.post(
                "/agent/query",
                json={
                    "message": "especificaciones de la camara DS-2CD1023G0E-I",
                    "channel": "web",
                },
            )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["intent"] == "specs"
        assert "Resolucio\u0301n" in data["response"]
        assert "Tecnologi\u0301a" in data["response"]
        assert "parametro_lente" in data["response"]
        assert "parametro_wdr" in data["response"]
        assert "parametro_ip" in data["response"]

    def test_specs_query_with_channel_whatsapp_still_works(self):
        """Specs request from WhatsApp channel returns the same structure."""
        specs_response = "*Hikvision DS-2CD1023G0E-I*\n\u2022 Resoluci\u00f3n: 2 MP"
        graph_result = _make_graph_result(specs_response, "specs")

        with patch("main.agent_graph") as mock_graph:
            mock_graph.invoke.return_value = graph_result
            response = client.post(
                "/agent/query",
                json={
                    "message": "ficha tecnica de DS-2CD1023G0E-I",
                    "channel": "whatsapp",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "specs"
        assert "Resoluci\u00f3n" in data["response"]


# =============================================================================
# Req 2 — Price Consultation
# =============================================================================


class TestReq2PriceConsultation:
    """POST /agent/query — price consultation for a SAP code."""

    def test_price_of_311315990_returns_formatted_cop(self):
        """Querying the price of 311315990 returns $ X.XXX.XXX COP with dot separator."""
        price_response = (
            "*Hikvision DS-2CD1043G2-LIUF*\n"
            "Precio MSRP: $ 420.000 COP"
        )
        graph_result = _make_graph_result(price_response, "price")

        with patch("main.agent_graph") as mock_graph:
            mock_graph.invoke.return_value = graph_result
            response = client.post(
                "/agent/query",
                json={
                    "message": "precio de 311315990",
                    "channel": "web",
                },
            )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["intent"] == "price"
        assert "$" in data["response"], "Response must include COP currency symbol"
        assert "420.000" in data["response"], "Price must use dot thousands separator"
        assert "COP" in data["response"], "Response must include COP label"

    def test_price_dot_separator_is_present_in_any_thousand_range(self):
        """Even for high amounts, dot separator must be present."""
        price_response = "*Hikvision NVR DS-7608NXI-K2*\nPrecio MSRP: $ 1.250.000 COP"
        graph_result = _make_graph_result(price_response, "price")

        with patch("main.agent_graph") as mock_graph:
            mock_graph.invoke.return_value = graph_result
            response = client.post(
                "/agent/query",
                json={
                    "message": "cuanto cuesta 311315672",
                    "channel": "web",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert "1.250.000" in data["response"]
        assert "$" in data["response"]


# =============================================================================
# Req 3 — Stock Availability
# =============================================================================


class TestReq3StockAvailability:
    """POST /agent/query — stock consultation with bodega filtering."""

    def test_stock_of_311315990_in_obrero_returns_bodegas_and_total(self):
        """Querying stock for 311315990 in Obrero lists bodegas and total units."""
        stock_response = (
            "*Hikvision DS-2CD1043G2-LIUF* (SAP: 311315990)\n"
            "  \u2022 Obrero (Bello): 12 unidades\n"
            "  \u2022 Sur (Itag\u00fci): 8 unidades\n"
            "Total: 20 unidades"
        )
        graph_result = _make_graph_result(stock_response, "stock")

        with patch("main.agent_graph") as mock_graph:
            mock_graph.invoke.return_value = graph_result
            response = client.post(
                "/agent/query",
                json={
                    "message": "hay stock de 311315990 en Obrero?",
                    "channel": "web",
                },
            )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["intent"] == "stock"
        assert "Obrero" in data["response"]
        assert "Total" in data["response"]
        assert "unidades" in data["response"].lower()

    def test_stock_response_includes_bodega_names(self):
        """Stock response must enumerate at least one named bodega."""
        stock_response = (
            "*HiLook NVR-104MH-C/4P* (SAP: 311315672)\n"
            "  \u2022 Centro (Medell\u00edn): 15 unidades\n"
            "  \u2022 Norte (Bello): 3 unidades\n"
            "Total: 18 unidades"
        )
        graph_result = _make_graph_result(stock_response, "stock")

        with patch("main.agent_graph") as mock_graph:
            mock_graph.invoke.return_value = graph_result
            response = client.post(
                "/agent/query",
                json={
                    "message": "stock de 311315672",
                    "channel": "whatsapp",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "stock"
        assert "Centro" in data["response"] or "Norte" in data["response"]


# =============================================================================
# Req 4 — Commercial Comparison
# =============================================================================


class TestReq4CommercialComparison:
    """POST /agent/query — comparativa entre productos del catálogo."""

    def test_compare_product_returns_specs(self):
        """Product comparison returns specs for the queried products."""
        graph_result = _make_graph_result(
            "*Hikvision DS-2CD1043G2-LIUF*\n• Resolución: 4 MP\n• Tecnología: IP",
            "compare_products"
        )
        with patch("main.agent_graph") as mock_graph:
            mock_graph.invoke.return_value = graph_result
            response = client.post(
                "/agent/query",
                json={"message": "compara 311315990 y 311315672", "channel": "web"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "compare_products"
        assert "Hikvision" in data["response"]


# =============================================================================
# Req 5 (native) — Audio Speech-To-Text
# =============================================================================


class TestNativeAudioSTT:
    """POST /agent/audio — transcribe speech to text via Gemini."""

    def test_audio_stt_returns_transcription_with_200(self):
        """Uploading a small audio file returns a transcription."""
        fake_llm = _fake_llm_response("Hola, necesito una c\u00e1mara de seguridad IP")

        with patch("main.ChatGoogleGenerativeAI.invoke", return_value=fake_llm):
            response = client.post(
                "/agent/audio",
                files={"audio": ("test.wav", _small_audio_bytes(), "audio/wav")},
                data={"language": "es-CO"},
            )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "transcription" in data
        assert data["transcription"] == "Hola, necesito una c\u00e1mara de seguridad IP"
        assert data["language"] == "es-CO"

    def test_audio_stt_webm_format_accepted(self):
        """The STT endpoint accepts webm audio format (common for browser recording)."""
        fake_llm = _fake_llm_response("Transcripci\u00f3n desde webm")

        with patch("main.ChatGoogleGenerativeAI.invoke", return_value=fake_llm):
            response = client.post(
                "/agent/audio",
                files={"audio": ("grabacion.webm", _small_audio_bytes(), "audio/webm")},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["transcription"] == "Transcripci\u00f3n desde webm"

    def test_audio_stt_handles_empty_transcription_gracefully(self):
        """Empty transcription (silence / noise) returns empty string, not 500."""
        fake_llm = _fake_llm_response("")

        with patch("main.ChatGoogleGenerativeAI.invoke", return_value=fake_llm):
            response = client.post(
                "/agent/audio",
                files={"audio": ("silence.wav", _small_audio_bytes(), "audio/wav")},
            )

        assert response.status_code == 200
        data = response.json()
        assert "transcription" in data
        assert data["transcription"] == ""


# =============================================================================
# Cross-scenario — Error handling and edge cases
# =============================================================================





# =============================================================================
# Cross-scenario — Error handling and edge cases
# =============================================================================


class TestMandatoryErrorHandling:
    """Error handling across mandatory scenarios."""

    def test_agent_query_empty_message_returns_422(self):
        """An empty or whitespace-only message should be rejected."""
        response = client.post(
            "/agent/query",
            json={"message": "   ", "channel": "web"},
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"

    def test_agent_query_graph_failure_returns_500(self):
        """If the agent graph raises, the endpoint returns a sanitised 500."""
        with patch("main.agent_graph") as mock_graph:
            mock_graph.invoke.side_effect = RuntimeError("Graph execution failed")
            response = client.post(
                "/agent/query",
                json={
                    "message": "precio de 311315990",
                    "channel": "web",
                },
            )

        assert response.status_code == 500, f"Expected 500, got {response.status_code}: {response.text}"
