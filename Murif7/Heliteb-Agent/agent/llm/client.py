"""LLM client factory for the HELITEB commercial agent.

Exposes three pre-configured model instances and a single `get_llm(complexity)`
selector used by the LangGraph nodes.

Tiers
-----
- simple   → Mistral Small     (default; low latency, low cost)
- complex  → Mistral Large     (richer reasoning, longer outputs)
- fallback → Gemini 2.5 Flash  (used when Mistral is unavailable)

Environment
-----------
Required:  MISTRAL_API_KEY, GOOGLE_API_KEY
"""
from __future__ import annotations

import os
from functools import lru_cache

import httpx
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mistralai import ChatMistralAI


_REQUEST_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=5.0, pool=5.0)


@lru_cache(maxsize=1)
def _mistral_small() -> ChatMistralAI:
    """Mistral Small — quick replies, default tier."""
    return ChatMistralAI(
        model="mistral-small-latest",
        temperature=0.2,
        max_tokens=512,
        mistral_api_key=os.environ["MISTRAL_API_KEY"],
        timeout=int(_REQUEST_TIMEOUT.read),
    )


@lru_cache(maxsize=1)
def _mistral_large() -> ChatMistralAI:
    """Mistral Large — complex reasoning, longer outputs."""
    return ChatMistralAI(
        model="mistral-large-latest",
        temperature=0.2,
        max_tokens=1024,
        mistral_api_key=os.environ["MISTRAL_API_KEY"],
        timeout=int(_REQUEST_TIMEOUT.read),
    )


@lru_cache(maxsize=1)
def _gemini_flash() -> ChatGoogleGenerativeAI:
    """Gemini 2.5 Flash — fallback model."""
    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=0.2,
        max_tokens=512,
        google_api_key=os.environ["GOOGLE_API_KEY"],
        timeout=_REQUEST_TIMEOUT.read,
    )


_REGISTRY = {
    "simple": _mistral_small,
    "complex": _mistral_large,
    "fallback": _gemini_flash,
}


def get_llm(complexity: str = "simple"):
    """Return the LLM instance matching the requested complexity tier.

    Args:
        complexity: One of ``"simple"`` (default), ``"complex"``, or ``"fallback"``.

    Returns:
        A LangChain ``BaseChatModel`` ready to invoke.

    Raises:
        ValueError: If ``complexity`` is not a recognised tier.
    """
    try:
        factory = _REGISTRY[complexity]
    except KeyError as exc:
        raise ValueError(
            f"Unknown complexity tier: {complexity!r}. "
            f"Expected one of: {sorted(_REGISTRY)}"
        ) from exc

    if complexity == "complex":
        try:
            return factory()
        except Exception:
            return _gemini_flash()
    return factory()
