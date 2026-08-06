'''python
"""Ollama Python client wrapper.
Provides a thin, user‑friendly API around the Ollama HTTP endpoints.
All network calls are performed with the ``requests`` library (sync) –
for async usage you can replace with ``httpx``.
"""

import os
import json
from typing import List, Dict, Any, Optional
import requests

DEFAULT_HOST = os.getenv("OLLAMA_HOST", "http://localhost")
DEFAULT_PORT = int(os.getenv("OLLAMA_PORT", "11434"))
BASE_URL = f"{DEFAULT_HOST}:{DEFAULT_PORT}"  # e.g. http://localhost:11434

class OllamaClient:
    def __init__(self, base_url: str = BASE_URL, timeout: int = 30):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.session = requests.Session()

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def list_models(self) -> List[Dict[str, Any]]:
        """Return a list of available models (``/api/tags``)."""
        resp = self.session.get(self._url("/api/tags"), timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return data.get("models", [])

    def pull_model(self, name: str, stream: bool = False) -> Any:
        """Pull a model from the Ollama registry.
        If ``stream`` is ``True`` the raw streaming response is returned.
        """
        payload = {"name": name, "stream": stream}
        resp = self.session.post(self._url("/api/pull"), json=payload, timeout=self.timeout, stream=stream)
        resp.raise_for_status()
        if stream:
            return resp.iter_lines()
        return resp.json()

    def delete_model(self, name: str) -> Dict[str, Any]:
        payload = {"name": name}
        resp = self.session.delete(self._url("/api/delete"), json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def generate(self, prompt: str, model: str = "qwen2:0.5b", stream: bool = False, **options) -> Any:
        payload = {"model": model, "prompt": prompt, **options}
        resp = self.session.post(self._url("/api/generate"), json=payload, timeout=self.timeout, stream=stream)
        resp.raise_for_status()
        if stream:
            return resp.iter_lines()
        return resp.json()

    def chat(self, messages: List[Dict[str, str]], model: str = "qwen2:0.5b", stream: bool = False, **options) -> Any:
        payload = {"model": model, "messages": messages, **options}
        resp = self.session.post(self._url("/api/chat"), json=payload, timeout=self.timeout, stream=stream)
        resp.raise_for_status()
        if stream:
            return resp.iter_lines()
        return resp.json()

    def embeddings(self, model: str, input: List[str], **options) -> Dict[str, Any]:
        payload = {"model": model, "input": input, **options}
        resp = self.session.post(self._url("/api/embeddings"), json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def health(self) -> Dict[str, Any]:
        resp = self.session.get(self._url("/api/health"), timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

# Simple usage example (will be removed from production library)
if __name__ == "__main__":
    client = OllamaClient()
    print("Available models:", client.list_models())
    # Example generate call
    print("Generate example:", client.generate(prompt="Hello, world!", model="qwen2:0.5b"))
'''
