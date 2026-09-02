import os
from core.secrets.compat import env_names, env_or_secret
import time
import json
import asyncio
import logging
from typing import Optional, Dict, Any, List

import httpx

logger = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_TIMEOUT = 60.0
KEY_COOLDOWN = 300
RATE_LIMIT_COOLDOWN = 60
QUOTA_COOLDOWN = 43200
GLOBAL_COOLDOWN = 3600  # 1 hour when ALL keys are exhausted

FALLBACK_MODELS = [
    "gemini-flash-latest",
    "gemini-pro-latest",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]

GEMINI_MODELS = FALLBACK_MODELS

MODEL_LIST_CACHE_TTL = 6 * 3600
MODEL_LIST_RETRY_COOLDOWN = 300
_IRRELEVANT_MODEL_HINTS = (
    "embedding", "imagen", "veo", "tts", "lyria", "live", "robotics",
    "image", "aqa", "learnlm",
)

_model_list_cache: Dict[str, Any] = {"models": [], "fetched_at": 0.0, "last_attempt": 0.0}
_model_list_lock = asyncio.Lock()


class AllKeysExhausted(Exception):
    """All Gemini API keys are exhausted (quota / rate-limit / cooldown).
    Raised when no key can serve the request at this moment."""
    pass


def _rank_model(name: str) -> tuple:
    n = name.lower()
    if any(h in n for h in _IRRELEVANT_MODEL_HINTS):
        return (9,)
    is_preview = "preview" in n or "-exp" in n or n.endswith("exp")
    if n in ("gemini-flash-latest", "gemini-pro-latest"):
        return (0,)
    if "flash" in n and not is_preview:
        return (1,)
    if "pro" in n and not is_preview:
        return (2,)
    if not is_preview:
        return (3,)
    return (4,)


async def fetch_live_models(http_client: httpx.AsyncClient, api_key: str) -> list:
    url = f"{GEMINI_API_BASE}?key={api_key}&pageSize=200"
    try:
        resp = await http_client.get(url, timeout=GEMINI_TIMEOUT)
        if resp.status_code != 200:
            logger.warning(f"Gemini model discovery failed: HTTP {resp.status_code} - {resp.text[:200]}")
            return []
        data = resp.json()
        names = []
        for m in data.get("models", []):
            full_name = m.get("name", "")
            methods = m.get("supportedGenerationMethods", [])
            if "generateContent" not in methods:
                continue
            short = full_name.split("/")[-1] if "/" in full_name else full_name
            if not short.startswith("gemini"):
                continue
            names.append(short)
        names = sorted(set(names), key=_rank_model)
        return names
    except Exception as e:
        logger.warning(f"Gemini model discovery error: {e}")
        return []


async def get_live_model_list(http_client: httpx.AsyncClient, api_key: str, force: bool = False) -> list:
    global _model_list_cache
    now = time.time()
    async with _model_list_lock:
        if not force and _model_list_cache["models"] and (now - _model_list_cache["fetched_at"] < MODEL_LIST_CACHE_TTL):
            return _model_list_cache["models"]
        if not force and not _model_list_cache["models"] and (now - _model_list_cache["last_attempt"] < MODEL_LIST_RETRY_COOLDOWN):
            return FALLBACK_MODELS
        _model_list_cache["last_attempt"] = now
        fetched = await fetch_live_models(http_client, api_key)
        if fetched:
            _model_list_cache["models"] = fetched
            _model_list_cache["fetched_at"] = now
            logger.info(f"Gemini: refreshed live model list ({len(fetched)} usable models): {fetched[:6]}")
            return fetched
        logger.warning("Gemini: live discovery returned nothing, using cached/fallback list")
        return _model_list_cache["models"] or FALLBACK_MODELS


def invalidate_model_list_cache():
    _model_list_cache["fetched_at"] = 0.0


