from __future__ import annotations

import json
import os
import random
import re
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Callable
from urllib import error, request

from fastapi import HTTPException, status
from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent


def load_env_files(*, override: bool = False) -> None:
    """Load only this app's local .env plus process environment.

    Keep ocr-automation self-contained: do not read ../.env or kgshai env files.
    """
    local_env = PROJECT_DIR / ".env"
    if local_env.exists():
        load_dotenv(local_env, override=override)


load_env_files(override=False)

DEFAULT_OPENROUTER_MODELS = ["qwen3-next-80b-a3b-instruct:free"]
DEFAULT_OLLAMA_CLOUD_MODELS = ["gemini-3-flash-preview", "qwen3.5:397b-cloud"]
DEFAULT_NVIDIA_MODELS = [
    "qwen/qwen3.5-397b-a17b",
    "glm-5.1",
    "glm-4.7",
    "gemma-4-31b-it",
]
NVIDIA_CONTEXT_WINDOW = 1_000_000


def api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value not in (None, "") else default


def default_provider_name() -> str:
    configured = env("OCR_AI_PROVIDER") or env("KGSUI_AI_PROVIDER")
    if configured:
        return configured.strip().lower()
    if _env_key_items(r"^NVAPI\d+$") or env("NVIDIA_API_KEY"):
        return "nvidia"
    if _env_key_items(r"^OLAPI\d+$"):
        return "ollama_cloud"
    if _env_key_items(r"^OPAPI\d+$") or _env_key_items(r"^OPENROUTERAPI\d+$"):
        return "openrouter"
    return "ollama_cloud"


def default_model_name(provider: str | None = None) -> str:
    provider_name = (provider or default_provider_name()).strip().lower()
    if provider_name == "nvidia":
        configured = env("OCR_AI_MODEL") or env("KGSUI_AI_NVIDIA_MODEL") or env("KGSUI_AI_MODEL")
        return configured if configured in DEFAULT_NVIDIA_MODELS else DEFAULT_NVIDIA_MODELS[0]
    if provider_name == "openrouter":
        return env("OCR_AI_MODEL") or env("KGSUI_AI_OPENROUTER_MODEL") or DEFAULT_OPENROUTER_MODELS[0]
    return env("OCR_AI_MODEL") or env("KGSUI_AI_MODEL") or env("OLLAMA_STUDY_MODEL") or "gemini-3-flash-preview"


def ai_timeout_seconds() -> int:
    """Long MCQ generations can take several minutes on cloud LLMs.

    KGSUI often uses 60s, which is too short for a 30k+ char OCR prompt.
    OCR_AI_TIMEOUT_SECONDS overrides everything; otherwise enforce at least
    15 minutes so urllib does not abort while SSE keeps the browser alive.
    """
    raw = env("OCR_AI_TIMEOUT_SECONDS") or env("KGSUI_AI_TIMEOUT_SECONDS") or "900"
    try:
        parsed = int(raw)
    except ValueError:
        parsed = 900
    return max(900, parsed)


@dataclass(frozen=True)
class AiGenerateRequest:
    prompt: str
    provider: str | None = None
    model: str | None = None
    temperature: float | None = None
    event_callback: Callable[[dict[str, Any]], None] | None = None


@dataclass(frozen=True)
class AiGenerateResult:
    text: str
    model: str
    provider: str
    key_mask: str | None = None


