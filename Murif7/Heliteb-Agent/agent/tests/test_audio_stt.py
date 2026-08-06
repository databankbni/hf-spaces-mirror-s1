"""Tests for POST /agent/audio — Speech-To-Text via Gemini 2.5 Flash."""
from __future__ import annotations

import base64
import os
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Set env vars BEFORE importing main — llm/client.py creates module-level
# singletons that access MISTRAL_API_KEY / GOOGLE_API_KEY at import time.
# ---------------------------------------------------------------------------
os.environ.setdefault("MISTRAL_API_KEY", "test-mistral-key")
os.environ.setdefault("GOOGLE_API_KEY", "test-google-key")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-supabase-key")

from fastapi.testclient import TestClient

from main import MAX_AUDIO_BYTES, app

client = TestClient(app)


# ============================================================================
# Helpers
# ============================================================================

def _fake_llm_response(transcription: str = "Hola, este es un audio de prueba.") -> MagicMock:
    """Return a MagicMock that mimics a LangChain LLM result with .content."""
    result = MagicMock()
    result.content = transcription
    return result


def _small_audio_bytes() -> bytes:
    """Return a tiny WAV-like payload that passes the size check."""
    # Minimal valid WAV header (44 bytes) + tiny silence
    return b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"


# ============================================================================
# Tests
# ============================================================================

class TestAudioSTTSuccess:
    """Happy-path: valid audio file returns transcription."""

    def test_valid_audio_returns_transcription(self):
        """POST with a small audio file should return transcription + language."""
        fake_result = _fake_llm_response("Hola mundo")
        with patch(
            "main.ChatGoogleGenerativeAI.invoke",
            return_value=fake_result,
        ):
            response = client.post(
                "/agent/audio",
                files={"audio": ("test.wav", _small_audio_bytes(), "audio/wav")},
                data={"language": "es-CO"},
            )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "transcription" in data
        assert data["transcription"] == "Hola mundo"
        assert data["language"] == "es-CO"

    def test_default_language_is_es_co(self):
        """When language is omitted, it should default to 'es-CO'."""
        fake_result = _fake_llm_response("Default language transcription")
        with patch(
            "main.ChatGoogleGenerativeAI.invoke",
            return_value=fake_result,
        ):
            response = client.post(
                "/agent/audio",
                files={"audio": ("test.webm", _small_audio_bytes(), "audio/webm")},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["language"] == "es-CO"

    def test_custom_language_is_preserved(self):
        """When language is provided, it should be echoed back."""
        fake_result = _fake_llm_response("English transcription")
        with patch(
            "main.ChatGoogleGenerativeAI.invoke",
            return_value=fake_result,
        ):
            response = client.post(
                "/agent/audio",
                files={"audio": ("test.mp3", _small_audio_bytes(), "audio/mpeg")},
                data={"language": "en-US"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["language"] == "en-US"


class TestAudioSTTValidation:
    """Input validation: file size, missing fields, etc."""

    def test_file_too_large_returns_413(self):
        """Files exceeding MAX_AUDIO_BYTES should return 413."""
        big_audio = b"\x00" * (MAX_AUDIO_BYTES + 1)
        response = client.post(
            "/agent/audio",
            files={"audio": ("big.wav", big_audio, "audio/wav")},
        )
        assert response.status_code == 413, f"Expected 413, got {response.status_code}: {response.text}"

    def test_file_exactly_at_limit_should_pass(self):
        """Files exactly at MAX_AUDIO_BYTES should be accepted."""
        exact_audio = b"\x00" * MAX_AUDIO_BYTES
        fake_result = _fake_llm_response("ok")
        with patch(
            "main.ChatGoogleGenerativeAI.invoke",
            return_value=fake_result,
        ):
            response = client.post(
                "/agent/audio",
                files={"audio": ("exact.wav", exact_audio, "audio/wav")},
            )
        assert response.status_code == 200

    def test_missing_audio_file_returns_422(self):
        """Missing the required 'audio' field should return 422."""
        response = client.post(
            "/agent/audio",
            data={"language": "es-CO"},
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"


class TestAudioSTTErrorHandling:
    """LLM / server errors are handled gracefully."""

    def test_llm_failure_returns_500(self):
        """If the LLM call raises, the endpoint should return 500."""
        with patch(
            "main.ChatGoogleGenerativeAI.invoke",
            side_effect=RuntimeError("Gemini API timeout"),
        ):
            response = client.post(
                "/agent/audio",
                files={"audio": ("test.wav", _small_audio_bytes(), "audio/wav")},
            )
        assert response.status_code == 500, f"Expected 500, got {response.status_code}: {response.text}"