class GeminiKeyManager:
    def __init__(self, db):
        self.db = db
        self._keys: Dict[str, dict] = {}
        self._cooldown_until: Dict[str, float] = {}
        self._global_cooldown_until: float = 0.0
        self._lock = asyncio.Lock()
        self._restore_cooldowns()

    def _load_env_keys(self) -> Dict[str, dict]:
        env_keys: Dict[str, dict] = {}
        seen_values: Dict[str, str] = {}
        for key in env_names("GEMINI_KEY_"):
            val = env_or_secret(key)
            if val and val.strip():
                clean_val = val.strip()
                kid = key.lower()
                if clean_val in seen_values:
                    logger.warning(f"Dropping duplicate key {key} (same value as {seen_values[clean_val]})")
                    continue
                seen_values[clean_val] = key
                env_keys[kid] = {
                    "name": key,
                    "key": clean_val,
                    "enabled": True,
                    "usage_count": 0,
                    "error_count": 0,
                    "last_used": 0,
                    "added_at": 0,
                    "_source": "env",
                }
        return env_keys

    def _load_keys(self):
        raw = self.db.get_all_ai_keys()
        env = self._load_env_keys()
        self._keys = {}
        seen_values: set = set()
        for kid, kdata in raw.items():
            if not kdata.get("enabled", True):
                continue
            val = kdata.get("key", "")
            if not val:
                continue
            if val in seen_values:
                logger.warning(f"Dropping duplicate DB key {kid} (same value as another key)")
                continue
            seen_values.add(val)
            self._keys[kid] = kdata
        for kid, kdata in env.items():
            val = kdata.get("key", "")
            if val and val in seen_values:
                logger.warning(f"Dropping duplicate env key {kid} (same value as another key)")
                continue
            if val:
                seen_values.add(val)
            self._keys[kid] = kdata

    def _restore_cooldowns(self):
        try:
            state = self.db.get_gemini_state()
            self._global_cooldown_until = state.get("global_cooldown_until", 0.0)
            for kid, expires in state.get("per_key_cooldowns", {}).items():
                if expires > time.time():
                    self._cooldown_until[kid] = expires
            if self._global_cooldown_until > time.time():
                remaining = int(self._global_cooldown_until - time.time())
                logger.info(f"Restored global cooldown: {remaining}s remaining ({len(self._cooldown_until)} keys in cooldown)")
            elif self._cooldown_until:
                logger.info(f"Restored {len(self._cooldown_until)} per-key cooldowns from DB")
        except Exception as e:
            logger.warning(f"Failed to restore cooldowns: {e}")

    def _persist_cooldowns(self):
        try:
            now = time.time()
            per_key = {k: v for k, v in self._cooldown_until.items() if v > now}
            self.db.save_gemini_state({
                "global_cooldown_until": self._global_cooldown_until,
                "per_key_cooldowns": per_key,
                "updated_at": int(now),
            })
        except Exception as e:
            logger.warning(f"Failed to persist cooldowns: {e}")

    def get_all_keys_summary(self):
        raw = self.db.get_all_ai_keys()
        if not self._keys:
            self._load_keys()
        for kid, kdata in self._keys.items():
            if kdata.get("_source") == "env":
                raw[kid] = kdata
        return raw

    async def acquire_usable_key(self) -> Optional[tuple]:
        """Tries each key one by one (NOT round-robin).
        Skips keys in per-key cooldown.
        Returns the first (kid, api_key) that is available, or None."""
        async with self._lock:
            self._load_keys()
            if not self._keys:
                logger.warning("No Gemini keys configured")
                return None
            now = time.time()
            for kid, kdata in self._keys.items():
                if kid in self._cooldown_until and now < self._cooldown_until[kid]:
                    continue
                api_key = kdata.get("key", "")
                if not api_key:
                    continue
                logger.info(f"Trying {kid}...")
                return (kid, api_key)
            cooldowns = {k: int(self._cooldown_until[k] - now) for k in self._keys
                         if k in self._cooldown_until and self._cooldown_until[k] > now}
            logger.warning(f"All Gemini keys in cooldown: {cooldowns}")
            return None

    def switch_to_next_key(self, current_kid: str) -> Optional[tuple]:
        """Finds the next available key different from current_kid.
        Used when the current session key fails and we need an alternative."""
        self._load_keys()
        now = time.time()
        for kid, kdata in self._keys.items():
            if kid == current_kid:
                continue
            if kid in self._cooldown_until and now < self._cooldown_until[kid]:
                continue
            api_key = kdata.get("key", "")
            if not api_key:
                continue
            logger.info(f"Switching to {kid}...")
            return (kid, api_key)
        return None

    def is_global_cooldown_active(self) -> bool:
        return time.time() < self._global_cooldown_until

    def set_global_cooldown(self, seconds: int = GLOBAL_COOLDOWN):
        self._global_cooldown_until = time.time() + seconds
        self._persist_cooldowns()
        logger.info(f"Global cooldown set for {seconds}s (until {time.strftime('%H:%M:%S', time.localtime(self._global_cooldown_until))})")

    async def record_success(self, key_id: str):
        async with self._lock:
            if key_id in self._keys:
                self._keys[key_id]["usage_count"] = self._keys[key_id].get("usage_count", 0) + 1
                self._keys[key_id]["last_used"] = int(time.time())
            self.db.increment_ai_key_usage(key_id)
            self._cooldown_until.pop(key_id, None)
            self._persist_cooldowns()
            logger.info(f"{key_id} success. Usage recorded, cooldown cleared.")

    async def record_failure(self, key_id: str, cooldown: int = KEY_COOLDOWN):
        async with self._lock:
            if key_id in self._keys:
                self._keys[key_id]["error_count"] = self._keys[key_id].get("error_count", 0) + 1
            self.db.increment_ai_key_error(key_id)
            self._cooldown_until[key_id] = time.time() + cooldown
            self._persist_cooldowns()
            logger.warning(f"{key_id} failure. Cooldown {cooldown}s.")

    async def record_quota_exhausted(self, key_id: str):
        async with self._lock:
            if key_id in self._keys:
                self._keys[key_id]["error_count"] = self._keys[key_id].get("error_count", 0) + 10
            self.db.increment_ai_key_error(key_id)
            self._cooldown_until[key_id] = time.time() + QUOTA_COOLDOWN
            self._persist_cooldowns()
            logger.warning(f"{key_id} quota exhausted. Cooldown {QUOTA_COOLDOWN}s (12h).")

    async def mark_disabled(self, key_id: str):
        async with self._lock:
            if key_id in self._keys and self._keys[key_id].get("_source") == "env":
                self._keys[key_id]["enabled"] = False
                return
            self.db.set_ai_key_enabled(key_id, False)