class ApiKeyRotator:
    """Random-bag key rotator that avoids using the same key twice in a row when possible."""

    _random = random.SystemRandom()

    def __init__(self, keys: list[str]):
        if not keys:
            raise ValueError("At least one API key is required")
        self._keys = keys
        self._lock = Lock()
        self._bag: list[int] = []
        self._last_index: int | None = None
        self._usage: dict[str, int] = {self.mask(key): 0 for key in keys}

    @staticmethod
    def mask(key: str) -> str:
        if len(key) <= 12:
            return f"{key[:4]}...{key[-2:]}"
        return f"{key[:8]}...{key[-4:]}"

    def _refill_bag_locked(self) -> None:
        self._bag = list(range(len(self._keys)))
        self._random.shuffle(self._bag)
        if len(self._bag) > 1 and self._last_index is not None and self._bag[-1] == self._last_index:
            self._bag[0], self._bag[-1] = self._bag[-1], self._bag[0]

    def next(self) -> tuple[str, str]:
        with self._lock:
            if not self._bag:
                self._refill_bag_locked()
            index = self._bag.pop() if self._bag else 0
            if len(self._keys) > 1 and index == self._last_index and self._bag:
                alt_index = self._bag.pop()
                self._bag.append(index)
                index = alt_index
            self._last_index = index
            key = self._keys[index]
            masked = self.mask(key)
            self._usage[masked] = self._usage.get(masked, 0) + 1
            return key, masked

    def size(self) -> int:
        return len(self._keys)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {"total_keys": len(self._keys), "usage": dict(self._usage), "strategy": "random-bag-no-repeat"}


_ROTATOR_CACHE: dict[tuple[str, tuple[str, ...]], ApiKeyRotator] = {}
_ROTATOR_CACHE_LOCK = Lock()


def _shared_rotator(provider_name: str, keys: list[str]) -> ApiKeyRotator:
    cache_key = (provider_name, tuple(keys))
    with _ROTATOR_CACHE_LOCK:
        rotator = _ROTATOR_CACHE.get(cache_key)
        if rotator is None:
            rotator = ApiKeyRotator(keys)
            _ROTATOR_CACHE[cache_key] = rotator
        return rotator


def _env_key_items(pattern_text: str) -> list[tuple[str, str]]:
    pattern = re.compile(pattern_text)
    matched: list[tuple[str, str]] = []
    for name, value in os.environ.items():
        if pattern.match(name) and value and value.strip():
            matched.append((name, value.strip()))
    return sorted(matched, key=lambda item: item[0])


def _parse_models(raw: str | None, fallback: list[str]) -> list[str]:
    if not raw:
        return list(fallback)
    models = [item.strip() for item in raw.split(",") if item.strip()]
    return models or list(fallback)


def _extract_chat_text(payload: dict[str, Any]) -> str | None:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    message = first.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content.strip() or None
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
            return "\n".join(parts).strip() or None
    text = first.get("text")
    if isinstance(text, str):
        return text.strip() or None
    return None


class BaseAiProvider:
    provider_name = "base"
    display_name = "Base"

    def generate(self, payload: AiGenerateRequest) -> AiGenerateResult:
        raise NotImplementedError

    def status(self) -> dict[str, Any]:
        raise NotImplementedError

    def catalog_entry(self, *, refresh: bool = False) -> dict[str, Any]:
        raise NotImplementedError


