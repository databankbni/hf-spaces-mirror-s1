from __future__ import annotations

import base64
from typing import Any, Dict, List, Optional

import requests

from ..models import Usage
from .base import LLMError, LLMProvider, Reply, request_with_retry

ENDPOINT = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def complete(self, system: str, user: str, images: Optional[List[bytes]] = None) -> Reply:
        if not self.api_key:
            raise LLMError("no Anthropic API key. Put ANTHROPIC_API_KEY in your .env file.")
        content: List[Dict[str, Any]] = []
        for img in (images or []):
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/png",
                "data": base64.b64encode(img).decode("ascii")}})
        content.append({"type": "text", "text": user})
        body = {"model": self.model, "max_tokens": 2048, "temperature": self.temperature,
                "system": system, "messages": [{"role": "user", "content": content}]}
        r = request_with_retry(lambda: requests.post(
            ENDPOINT, headers={"x-api-key": self.api_key, "anthropic-version": API_VERSION},
            json=body, timeout=self.timeout), "anthropic")
        if r.status_code != 200:
            raise LLMError("anthropic {0}: {1}".format(r.status_code, r.text[:400]))
        data = r.json()
        text = "".join(b.get("text", "") for b in data.get("content", []))
        u = data.get("usage", {})
        usage = Usage(prompt_tokens=int(u.get("input_tokens", 0)),
                      completion_tokens=int(u.get("output_tokens", 0)),
                      calls=1, model=self.model)
        return Reply(text=text, usage=usage, raw=data)
