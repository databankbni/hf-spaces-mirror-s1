from __future__ import annotations

import base64
from typing import Any, Dict, List, Optional

import requests

from ..models import Usage
from .base import LLMError, LLMProvider, Reply, request_with_retry

ENDPOINT = "https://api.openai.com/v1/chat/completions"


class OpenAIProvider(LLMProvider):
    name = "openai"

    def complete(self, system: str, user: str, images: Optional[List[bytes]] = None) -> Reply:
        if not self.api_key:
            raise LLMError("no OpenAI API key. Put OPENAI_API_KEY in your .env file.")
        content: List[Dict[str, Any]] = [{"type": "text", "text": user}]
        for img in (images or []):
            b64 = base64.b64encode(img).decode("ascii")
            content.append({"type": "image_url",
                            "image_url": {"url": "data:image/png;base64," + b64}})
        body = {"model": self.model, "temperature": self.temperature,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": content}]}
        r = request_with_retry(lambda: requests.post(
            ENDPOINT, headers={"Authorization": "Bearer " + self.api_key},
            json=body, timeout=self.timeout), "openai")
        if r.status_code != 200:
            raise LLMError("openai {0}: {1}".format(r.status_code, r.text[:400]))
        data = r.json()
        text = data["choices"][0]["message"]["content"]
        u = data.get("usage", {})
        usage = Usage(prompt_tokens=int(u.get("prompt_tokens", 0)),
                      completion_tokens=int(u.get("completion_tokens", 0)),
                      calls=1, model=self.model)
        return Reply(text=text, usage=usage, raw=data)