class RotatingChatCompletionsProvider(BaseAiProvider):
    target: str
    default_model: str
    available_models: list[str]
    timeout_seconds: int
    referer: str | None = None
    title: str | None = None
    models_endpoint: str | None = None
    strict_models = False
    context_window: int | None = None
    content_window: int | None = None

    def __init__(self, keys: list[str]):
        if not keys:
            raise api_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "ai_keys_missing", f"No API keys configured for provider '{self.provider_name}'")
        self.rotator = _shared_rotator(self.provider_name, keys)
        self._models_cache = list(self.available_models)
        self._models_cache_at = 0.0

    def generate(self, payload: AiGenerateRequest) -> AiGenerateResult:
        requested_model = (payload.model or self.default_model).strip() or self.default_model
        if self.strict_models and requested_model not in self.available_models:
            requested_model = self.default_model
        attempts: list[str] = []
        fallback_model = None if self.strict_models else self.default_model if requested_model != self.default_model else None
        total_attempts = self.rotator.size() + (1 if fallback_model else 0)
        for attempt_index in range(total_attempts):
            current_model = fallback_model if fallback_model and attempt_index >= self.rotator.size() else requested_model
            api_key, key_mask = self.rotator.next()
            if payload.event_callback:
                payload.event_callback(
                    {
                        "type": "model_call",
                        "provider": self.provider_name,
                        "model": current_model,
                        "key_mask": key_mask,
                        "attempt": attempt_index + 1,
                        "total_attempts": total_attempts,
                    }
                )
            try:
                text = self._post_chat(api_key=api_key, model=current_model, prompt=payload.prompt, temperature=payload.temperature, event_callback=payload.event_callback, key_mask=key_mask)
                if payload.event_callback:
                    payload.event_callback(
                        {
                            "type": "model_response",
                            "provider": self.provider_name,
                            "model": current_model,
                            "key_mask": key_mask,
                            "response_chars": len(text),
                        }
                    )
                return AiGenerateResult(text=text, model=current_model, provider=self.provider_name, key_mask=key_mask)
            except error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="ignore")
                attempts.append(f"{key_mask}:{exc.code}")
                retryable = exc.code == 404 and current_model != self.default_model or exc.code in {408, 409, 425, 429, 500, 502, 503, 504}
                if payload.event_callback:
                    payload.event_callback(
                        {
                            "type": "model_retry" if retryable else "model_error",
                            "provider": self.provider_name,
                            "model": current_model,
                            "key_mask": key_mask,
                            "attempt": attempt_index + 1,
                            "status_code": exc.code,
                            "retryable": retryable,
                            "message": body.strip()[:500] or f"HTTP {exc.code}",
                        }
                    )
                if exc.code == 404 and current_model != self.default_model:
                    continue
                if exc.code in {408, 409, 425, 429, 500, 502, 503, 504}:
                    continue
                raise api_error(status.HTTP_502_BAD_GATEWAY, "ai_provider_failed", body.strip() or f"{self.display_name} request failed with status {exc.code}")
            except (TimeoutError, socket.timeout) as exc:
                attempts.append(f"{key_mask}:timeout")
                if payload.event_callback:
                    payload.event_callback(
                        {
                            "type": "model_retry",
                            "provider": self.provider_name,
                            "model": current_model,
                            "key_mask": key_mask,
                            "attempt": attempt_index + 1,
                            "retryable": True,
                            "message": f"Read timed out after {self.timeout_seconds}s: {exc}",
                        }
                    )
                continue
            except error.URLError as exc:
                attempts.append(f"{key_mask}:network")
                if payload.event_callback:
                    payload.event_callback(
                        {
                            "type": "model_retry",
                            "provider": self.provider_name,
                            "model": current_model,
                            "key_mask": key_mask,
                            "attempt": attempt_index + 1,
                            "retryable": True,
                            "message": f"Network error: {exc.reason}",
                        }
                    )
                continue
        raise api_error(status.HTTP_502_BAD_GATEWAY, "ai_provider_unavailable", f"{self.display_name} request failed after key rotation attempts ({', '.join(attempts) or 'no attempts'})")

    def _post_chat(
        self,
        *,
        api_key: str,
        model: str,
        prompt: str,
        temperature: float | None,
        event_callback: Callable[[dict[str, Any]], None] | None = None,
        key_mask: str | None = None,
    ) -> str:
        stream = event_callback is not None
        payload: dict[str, Any] = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": stream}
        if temperature is not None:
            payload["temperature"] = temperature
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if stream else "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "OCRAutomation/1.0",
        }
        if self.referer:
            headers["HTTP-Referer"] = self.referer
        if self.title:
            headers["X-Title"] = self.title
        req = request.Request(self.target, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        with request.urlopen(req, timeout=self.timeout_seconds) as response:
            if not stream:
                raw = json.loads(response.read().decode("utf-8"))
                text = _extract_chat_text(raw)
                if not text:
                    raise api_error(status.HTTP_502_BAD_GATEWAY, "ai_provider_invalid_response", f"{self.display_name} returned an empty response")
                return text

            parts: list[str] = []
            total_chars = 0
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="ignore").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    item = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = item.get("choices") if isinstance(item, dict) else None
                if not isinstance(choices, list) or not choices:
                    continue
                first = choices[0]
                if not isinstance(first, dict):
                    continue
                delta_obj = first.get("delta") or first.get("message") or {}
                delta = ""
                if isinstance(delta_obj, dict):
                    content = delta_obj.get("content")
                    if isinstance(content, str):
                        delta = content
                    elif isinstance(content, list):
                        delta = "".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
                if not delta:
                    text = first.get("text")
                    if isinstance(text, str):
                        delta = text
                if delta:
                    parts.append(delta)
                    total_chars += len(delta)
                    event_callback(
                        {
                            "type": "token_delta",
                            "provider": self.provider_name,
                            "model": model,
                            "key_mask": key_mask,
                            "delta": delta,
                            "delta_chars": len(delta),
                            "total_chars": total_chars,
                        }
                    )
            text = "".join(parts).strip()
            if not text:
                raise api_error(status.HTTP_502_BAD_GATEWAY, "ai_provider_invalid_response", f"{self.display_name} returned an empty streamed response")
            return text

    def _fetch_remote_models(self) -> list[str]:
        if not self.models_endpoint:
            return list(self.available_models)
        api_key, _ = self.rotator.next()
        headers = {"Accept": "application/json", "Authorization": f"Bearer {api_key}", "User-Agent": "OCRAutomation/1.0"}
        req = request.Request(self.models_endpoint, headers=headers)
        with request.urlopen(req, timeout=self.timeout_seconds) as response:
            raw = json.loads(response.read().decode("utf-8"))
        data = raw.get("data") if isinstance(raw, dict) else None
        if not isinstance(data, list):
            return list(self.available_models)
        models = [item.get("id") for item in data if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("id").strip()]
        return models or list(self.available_models)

    def get_models(self, *, refresh: bool = False) -> list[str]:
        if not refresh and self._models_cache and (time.time() - self._models_cache_at) < 300:
            return list(self._models_cache)
        try:
            models = self._fetch_remote_models()
        except Exception:
            models = list(self._models_cache or self.available_models)
        self._models_cache = models
        self._models_cache_at = time.time()
        return list(models)

    def status(self) -> dict[str, Any]:
        entry: dict[str, Any] = {"provider": self.provider_name, "label": self.display_name, "target": self.target, "default_model": self.default_model, "models": self.get_models(refresh=False), **self.rotator.stats()}
        if self.context_window:
            entry["context_window"] = self.context_window
        if self.content_window:
            entry["content_window"] = self.content_window
        return entry

    def catalog_entry(self, *, refresh: bool = False) -> dict[str, Any]:
        entry: dict[str, Any] = {"provider": self.provider_name, "label": self.display_name, "default_model": self.default_model, "models": self.get_models(refresh=refresh), "configured": True, "target": self.target, "key_count": self.rotator.size()}
        if self.context_window:
            entry["context_window"] = self.context_window
        if self.content_window:
            entry["content_window"] = self.content_window
        return entry


