"""Tests for the LLM client factory — lazy init, timeouts, and fallback."""
from __future__ import annotations

import importlib
import os
from unittest import mock

import pytest


# Module path used for patching.
_MODULE = "llm.client"


# =============================================================================
# Lazy import — no env vars required at import time
# =============================================================================


def test_lazy_import_no_env():
    """Importing the module must succeed without MISTRAL_API_KEY / GOOGLE_API_KEY.

    The factories decorated with ``@lru_cache`` are *defined* at import time
    but never *called*, so ``os.environ["MISTRAL_API_KEY"]`` is not accessed
    until the first ``get_llm()`` call.
    """
    saved: dict[str, str | None] = {}
    for key in ("MISTRAL_API_KEY", "GOOGLE_API_KEY"):
        saved[key] = os.environ.pop(key, None)

    try:
        mod = importlib.import_module(_MODULE)
        importlib.reload(mod)

        # Module-level symbols exist and are usable.
        assert hasattr(mod, "get_llm")
        assert hasattr(mod, "_mistral_small")
        assert hasattr(mod, "_mistral_large")
        assert hasattr(mod, "_gemini_flash")

        # Calling the module import again (idempotent) does not raise either.
        importlib.reload(mod)
    finally:
        for key, val in saved.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val


# =============================================================================
# Successful initialisation with keys
# =============================================================================


def test_get_llm_with_keys():
    """``get_llm("simple")`` returns a ``ChatMistralAI`` instance when keys set."""
    os.environ.setdefault("MISTRAL_API_KEY", "test-mistral-key")
    os.environ.setdefault("GOOGLE_API_KEY", "test-google-key")

    from llm.client import get_llm
    from langchain_mistralai import ChatMistralAI

    model = get_llm("simple")
    assert isinstance(model, ChatMistralAI)


# =============================================================================
# Fallback: Mistral Large fails → Gemini Flash
# =============================================================================


def test_fallback_to_gemini_on_mistral_failure():
    """``get_llm("complex")`` returns Gemini when Mistral Large raises."""
    os.environ.setdefault("MISTRAL_API_KEY", "test-mistral-key")
    os.environ.setdefault("GOOGLE_API_KEY", "test-google-key")

    from llm.client import get_llm
    from langchain_google_genai import ChatGoogleGenerativeAI

    # Patch the registry entry for "complex" so the factory raises.
    with mock.patch.dict(
        f"{_MODULE}._REGISTRY",
        {"complex": mock.MagicMock(side_effect=Exception("Mistral API down"))},
    ):
        model = get_llm("complex")
        assert isinstance(model, ChatGoogleGenerativeAI)