class GeminiClient:
    def __init__(self, key_manager: GeminiKeyManager):
        self.key_manager = key_manager
        self._http = httpx.AsyncClient(timeout=GEMINI_TIMEOUT)
        self._model_index = 0
        self._session_kid: Optional[str] = None
        self._session_key: Optional[str] = None

    async def close(self):
        await self._http.aclose()

    async def acquire_session(self) -> bool:
        """Lock one key for the entire article processing session.
        Returns True if a working key was found, False if all keys are exhausted."""
        if self._session_kid:
            logger.warning("acquire_session called but session already active")
            return True
        if self.key_manager.is_global_cooldown_active():
            remaining = int(self.key_manager._global_cooldown_until - time.time())
            logger.warning(f"Global cooldown active, {remaining}s remaining. Cannot acquire session.")
            return False
        result = await self.key_manager.acquire_usable_key()
        if result:
            self._session_kid, self._session_key = result
            logger.info(f"Using {self._session_kid} for entire article.")
            return True
        self.key_manager.set_global_cooldown()
        logger.error("All keys exhausted. Queue paused. Retry after 1 hour.")
        return False

    def release_session(self):
        if self._session_kid:
            logger.info(f"Released {self._session_kid}.")
        self._session_kid = None
        self._session_key = None

    async def _switch_session_key(self) -> bool:
        """Called when the current session key fails.
        Tries the next key; if found, updates the session and returns True."""
        old_kid = self._session_kid
        result = self.key_manager.switch_to_next_key(old_kid or "")
        if result:
            self._session_kid, self._session_key = result
            logger.info(f"Session switched: {old_kid} -> {self._session_kid}.")
            return True
        logger.warning(f"Session switch failed: no alternative after {old_kid}.")
        return False

    async def _post_with_models(self, api_key: str, body: dict) -> Optional[tuple]:
        key_preview = api_key[:8] + "..." if len(api_key) > 8 else "(empty)"
        models = await get_live_model_list(self._http, api_key)
        if not models:
            models = FALLBACK_MODELS
        saw_404 = False
        for offset in range(len(models)):
            idx = (self._model_index + offset) % len(models)
            model = models[idx]
            url = f"{GEMINI_API_BASE}/{model}:generateContent?key={api_key}"
            try:
                resp = await self._http.post(url, json=body)
                resp_body = resp.text
                resp_preview = resp_body[:300]

                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        if text:
                            self._model_index = idx
                            return (200, text, model, idx)
                    return (200, "", model, idx)

                error_data = {}
                try:
                    error_data = resp.json()
                except Exception:
                    pass
                error_obj = error_data.get("error", {})
                google_status = error_obj.get("status", "UNKNOWN")
                google_message = error_obj.get("message", resp.reason_phrase)

                if resp.status_code == 404:
                    logger.warning(
                        f"Model '{model}' not found (404) for key {key_preview} "
                        f"(likely retired by Google), trying next. Google: {google_message}"
                    )
                    saw_404 = True
                    continue

                if resp.status_code in (429, 400, 401, 403, 500, 502, 503):
                    log_msg = (
                        f"Key: {key_preview}\n"
                        f"HTTP Status: {resp.status_code}\n"
                        f"Google Status: {google_status}\n"
                        f"Google Message: {google_message}\n"
                        f"Model: {model}\n"
                        f"Endpoint: {GEMINI_API_BASE}/{model}:generateContent?key={key_preview}\n"
                        f"Response: {resp_preview}"
                    )
                    logger.error(f"Gemini API error:\n{log_msg}")
                    return (resp.status_code, {
                        "google_status": google_status,
                        "google_message": google_message,
                        "model": model,
                    }, model, idx)

                logger.warning(
                    f"Unexpected HTTP {resp.status_code} for model '{model}' "
                    f"on key {key_preview}, trying next. Body: {resp_preview}"
                )
                continue

            except httpx.TimeoutException:
                logger.warning(f"Model '{model}' timeout on key {key_preview}, trying next")
                continue
            except Exception as e:
                logger.warning(f"Model '{model}' error on key {key_preview}: {e}, trying next")
                continue
        if saw_404:
            logger.warning("Gemini: every live-listed model 404'd, forcing re-discovery on next attempt")
            invalidate_model_list_cache()
        return None

    def _classify_and_handle_error(self, kid: str, code: int, error_info: dict):
        google_status = error_info.get("google_status", "UNKNOWN")
        google_message = error_info.get("google_message", "")
        model = error_info.get("model", "?")

        if code == 429:
            if google_status == "RESOURCE_EXHAUSTED":
                logger.warning(f"{kid} quota exhausted (RESOURCE_EXHAUSTED) on {model}. Message: {google_message}")
                return self.key_manager.record_quota_exhausted(kid)
            elif google_status == "RATE_LIMIT":
                logger.warning(f"{kid} rate limited on {model}. 60s cooldown. Message: {google_message}")
                return self.key_manager.record_failure(kid, RATE_LIMIT_COOLDOWN)
            else:
                logger.warning(f"{kid} HTTP 429 ({google_status}) on {model}. 60s cooldown. Message: {google_message}")
                return self.key_manager.record_failure(kid, RATE_LIMIT_COOLDOWN)

        if code == 401:
            logger.error(f"{kid} INVALID API KEY (401) on {model}. Disabling key. Message: {google_message}")
            return self.key_manager.mark_disabled(kid)

        if code == 403:
            if google_status in ("ACCESS_NOT_CONFIGURED", "PERMISSION_DENIED", "API_KEY_INVALID"):
                logger.error(f"{kid} ACCESS DENIED ({google_status}) on {model}. Disabling key. Message: {google_message}")
                return self.key_manager.mark_disabled(kid)
            logger.warning(f"{kid} HTTP 403 ({google_status}) on {model}. 5min cooldown. Message: {google_message}")
            return self.key_manager.record_failure(kid, KEY_COOLDOWN)

        if code == 400:
            logger.warning(f"{kid} BAD REQUEST (400) on {model}. 5min cooldown. Message: {google_message}")
            return self.key_manager.record_failure(kid, KEY_COOLDOWN)

        logger.error(f"{kid} HTTP {code} ({google_status}) on {model}. 5min cooldown. Message: {google_message}")
        return self.key_manager.record_failure(kid, KEY_COOLDOWN)

    async def generate(self, prompt: str, system_instruction: str = None) -> Optional[str]:
        """Generate text using the session key if available.
        Raises AllKeysExhausted when no key can serve the request."""
        if self._session_kid and self._session_key:
            kid, api_key = self._session_kid, self._session_key
        else:
            if self.key_manager.is_global_cooldown_active():
                raise AllKeysExhausted("Global cooldown active")
            result = await self.key_manager.acquire_usable_key()
            if result is None:
                self.key_manager.set_global_cooldown()
                raise AllKeysExhausted("No Gemini API keys available")
            kid, api_key = result

        body: Dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 4096,
            },
        }
        if system_instruction:
            body["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        result = await self._post_with_models(api_key, body)
        if result is None:
            invalidate_model_list_cache()
            logger.warning(f"No usable model responded for {kid}; retrying with fresh model list")
            result = await self._post_with_models(api_key, body)
            if result is None:
                if self._session_kid:
                    await self.key_manager.record_failure(kid)
                    if await self._switch_session_key():
                        return await self.generate(prompt, system_instruction)
                else:
                    await self.key_manager.record_failure(kid)
                self.key_manager.set_global_cooldown()
                raise AllKeysExhausted(f"No usable model for {kid}")

        code, data_or_text, model, idx = result
        if code == 200:
            if data_or_text:
                await self.key_manager.record_success(kid)
                logger.info(f"{kid} success on {model}")
                return data_or_text
            await self.key_manager.record_failure(kid)
            logger.warning(f"{kid} returned empty on {model}")
            return None

        error_info = data_or_text if isinstance(data_or_text, dict) else {}
        await self._classify_and_handle_error(kid, code, error_info)

        if self._session_kid:
            if await self._switch_session_key():
                logger.info(f"Retrying with new session key {self._session_kid}...")
                return await self.generate(prompt, system_instruction)
            self.key_manager.set_global_cooldown()
            raise AllKeysExhausted(f"All keys exhausted after {kid}")

        return None

    async def generate_json(self, prompt: str, system_instruction: str = None) -> Optional[dict]:
        text = await self.generate(prompt, system_instruction)
        if not text:
            return None
        text = text.strip()
        if text.startswith("```"):
            for marker in ["```json", "```JSON", "```"]:
                if text.startswith(marker):
                    text = text[len(marker):]
                    break
            end_idx = text.rfind("```")
            if end_idx != -1:
                text = text[:end_idx]
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"Gemini response is not valid JSON, returning raw text")
            return {"raw": text}