class OllamaCloudProvider(BaseAiProvider):
    provider_name = "ollama_cloud"
    display_name = "Ollama Cloud"

    def __init__(self):
        self.target = (env("OCR_AI_OLLAMA_TARGET") or env("KGSUI_AI_OLLAMA_TARGET") or env("OLLAMA_TARGET") or "https://ollama.com").rstrip("/")
        self.default_model = default_model_name("ollama_cloud")
        self.available_models = _parse_models(env("OCR_AI_OLLAMA_MODELS") or env("KGSUI_AI_OLLAMA_MODELS"), DEFAULT_OLLAMA_CLOUD_MODELS)
        self.timeout_seconds = ai_timeout_seconds()
        raw_keys = [value for _, value in _env_key_items(r"^OLAPI\d+$")]
        if not raw_keys:
            raw_keys = [value for _, value in _env_key_items(r"^KGSUI_AI_OLLAMA_KEY_\d+$")]
        if not raw_keys:
            raise api_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "ai_keys_missing", "No Ollama Cloud API keys configured. Add OLAPI1, OLAPI2, ...")
        self.rotator = _shared_rotator(self.provider_name, raw_keys)
        self._models_cache = list(self.available_models)
        self._models_cache_at = 0.0

    def generate(self, payload: AiGenerateRequest) -> AiGenerateResult:
        requested_model = (payload.model or self.default_model).strip() or self.default_model
        attempts: list[str] = []
        fallback_model = self.default_model if requested_model != self.default_model else None
        total_attempts = self.rotator.size() + (1 if fallback_model else 0)
        for attempt_index in range(total_attempts):
            current_model = fallback_model if fallback_model and attempt_index >= self.rotator.size() else requested_model
            api_key, key_mask = self.rotator.next()
            if payload.event_callback:
                payload.event_callback(
                    {
                        "type": "model_call",
                        "provider": self.provider_name,
                        "model": current_model,
                        "key_mask": key_mask,
                        "attempt": attempt_index + 1,
                        "total_attempts": total_attempts,
                    }
                )
            try:
                text = self._post_generate(api_key=api_key, model=current_model, prompt=payload.prompt, temperature=payload.temperature, event_callback=payload.event_callback, key_mask=key_mask)
                if payload.event_callback:
                    payload.event_callback(
                        {
                            "type": "model_response",
                            "provider": self.provider_name,
                            "model": current_model,
                            "key_mask": key_mask,
                            "response_chars": len(text),
                        }
                    )
                return AiGenerateResult(text=text, model=current_model, provider=self.provider_name, key_mask=key_mask)
            except error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="ignore")
                attempts.append(f"{key_mask}:{exc.code}")
                retryable = exc.code == 404 and current_model != self.default_model or exc.code in {408, 409, 425, 429, 500, 502, 503, 504}
                if payload.event_callback:
                    payload.event_callback(
                        {
                            "type": "model_retry" if retryable else "model_error",
                            "provider": self.provider_name,
                            "model": current_model,
                            "key_mask": key_mask,
                            "attempt": attempt_index + 1,
                            "status_code": exc.code,
                            "retryable": retryable,
                            "message": body.strip()[:500] or f"HTTP {exc.code}",
                        }
                    )
                if exc.code == 404 and current_model != self.default_model:
                    continue
                if exc.code in {408, 409, 425, 429, 500, 502, 503, 504}:
                    continue
                raise api_error(status.HTTP_502_BAD_GATEWAY, "ai_provider_failed", body.strip() or f"{self.display_name} request failed with status {exc.code}")
            except (TimeoutError, socket.timeout) as exc:
                attempts.append(f"{key_mask}:timeout")
                if payload.event_callback:
                    payload.event_callback(
                        {
                            "type": "model_retry",
                            "provider": self.provider_name,
                            "model": current_model,
                            "key_mask": key_mask,
                            "attempt": attempt_index + 1,
                            "retryable": True,
                            "message": f"Read timed out after {self.timeout_seconds}s: {exc}",
                        }
                    )
                continue
            except error.URLError as exc:
                attempts.append(f"{key_mask}:network")
                if payload.event_callback:
                    payload.event_callback(
                        {
                            "type": "model_retry",
                            "provider": self.provider_name,
                            "model": current_model,
                            "key_mask": key_mask,
                            "attempt": attempt_index + 1,
                            "retryable": True,
                            "message": f"Network error: {exc.reason}",
                        }
                    )
                continue
        raise api_error(status.HTTP_502_BAD_GATEWAY, "ai_provider_unavailable", f"{self.display_name} request failed after key rotation attempts ({', '.join(attempts) or 'no attempts'})")

    def _post_generate(
        self,
        *,
        api_key: str,
        model: str,
        prompt: str,
        temperature: float | None,
        event_callback: Callable[[dict[str, Any]], None] | None = None,
        key_mask: str | None = None,
    ) -> str:
        stream = event_callback is not None
        payload: dict[str, Any] = {"model": model, "prompt": prompt, "stream": stream}
        if temperature is not None:
            payload["options"] = {"temperature": temperature}
        req = request.Request(
            f"{self.target}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/x-ndjson" if stream else "application/json", "Authorization": f"Bearer {api_key}", "User-Agent": "OCRAutomation/1.0"},
            method="POST",
        )
        with request.urlopen(req, timeout=self.timeout_seconds) as response:
            if not stream:
                raw = json.loads(response.read().decode("utf-8"))
                text = raw.get("response")
                if not isinstance(text, str) or not text.strip():
                    raise api_error(status.HTTP_502_BAD_GATEWAY, "ai_provider_invalid_response", f"{self.display_name} returned an empty response")
                return text.strip()

            parts: list[str] = []
            total_chars = 0
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    if line.startswith("data:"):
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            item = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                    else:
                        continue
                delta = item.get("response") if isinstance(item, dict) else None
                if isinstance(delta, str) and delta:
                    parts.append(delta)
                    total_chars += len(delta)
                    event_callback(
                        {
                            "type": "token_delta",
                            "provider": self.provider_name,
                            "model": model,
                            "key_mask": key_mask,
                            "delta": delta,
                            "delta_chars": len(delta),
                            "total_chars": total_chars,
                        }
                    )
                if isinstance(item, dict) and item.get("done"):
                    break
            text = "".join(parts).strip()
            if not text:
                raise api_error(status.HTTP_502_BAD_GATEWAY, "ai_provider_invalid_response", f"{self.display_name} returned an empty streamed response")
            return text

    def _fetch_remote_models(self) -> list[str]:
        api_key, _ = self.rotator.next()
        req = request.Request(f"{self.target}/api/tags", headers={"Accept": "application/json", "Authorization": f"Bearer {api_key}", "User-Agent": "OCRAutomation/1.0"})
        with request.urlopen(req, timeout=self.timeout_seconds) as response:
            raw = json.loads(response.read().decode("utf-8"))
        models = raw.get("models") if isinstance(raw, dict) else None
        if not isinstance(models, list):
            return list(self.available_models)
        names = [item.get("name") for item in models if isinstance(item, dict) and isinstance(item.get("name"), str) and item.get("name").strip()]
        return names or list(self.available_models)

    def get_models(self, *, refresh: bool = False) -> list[str]:
        if not refresh and self._models_cache and (time.time() - self._models_cache_at) < 300:
            return list(self._models_cache)
        try:
            models = self._fetch_remote_models()
        except Exception:
            models = list(self._models_cache or self.available_models)
        self._models_cache = models
        self._models_cache_at = time.time()
        return list(models)

    def status(self) -> dict[str, Any]:
        return {"provider": self.provider_name, "label": self.display_name, "target": self.target, "default_model": self.default_model, "models": self.get_models(refresh=False), **self.rotator.stats()}

    def catalog_entry(self, *, refresh: bool = False) -> dict[str, Any]:
        return {"provider": self.provider_name, "label": self.display_name, "default_model": self.default_model, "models": self.get_models(refresh=refresh), "configured": True, "target": self.target, "key_count": self.rotator.size()}


