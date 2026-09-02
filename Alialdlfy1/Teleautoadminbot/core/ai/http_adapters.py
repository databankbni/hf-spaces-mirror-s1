"""HTTP adapters for the supported P29 providers.

Adapters intentionally receive the selected secret as an argument from AIGateway;
they never read or log environment secrets themselves.
"""
from __future__ import annotations

import json
import re
from typing import Any


class ProviderHTTPError(RuntimeError):
    def __init__(self, message, *, status_code=0, rate_limited=False, transient=False, retry_after_seconds=0):
        super().__init__(message)
        self.status_code = status_code
        self.rate_limited = rate_limited
        self.transient = transient
        self.retry_after_seconds = retry_after_seconds
        self.cooldown_seconds = max(1, int(retry_after_seconds or (60 if rate_limited else 15)))


def _json_from_text(text: str) -> Any:
    text = (text or "").strip()
    # Models sometimes wrap JSON in markdown fences.
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if m:
            return json.loads(m.group(0))
        return {"text": text}


def _raise_response(response) -> None:
    if response.is_success:
        return
    status = int(response.status_code)
    retry_after = response.headers.get("retry-after", "0")
    try:
        retry = float(retry_after)
    except Exception:
        retry = 0
    raise ProviderHTTPError(
        f"provider HTTP {status}",
        status_code=status,
        rate_limited=status == 429,
        transient=status == 429 or status >= 500,
        retry_after_seconds=retry,
    )


def gemini_adapter(api_key: str, payload: dict) -> dict:
    import httpx
    model = payload.get("model", "gemini-2.0-flash")
    prompt = json.dumps(payload, ensure_ascii=False)
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    with httpx.Client(timeout=45) as client:
        response = client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": api_key},
            json=body,
        )
    _raise_response(response)
    data = response.json()
    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    text = "".join(str(p.get("text", "")) for p in parts if isinstance(p, dict))
    result = _json_from_text(text)
    usage = data.get("usageMetadata") or {}
    if isinstance(result, dict):
        result.setdefault("usage", {
            "prompt_tokens": usage.get("promptTokenCount", 0),
            "completion_tokens": usage.get("candidatesTokenCount", 0),
        })
    return result


def _openai_compatible(api_key: str, payload: dict, base_url: str, model: str) -> dict:
    import httpx
    system = payload.get("system") or (
        "Return only a JSON object matching the requested fields. "
        "Do not include markdown fences."
    )
    user = json.dumps(payload, ensure_ascii=False)
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
    }
    with httpx.Client(timeout=45) as client:
        response = client.post(
            base_url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
        )
    _raise_response(response)
    data = response.json()
    content = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    result = _json_from_text(content)
    usage = data.get("usage") or {}
    if isinstance(result, dict):
        result.setdefault("usage", usage)
    return result


def groq_adapter(api_key: str, payload: dict) -> dict:
    return _openai_compatible(
        api_key, payload,
        "https://api.groq.com/openai/v1/chat/completions",
        payload.get("model", "llama-3.3-70b-versatile"),
    )


def openrouter_adapter(api_key: str, payload: dict) -> dict:
    return _openai_compatible(
        api_key, payload,
        "https://openrouter.ai/api/v1/chat/completions",
        payload.get("model", "openai/gpt-4o-mini"),
    )


def register_default_http_adapters(gateway) -> None:
    gateway.register("gemini", gemini_adapter)
    gateway.register("groq", groq_adapter)
    gateway.register("openrouter", openrouter_adapter)
