"""
HuggingFace Ollama Bridge Client
Wraps a custom HF Space bridge endpoint so it behaves like the local
Ollama Python client used throughout the agent codebase.

Endpoint: https://dany00786-ollama.hf.space
  POST /chat  {"prompt": "..."}  → {"response": "..."}
  POST /api/chat  (Ollama-native JSON format) – also tried as fallback
"""

import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

HF_BRIDGE_URL = "https://dany00786-ollama.hf.space"


class HFBridgeClient:
    """
    Drop-in replacement for ollama.Client that forwards calls to the
    HuggingFace Space bridge endpoint.
    """

    def __init__(self, host: str = HF_BRIDGE_URL, timeout: int = 120):
        self.host = host.rstrip("/")
        self.timeout = timeout
        logger.info(f"HFBridgeClient initialised → {self.host}")

    # ------------------------------------------------------------------ #
    #  chat()  — mirrors ollama.Client.chat(model, messages, options)     #
    # ------------------------------------------------------------------ #
    def chat(self, model: str, messages: list, options: Optional[dict] = None, format: Optional[str] = None) -> dict:
        """
        Forward a chat call to the HF bridge.

        The bridge only accepts a flat "prompt" string, so we convert
        the OpenAI-style messages array into a single prompt string,
        call /chat, and wrap the response to look like an Ollama reply.
        """
        # Build prompt from messages list
        prompt_parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                prompt_parts.append(f"[System]: {content}")
            elif role == "user":
                prompt_parts.append(f"[User]: {content}")
            elif role == "assistant":
                prompt_parts.append(f"[Assistant]: {content}")
        
        prompt = "\n\n".join(prompt_parts)
        
        # If JSON format is requested, add explicit instruction
        if format == "json":
            prompt += "\n\nIMPORTANT: Your response MUST be valid JSON only, with no extra text."

        payload = {"prompt": prompt}

        try:
            resp = requests.post(
                f"{self.host}/chat",
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            response_text = data.get("response", "")
        except Exception as e:
            logger.error(f"HF bridge /chat request failed: {e}")
            raise

        # Return in Ollama-compatible format
        return {
            "message": {
                "role": "assistant",
                "content": response_text,
            },
            "model": model,
            "done": True,
        }

    # ------------------------------------------------------------------ #
    #  embeddings()  — mirrors ollama.Client.embeddings(model, prompt)    #
    #  The HF bridge doesn't have an embeddings endpoint, so we fall      #
    #  back to the local Ollama instance for embeddings only.             #
    # ------------------------------------------------------------------ #
    def embeddings(self, model: str, prompt: str) -> dict:
        """
        Embeddings are not supported by the HF bridge, so we fall back
        to the local Ollama for this call (used by the RAG/ChromaDB layer).
        """
        import ollama
        local_client = ollama.Client(host="http://localhost:11434")
        return local_client.embeddings(model=model, prompt=prompt)