class OpenRouterProvider(RotatingChatCompletionsProvider):
    provider_name = "openrouter"
    display_name = "OpenRouter"

    def __init__(self):
        self.target = (env("OCR_AI_OPENROUTER_TARGET") or env("KGSUI_AI_OPENROUTER_TARGET") or "https://openrouter.ai/api/v1/chat/completions").rstrip("/")
        self.models_endpoint = "https://openrouter.ai/api/v1/models"
        self.default_model = env("OCR_AI_OPENROUTER_MODEL") or env("KGSUI_AI_OPENROUTER_MODEL") or DEFAULT_OPENROUTER_MODELS[0]
        self.available_models = _parse_models(env("OCR_AI_OPENROUTER_MODELS") or env("KGSUI_AI_OPENROUTER_MODELS"), DEFAULT_OPENROUTER_MODELS)
        self.timeout_seconds = ai_timeout_seconds()
        self.referer = env("KGSUI_AI_OPENROUTER_SITE_URL") or "http://localhost:4033"
        self.title = env("KGSUI_AI_OPENROUTER_APP_NAME") or "OCRAutomation"
        keys = [value for _, value in _env_key_items(r"^OPAPI\d+$")]
        if not keys:
            keys = [value for _, value in _env_key_items(r"^OPENROUTERAPI\d+$")]
        super().__init__(keys)


