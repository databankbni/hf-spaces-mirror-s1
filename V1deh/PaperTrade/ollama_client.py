"""
ollama_client.py - Wrapper for calling Ollama (local LLM fallback).

Reuses existing Ollama space deployed separately on HF Spaces.
Provides health check, model discovery, and chat/generate methods.
"""

import logging
import os
import requests
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def check_ollama_health(endpoint: str, timeout: int = 15) -> bool:
    """Ping Ollama endpoint to check if running. Timeout is generous for HF Space cold starts."""
    try:
        resp = requests.get(f"{endpoint}/api/tags", timeout=timeout)
        is_healthy = resp.status_code == 200
        if is_healthy:
            logger.debug(f"Ollama health check passed: {endpoint}")
        else:
            logger.warning(f"Ollama health check failed ({resp.status_code}): {endpoint}")
        return is_healthy
    except Exception as e:
        logger.warning(f"Ollama health check failed: {e}")
        return False


def get_ollama_model(endpoint: str) -> str:
    """Return the model to use: OLLAMA_MODEL env var, else first model from /api/tags, else default."""
    env_model = os.environ.get("OLLAMA_MODEL", "").strip()
    if env_model:
        return env_model
    try:
        resp = requests.get(f"{endpoint}/api/tags", timeout=10)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            if models:
                return models[0]["name"]
    except Exception as e:
        logger.debug(f"Ollama model discovery failed: {e}")
    return "llama3.2:1b"


def ollama_chat(
    messages: List[Dict],
    endpoint: str,
    model: Optional[str] = None,
    timeout: int = 60,
    json_mode: bool = True,
) -> Optional[str]:
    """Call Ollama /api/chat with proper chat message format. Returns assistant text or None.
    json_mode=True adds format='json' to constrain output to valid JSON structure."""
    if model is None:
        model = get_ollama_model(endpoint)
    try:
        payload = {"model": model, "messages": messages, "stream": False}
        if json_mode:
            payload["format"] = "json"
        resp = requests.post(
            f"{endpoint}/api/chat",
            json=payload,
            timeout=timeout,
        )
        if resp.status_code == 200:
            content = resp.json().get("message", {}).get("content", "").strip()
            if content:
                logger.debug(f"Ollama chat ({model}) returned {len(content)} chars")
                return content
            else:
                logger.warning(f"Ollama chat ({model}) returned empty content")
        else:
            logger.warning(f"Ollama chat ({model}) status {resp.status_code}: {resp.text[:200]}")
    except requests.exceptions.Timeout:
        logger.warning(f"Ollama chat ({model}) timeout after {timeout}s")
    except Exception as e:
        logger.warning(f"Ollama chat ({model}) call failed: {e}")
    return None


def warmup_ollama(endpoint: str, model: Optional[str] = None, timeout: int = 30) -> bool:
    """Send a 1-token inference call to force model loading before a real call.
    Returns True if model responded (warm), False if cold-start timed out.
    Use after a fresh health check to avoid hanging 45s on the real inference."""
    if model is None:
        model = get_ollama_model(endpoint)
    try:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Hi"}],
            "stream": False,
            "options": {"num_predict": 1},
        }
        resp = requests.post(f"{endpoint}/api/chat", json=payload, timeout=timeout)
        if resp.status_code == 200:
            logger.debug("Ollama warmup (%s) succeeded", model)
            return True
        logger.debug("Ollama warmup (%s) status %d", model, resp.status_code)
        return False
    except requests.exceptions.Timeout:
        logger.warning("Ollama warmup (%s) timed out after %ds — model still cold", model, timeout)
        return False
    except Exception as e:
        logger.debug("Ollama warmup failed: %s", e)
        return False


def ollama_generate(
    prompt: str,
    endpoint: str,
    model: str = "llama3.2:1b",
    timeout: int = 30
) -> Optional[str]:
    """Call Ollama /api/generate (text completion). Prefer ollama_chat for chat messages."""
    try:
        resp = requests.post(
            f"{endpoint}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=timeout
        )
        if resp.status_code == 200:
            result = resp.json().get("response", "").strip()
            if result:
                logger.debug(f"Ollama ({model}) returned {len(result)} chars")
                return result
            else:
                logger.warning(f"Ollama ({model}) returned empty response")
        else:
            logger.warning(f"Ollama ({model}) status {resp.status_code}: {resp.text[:200]}")
    except requests.exceptions.Timeout:
        logger.warning(f"Ollama ({model}) timeout after {timeout}s")
    except Exception as e:
        logger.warning(f"Ollama ({model}) call failed: {e}")
    return None
