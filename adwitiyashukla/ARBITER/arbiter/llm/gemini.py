from __future__ import annotations

import base64
from typing import Any, Dict, List, Optional

import requests

from ..models import Usage
from .base import LLMError, LLMProvider, Reply, request_with_retry

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiProvider(LLMProvider):
    name = "gemini"

    def complete(self, system: str, user: str, images: Optional[List[bytes]] = None) -> Reply:
        if not self.api_key:
            raise LLMError("no Gemini API key. Put GEMINI_API_KEY in your .env file.")
        parts: List[Dict[str, Any]] = [{"text": user}]
        for img in (images or []):
            parts.append({"inline_data": {"mime_type": "image/png",
                                          "data": base64.b64encode(img).decode("ascii")}})
        body = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": self.temperature, "maxOutputTokens": 2048},
        }
        r = request_with_retry(lambda: requests.post(
            ENDPOINT.format(model=self.model), params={"key": self.api_key},
            json=body, timeout=self.timeout), "gemini")
        if r.status_code != 200:
            raise LLMError("gemini {0}: {1}".format(r.status_code, r.text[:400]))
        data = r.json()
        try:
            cand = data["candidates"][0]
            text = "".join(p.get("text", "") for p in cand["content"]["parts"])
        except (KeyError, IndexError):
            reason = data.get("promptFeedback") or data.get("candidates")
            raise LLMError("gemini returned no usable text: {0}".format(str(reason)[:300]))
        meta = data.get("usageMetadata", {})
        usage = Usage(prompt_tokens=int(meta.get("promptTokenCount", 0)),
                      completion_tokens=int(meta.get("candidatesTokenCount", 0)),
                      calls=1, model=self.model)
        return Reply(text=text, usage=usage, raw=data)