class NvidiaProvider(RotatingChatCompletionsProvider):
    provider_name = "nvidia"
    display_name = "NVIDIA"
    strict_models = True
    context_window = NVIDIA_CONTEXT_WINDOW
    content_window = NVIDIA_CONTEXT_WINDOW

    def __init__(self):
        self.target = (env("OCR_AI_NVIDIA_TARGET") or env("KGSUI_AI_NVIDIA_TARGET") or "https://integrate.api.nvidia.com/v1/chat/completions").rstrip("/")
        self.models_endpoint = None
        self.available_models = list(DEFAULT_NVIDIA_MODELS)
        self.default_model = default_model_name("nvidia")
        self.timeout_seconds = ai_timeout_seconds()
        keys = [value for _, value in _env_key_items(r"^NVAPI\d+$")]
        if not keys:
            keys = [value for _, value in _env_key_items(r"^KGSUI_AI_NVIDIA_KEY_\d+$")]
        fallback = (env("NVIDIA_API_KEY") or "").strip()
        if fallback and fallback not in keys:
            keys.append(fallback)
        super().__init__(keys)


class AiService:
    def __init__(self):
        load_env_files(override=False)
        self._providers = self._build_providers()

    def _build_providers(self) -> dict[str, BaseAiProvider]:
        providers: dict[str, BaseAiProvider] = {}
        for factory in (OllamaCloudProvider, OpenRouterProvider, NvidiaProvider):
            try:
                provider = factory()
            except Exception:
                continue
            providers[provider.provider_name] = provider
        return providers

    def _resolve_provider(self, provider_name: str | None = None) -> BaseAiProvider:
        selected = (provider_name or default_provider_name()).strip().lower()
        provider = self._providers.get(selected)
        if provider is not None:
            return provider
        available = ", ".join(sorted(self._providers)) or "none"
        raise api_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "ai_provider_unknown", f"Unknown or unavailable AI provider '{selected}'. Available configured providers: {available}")

    def generate_text(
        self,
        *,
        prompt: str,
        provider: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        event_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> AiGenerateResult:
        resolved = self._resolve_provider(provider)
        return resolved.generate(
            AiGenerateRequest(
                prompt=prompt,
                provider=resolved.provider_name,
                model=model,
                temperature=temperature,
                event_callback=event_callback,
            )
        )

    def status(self, provider: str | None = None) -> dict[str, Any]:
        if provider:
            return self._resolve_provider(provider).status()
        return {"default_provider": default_provider_name(), "providers": [item.status() for item in self._providers.values()]}

    def catalog(self, *, refresh: bool = False) -> dict[str, Any]:
        return {"default_provider": default_provider_name(), "default_model": default_model_name(default_provider_name()), "providers": [item.catalog_entry(refresh=refresh) for item in self._providers.values()]}
