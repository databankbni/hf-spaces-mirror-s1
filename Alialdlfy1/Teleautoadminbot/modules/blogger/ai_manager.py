import os
import time
import json
import asyncio
import logging
from typing import Optional, Dict, Any, List, Tuple
from core.secrets.compat import env_names, env_or_secret
import httpx

logger = logging.getLogger(__name__)

GLOBAL_COOLDOWN = 3600
KEY_COOLDOWN = 300
RATE_LIMIT_COOLDOWN = 60
QUOTA_COOLDOWN = 43200
TIMEOUT = 30.0
MODEL_CACHE_TTL = 3600
MODEL_CACHE_RETRY_COOLDOWN = 300
MODEL_404_BLACKLIST_TTL = 6 * 3600
PROVIDER_ORDER = ["gemini", "groq", "openrouter"]
_IRRELEVANT_MODEL_HINTS = (
    "embedding", "imagen", "veo", "tts", "lyria", "live", "robotics",
    "image", "aqa", "learnlm", "whisper", "tts", "stt", "moderation",
    "dall-e", "dalle", "stable-diffusion", "sdxl",
    "audio", "speech", "control", "vision", "preview",
)


def _empty_perf() -> Dict[str, Any]:
    return {
        "started_at": int(time.time()),
        "requests": 0,
        "success": 0,
        "errors": 0,
        "timeouts": 0,
        "rate_limited": 0,
        "auth_failures": 0,
        "latency_ms_total": 0,
        "by_provider": {},
    }


class AllProvidersExhausted(Exception):
    pass


class NoAvailableAIProvider(AllProvidersExhausted):
    pass


def _rank_model(name: str) -> tuple:
    n = name.lower()
    if any(h in n for h in _IRRELEVANT_MODEL_HINTS):
        return (99,)
    if "gemini" in n:
        is_preview = "preview" in n or "-exp" in n or n.endswith("exp")
        if "flash" in n and not is_preview:
            return (1,)
        if "pro" in n and not is_preview:
            return (2,)
        if not is_preview:
            return (3,)
        return (4,)
    stable = 0 if ("stable" in n or "production" in n or "latest" in n) else 1
    fast = 0 if "flash" in n else (0 if "mini" in n else 1)
    context = 0 if "128k" in n or "1m" in n else 1
    return (stable, fast, context)


PROVIDER_CONFIGS = {
    "gemini": {
        "api_base": "https://generativelanguage.googleapis.com/v1beta/models",
        "env_prefix": "GEMINI_KEY_",
        "timeout": 60,
    },
    "groq": {
        "api_base": "https://api.groq.com/openai/v1",
        "env_prefix": "GROQ_KEY_",
        "timeout": 60,
    },
    "openrouter": {
        "api_base": "https://openrouter.ai/api/v1",
        "env_prefix": "OPENROUTER_KEY_",
        "timeout": 60,
    },
}


async def _discover_gemini_models(http: httpx.AsyncClient, api_key: str) -> list:
    url = f"{PROVIDER_CONFIGS['gemini']['api_base']}?key={api_key}&pageSize=200"
    try:
        resp = await http.get(url, timeout=TIMEOUT)
        if resp.status_code != 200:
            return []
        data = resp.json()
        names = []
        for m in data.get("models", []):
            methods = m.get("supportedGenerationMethods", [])
            if "generateContent" not in methods:
                continue
            short = m.get("name", "").split("/")[-1]
            if not short.startswith("gemini"):
                continue
            names.append(short)
        return sorted(set(names), key=_rank_model)
    except Exception:
        return []


async def _discover_openai_models(http: httpx.AsyncClient, base_url: str, api_key: str) -> list:
    url = f"{base_url}/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        resp = await http.get(url, headers=headers, timeout=TIMEOUT)
        if resp.status_code != 200:
            logger.warning(f"{base_url}/models returned {resp.status_code}")
            return []
        data = resp.json()
        models_raw = data.get("data", [])
        names = []
        for m in models_raw:
            mid = m.get("id", "")
            if any(h in mid.lower() for h in ("embedding", "whisper", "tts", "stt", "moderation", "dall-e", "audio", "speech", "vision", "preview")):
                continue
            names.append(mid)
        result = sorted(set(names), key=_rank_model)
        logger.info(f"{base_url}/models: found {len(result)} usable models")
        return result
    except Exception as e:
        logger.warning(f"{base_url}/models: exception: {e}")
        return []


_model_cache: Dict[str, Dict[str, Any]] = {}
_model_cache_lock = asyncio.Lock()


async def get_models(provider: str, http: httpx.AsyncClient, api_key: str, force: bool = False) -> list:
    cfg = PROVIDER_CONFIGS.get(provider)
    if not cfg:
        return []
    now = time.time()
    async with _model_cache_lock:
        cached = _model_cache.get(provider, {})
        if not force and cached.get("models") and (now - cached.get("fetched_at", 0) < MODEL_CACHE_TTL):
            return cached["models"]
        if not force and not cached.get("models") and (now - cached.get("last_attempt", 0) < MODEL_CACHE_RETRY_COOLDOWN):
            return cached.get("models", [])
        cached["last_attempt"] = now
        _model_cache[provider] = cached
    if provider == "gemini":
        fetched = await _discover_gemini_models(http, api_key)
    else:
        fetched = await _discover_openai_models(http, cfg["api_base"], api_key)
    async with _model_cache_lock:
        if fetched:
            _model_cache[provider] = {"models": fetched, "fetched_at": now, "last_attempt": now}
            logger.info(f"{provider}: refreshed model list ({len(fetched)} usable): {fetched[:4]}")
            return fetched
        return _model_cache.get(provider, {}).get("models", [])


def invalidate_model_cache(provider: str = None):
    if provider:
        _model_cache.pop(provider, None)
    else:
        _model_cache.clear()


async def _gemini_chat(http: httpx.AsyncClient, api_key: str, model: str, prompt: str, system: str = None) -> Tuple[int, Any]:
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    url = f"{PROVIDER_CONFIGS['gemini']['api_base']}/{model}:generateContent?key={api_key}"
    resp = await http.post(url, json=body, timeout=TIMEOUT)
    if resp.status_code == 200:
        data = resp.json()
        candidates = data.get("candidates", [])
        if candidates:
            text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            return (200, text)
        return (200, "")
    error_data = {}
    try:
        error_data = resp.json()
    except Exception:
        pass
    error_obj = error_data.get("error", {})
    status = error_obj.get("status", "UNKNOWN")
    message = error_obj.get("message", resp.reason_phrase)
    body_preview = resp.text[:500]
    logger.warning(
        f"Gemini API error: Endpoint={url} Code={resp.status_code} "
        f"GoogleStatus={status} Message={message} Body={body_preview}"
    )
    return (resp.status_code, {"google_status": status, "google_message": message, "body": body_preview})


async def _openai_chat(http: httpx.AsyncClient, base_url: str, api_key: str, model: str, prompt: str, system: str = None) -> Tuple[int, Any]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if "openrouter" in base_url:
        headers["HTTP-Referer"] = "https://t.me/blogger_publisher"
        headers["X-Title"] = "BloggerPublisher"
    body = {
        "model": model,
        "messages": [],
        "temperature": 0.7,
        "max_tokens": 4096,
    }
    if system:
        body["messages"].append({"role": "system", "content": system})
    body["messages"].append({"role": "user", "content": prompt})
    url = f"{base_url}/chat/completions"
    resp = await http.post(url, headers=headers, json=body, timeout=TIMEOUT)
    if resp.status_code == 200:
        data = resp.json()
        choices = data.get("choices", [])
        if choices:
            text = choices[0].get("message", {}).get("content", "")
            return (200, text)
        return (200, "")
    error_data = {}
    try:
        error_data = resp.json()
    except Exception:
        pass
    err = error_data.get("error", {})
    message = err.get("message", resp.reason_phrase)
    body_preview = resp.text[:500]
    provider_label = "OpenRouter" if "openrouter" in base_url else "OpenAI"
    logger.warning(
        f"{provider_label} API error: Endpoint={url} Code={resp.status_code} "
        f"Message={message} Body={body_preview}"
    )
    return (resp.status_code, {"message": message, "body": body_preview})


class AIKeyManager:
    def __init__(self, db):
        self.db = db
        self._env_keys: Dict[str, dict] = {}
        self._keys: Dict[str, dict] = {}
        self._cooldown_until: Dict[str, float] = {}
        self._global_cooldown_until: float = 0.0
        self._provider_index: Dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._perf: Dict[str, Any] = _empty_perf()
        self._load_env_keys_once()
        self._merge_db_keys()
        self._restore_state()
        self._log_startup_summary()

    def _log_startup_summary(self):
        counts: Dict[str, int] = {}
        for k in self._keys.values():
            p = k.get("_provider", "unknown")
            counts[p] = counts.get(p, 0) + 1
        logger.info("Loading AI Providers...")
        providers_created = 0
        for p in PROVIDER_ORDER:
            c = counts.get(p, 0)
            if c:
                logger.info(f"{p.capitalize()} Keys Loaded: {c}")
                providers_created += 1
        logger.info(f"Providers Created: {providers_created}")
        logger.info(f"Total Keys: {len(self._keys)}")
        models_summary = ", ".join(
            f"{p}: {len(_model_cache.get(p, {}).get('models', [])) if _model_cache.get(p, {}).get('models') else 'pending'}"
            for p in PROVIDER_ORDER
        )
        logger.info(f"Models Loaded: {models_summary}")
        logger.info("AI Manager Ready")

    def _load_env_keys_once(self):
        """Scan env vars once at startup. Never called again."""
        self._env_keys = {}
        seen_val: Dict[str, str] = {}
        for provider in PROVIDER_ORDER:
            prefix = PROVIDER_CONFIGS[provider]["env_prefix"]
            prefix_upper = prefix.upper()
            for env_name in env_names(prefix_upper):
                value = env_or_secret(env_name)
                if not value or not env_name.upper().startswith(prefix_upper):
                    continue
                val = value.strip()
                if not val:
                    continue
                if val in seen_val:
                    display = env_name.upper()
                    existing = seen_val[val].upper()
                    logger.warning(f"Dropping duplicate {display} (same value as {existing})")
                    continue
                seen_val[val] = env_name
                display_name = env_name.upper()
                self._env_keys[env_name.lower()] = {
                    "name": display_name,
                    "key": val,
                    "enabled": True,
                    "usage_count": 0,
                    "error_count": 0,
                    "last_used": 0,
                    "added_at": 0,
                    "_source": "env",
                    "_provider": provider,
                }

    def _merge_db_keys(self):
        """Merge DB keys into self._keys (env keys have priority)."""
        self._keys = dict(self._env_keys)
        raw = self.db.get_all_ai_keys()
        seen_vals: set = set(v["key"] for v in self._keys.values() if v.get("key"))
        for kid, kdata in raw.items():
            if not kdata.get("enabled", True):
                continue
            val = kdata.get("key", "")
            if not val or val in seen_vals:
                continue
            seen_vals.add(val)
            kdata["_provider"] = "gemini"
            if "name" not in kdata or not kdata.get("name"):
                kdata["name"] = kid
            self._keys[kid] = kdata

    def _restore_state(self):
        try:
            state = self.db.get_gemini_state()
            self._global_cooldown_until = state.get("global_cooldown_until", 0.0)
            for kid, expires in state.get("per_key_cooldowns", {}).items():
                if expires > time.time():
                    self._cooldown_until[kid] = expires
            self._provider_index = state.get("provider_index", {})
            perf = state.get("perf")
            if isinstance(perf, dict) and perf.get("started_at"):
                base = _empty_perf()
                base.update(perf)
                self._perf = base
            if self._global_cooldown_until > time.time():
                remaining = int(self._global_cooldown_until - time.time())
                logger.info(f"Restored global cooldown: {remaining}s remaining")
        except Exception as e:
            logger.warning(f"Failed to restore AI state: {e}")

    def _persist_state(self):
        try:
            now = time.time()
            per_key = {k: v for k, v in self._cooldown_until.items() if v > now}
            self.db.save_gemini_state({
                "global_cooldown_until": self._global_cooldown_until,
                "per_key_cooldowns": per_key,
                "provider_index": self._provider_index,
                "perf": self._perf,
                "updated_at": int(now),
            })
        except Exception as e:
            logger.warning(f"Failed to persist AI state: {e}")

    def _key_name(self, key_id: str) -> str:
        return self._keys.get(key_id, {}).get("name", key_id.upper())

    def is_global_cooldown_active(self) -> bool:
        return time.time() < self._global_cooldown_until

    def set_global_cooldown(self, seconds: int = GLOBAL_COOLDOWN):
        self._global_cooldown_until = time.time() + seconds
        self._persist_state()
        logger.info(f"Global Cooldown: {seconds}s (until {time.strftime('%H:%M:%S', time.localtime(self._global_cooldown_until))})")

    def get_all_keys_summary(self) -> Dict[str, dict]:
        return dict(self._keys)

    def get_provider_keys(self, provider: str) -> List[Tuple[str, dict]]:
        return [(k, v) for k, v in self._keys.items() if v.get("_provider") == provider]

    def _key_usable(self, kid: str, kdata: dict, now: float) -> bool:
        """A key is usable only when enabled, not in cooldown, and carries a key value."""
        if not kdata.get("enabled", True):
            return False
        if kid in self._cooldown_until and now < self._cooldown_until[kid]:
            return False
        if not kdata.get("key", ""):
            return False
        return True

    def cooldown_remaining(self, key_id: str) -> int:
        """Seconds remaining until a key leaves its cooldown (0 = ready)."""
        until = self._cooldown_until.get(key_id, 0.0)
        if until > time.time():
            return int(until - time.time())
        return 0

    async def record_perf(self, provider: str, ok: bool, latency_ms: int, reason: str = "", key_id: str = None):
        """Track rolling performance statistics (used by AIClient for every API call)."""
        async with self._lock:
            perf = self._perf
            perf["requests"] += 1
            if ok:
                perf["success"] += 1
            else:
                perf["errors"] += 1
            perf["latency_ms_total"] += latency_ms
            if reason == "timeout":
                perf["timeouts"] += 1
            elif reason == "rate":
                perf["rate_limited"] += 1
            elif reason == "auth":
                perf["auth_failures"] += 1
            byp = perf["by_provider"].setdefault(provider, {
                "requests": 0, "success": 0, "errors": 0, "timeouts": 0,
                "rate_limited": 0, "latency_ms_total": 0,
            })
            byp["requests"] += 1
            if ok:
                byp["success"] += 1
            else:
                byp["errors"] += 1
            if reason == "timeout":
                byp["timeouts"] += 1
            elif reason == "rate":
                byp["rate_limited"] += 1
            byp["latency_ms_total"] += latency_ms
            if key_id and key_id in self._keys:
                kd = self._keys[key_id]
                kd["last_latency_ms"] = latency_ms
                kd["last_error_reason"] = reason or ""
                total_lat = kd.get("total_latency_ms", 0) + latency_ms
                kd["total_latency_ms"] = total_lat
                calls = kd.get("usage_count", 0) + kd.get("error_count", 0)
                if calls > 0:
                    kd["avg_latency_ms"] = int(total_lat / calls)
            self._persist_state()

    def get_perf_stats(self) -> Dict[str, Any]:
        perf = {k: v for k, v in self._perf.items()}
        perf["success_rate"] = round((perf["success"] / perf["requests"] * 100), 1) if perf["requests"] else 0.0
        perf["avg_latency_ms"] = int(perf["latency_ms_total"] / perf["requests"]) if perf["requests"] else 0
        return perf

    async def acquire_usable_key(self) -> Optional[Tuple[str, str, str]]:
        async with self._lock:
            self._merge_db_keys()
            if not self._keys:
                logger.warning("No AI keys configured")
                return None
            now = time.time()
            for provider in PROVIDER_ORDER:
                provider_keys = self.get_provider_keys(provider)
                if not provider_keys:
                    continue
                idx = self._provider_index.get(provider, -1)
                for offset in range(len(provider_keys)):
                    key_idx = (idx + 1 + offset) % len(provider_keys)
                    kid, kdata = provider_keys[key_idx]
                    if not self._key_usable(kid, kdata, now):
                        continue
                    api_key = kdata.get("key", "")
                    self._provider_index[provider] = key_idx
                    name = self._key_name(kid)
                    logger.info(f"Using Provider: {provider.capitalize()}")
                    logger.info(f"Using Key: {name}")
                    return (provider, kid, api_key)
                # All keys in this provider are in cooldown, disabled, or invalid
                logger.warning(f"Provider {provider.capitalize()} exhausted")
            cooldown_keys = []
            for kid in self._keys:
                if kid in self._cooldown_until and self._cooldown_until[kid] > now:
                    cooldown_keys.append(self._key_name(kid))
            if cooldown_keys:
                logger.warning(f"All keys in cooldown: {cooldown_keys}")
            return None

    def switch_to_next_key(self, current_kid: str) -> Optional[Tuple[str, str, str]]:
        self._merge_db_keys()
        now = time.time()
        current_provider = self._keys.get(current_kid, {}).get("_provider", "")
        # Try next key in same provider first
        if current_provider:
            provider_keys = self.get_provider_keys(current_provider)
            if provider_keys:
                idx = self._provider_index.get(current_provider, -1)
                for offset in range(len(provider_keys)):
                    key_idx = (idx + 1 + offset) % len(provider_keys)
                    kid, kdata = provider_keys[key_idx]
                    if kid == current_kid:
                        continue
                    if not self._key_usable(kid, kdata, now):
                        continue
                    api_key = kdata.get("key", "")
                    self._provider_index[current_provider] = key_idx
                    logger.info(f"Switching Key: {self._key_name(kid)}")
                    return (current_provider, kid, api_key)
        # Try next provider
        found_current = False
        for provider in PROVIDER_ORDER:
            if not found_current:
                if provider == current_provider:
                    found_current = True
                continue
            provider_keys = self.get_provider_keys(provider)
            if not provider_keys:
                continue
            for kid, kdata in provider_keys:
                if not self._key_usable(kid, kdata, now):
                    continue
                api_key = kdata.get("key", "")
                self._provider_index[provider] = 0
                logger.info(f"Switching Provider: {provider.capitalize()}")
                logger.info(f"Using Key: {self._key_name(kid)}")
                return (provider, kid, api_key)
            continue
        logger.warning("No alternative key available")
        return None

    async def record_success(self, key_id: str):
        async with self._lock:
            if key_id in self._keys:
                self._keys[key_id]["usage_count"] = self._keys[key_id].get("usage_count", 0) + 1
                self._keys[key_id]["last_used"] = int(time.time())
            self.db.increment_ai_key_usage(key_id)
            self._cooldown_until.pop(key_id, None)
            self._persist_state()

    async def record_failure(self, key_id: str, cooldown: int = KEY_COOLDOWN):
        async with self._lock:
            if key_id in self._keys:
                self._keys[key_id]["error_count"] = self._keys[key_id].get("error_count", 0) + 1
            self.db.increment_ai_key_error(key_id)
            self._cooldown_until[key_id] = time.time() + cooldown
            self._persist_state()
            logger.info(f"Key Cooldown: {self._key_name(key_id)} ({cooldown}s)")

    async def record_quota_exhausted(self, key_id: str):
        async with self._lock:
            if key_id in self._keys:
                self._keys[key_id]["error_count"] = self._keys[key_id].get("error_count", 0) + 10
            self.db.increment_ai_key_error(key_id)
            self._cooldown_until[key_id] = time.time() + QUOTA_COOLDOWN
            self._persist_state()
            logger.info(f"Key Cooldown: {self._key_name(key_id)} ({QUOTA_COOLDOWN}s) - quota exhausted")

    async def mark_disabled(self, key_id: str):
        async with self._lock:
            if key_id in self._keys and self._keys[key_id].get("_source") == "env":
                self._keys[key_id]["enabled"] = False
                return
            self.db.set_ai_key_enabled(key_id, False)


class AIClient:
    def __init__(self, key_manager: AIKeyManager):
        self.key_manager = key_manager
        self._http = httpx.AsyncClient(timeout=TIMEOUT)
        self._session_provider: Optional[str] = None
        self._session_kid: Optional[str] = None
        self._session_key: Optional[str] = None
        self._session_model: Optional[str] = None
        self._model_blacklist: Dict[str, float] = {}

    def _model_blacklisted(self, model: str, now: float = None) -> bool:
        now = now or time.time()
        return model in self._model_blacklist and self._model_blacklist[model] > now

    def _blacklist_model(self, model: str, reason: str = ""):
        self._model_blacklist[model] = time.time() + MODEL_404_BLACKLIST_TTL
        logger.warning(
            f"Model blacklisted (temporarily {MODEL_404_BLACKLIST_TTL // 3600}h): {model} "
            f"provider={self._session_provider}. Reason: {reason or '404/not found'}"
        )

    def _endpoint_for(self, provider: str, model: str) -> str:
        if provider == "gemini":
            return f"{PROVIDER_CONFIGS[provider]['api_base']}/{model}:generateContent"
        return f"{PROVIDER_CONFIGS[provider]['api_base']}/chat/completions"

    async def close(self):
        await self._http.aclose()

    async def acquire_session(self) -> bool:
        if self._session_kid:
            # A held session should be dropped if it fell into cooldown
            # (e.g. another concurrent task exhausted it) so we grab a fresh key.
            if self.key_manager.cooldown_remaining(self._session_kid) > 0:
                logger.info(f"Session key {self._session_kid} now in cooldown, releasing session")
                self.release_session()
            else:
                return True
        if self._session_model:
            models = await get_models(self._session_provider, self._http, self._session_key)
            if self._session_model in models:
                return True
            invalidate_model_cache(self._session_provider)
            logger.info(f"Model {self._session_model} absent from refreshed list, re-acquisition may happen")
        result = await self.key_manager.acquire_usable_key()
        if result:
            self._session_provider, self._session_kid, self._session_key = result
            models = await get_models(self._session_provider, self._http, self._session_key)
            usable = [m for m in models if not self._model_blacklisted(m)]
            if usable:
                self._session_model = usable[0]
                logger.info(f"Using Model: {self._session_model}")
            return True
        if not self.key_manager.is_global_cooldown_active():
            self.key_manager.set_global_cooldown()
            logger.error("All providers exhausted. Queue paused.")
        return False

    def release_session(self):
        self._session_provider = None
        self._session_kid = None
        self._session_key = None
        self._session_model = None

    async def _pick_model(self) -> Optional[str]:
        if self._session_model:
            models = await get_models(self._session_provider, self._http, self._session_key)
            if self._session_model in models and not self._model_blacklisted(self._session_model):
                return self._session_model
            invalidate_model_cache(self._session_provider)
            logger.info(f"Model {self._session_model} not found/blacklisted, refreshing list...")
            models = await get_models(self._session_provider, self._http, self._session_key, force=True)
        else:
            models = await get_models(self._session_provider, self._http, self._session_key)
        usable = [m for m in models if not self._model_blacklisted(m)]
        skipped = [m for m in models if self._model_blacklisted(m)]
        if skipped:
            logger.info(f"Skipping {len(skipped)} blacklisted model(s): {skipped[:4]}")
        if usable:
            self._session_model = usable[0]
            logger.info(f"Using Model: {self._session_model}")
            return self._session_model
        return None

    async def _call_api(self, prompt: str, system: str = None) -> Optional[str]:
        provider = self._session_provider
        api_key = self._session_key
        visited_models = set()
        while True:
            model = await self._pick_model()
            if not model:
                logger.warning(f"No usable model for {provider}")
                return None
            if model in visited_models:
                logger.warning(f"All models exhausted for {provider}")
                return None
            visited_models.add(model)
            try:
                started = time.time()
                if provider == "gemini":
                    code, data = await _gemini_chat(self._http, api_key, model, prompt, system)
                else:
                    base_url = PROVIDER_CONFIGS[provider]["api_base"]
                    code, data = await _openai_chat(self._http, base_url, api_key, model, prompt, system)
                latency_ms = int((time.time() - started) * 1000)
            except httpx.TimeoutException:
                latency_ms = int((time.time() - started) * 1000)
                await self.key_manager.record_perf(provider, False, latency_ms, "timeout", self._session_kid)
                logger.warning(f"Timeout on {model}")
                return None
            except Exception as e:
                latency_ms = int((time.time() - started) * 1000)
                await self.key_manager.record_perf(provider, False, latency_ms, "error", self._session_kid)
                logger.warning(f"Error: {e}")
                return None
            if code == 200:
                if data:
                    await self.key_manager.record_success(self._session_kid)
                    await self.key_manager.record_perf(provider, True, latency_ms, "", self._session_kid)
                    return data
                await self.key_manager.record_failure(self._session_kid)
                await self.key_manager.record_perf(provider, False, latency_ms, "empty", self._session_kid)
                logger.warning(
                    f"AI empty response: Provider={provider} Key={self.key_manager._key_name(self._session_kid)} "
                    f"Model={model} Code={code}"
                )
                return None
            if isinstance(data, dict):
                msg = data.get("message") or data.get("google_message") or data.get("google_status") or str(data)
            else:
                msg = str(data)
            body_preview = (data.get("body") or data.get("message") or str(data))[:500] if isinstance(data, dict) else str(data)[:500]
            model_not_found = code == 404 or any(x in msg.lower() for x in ("not found", "model_not_found", "model not found", "unknown model", "deprecated", "disabled"))
            if model_not_found:
                self._blacklist_model(model, msg)
                logger.warning(
                    f"Model excluded (404/not found/deprecated): Provider={provider} "
                    f"Key={self.key_manager._key_name(self._session_kid)} Model={model} "
                    f"Endpoint={self._endpoint_for(provider, model)} Code={code} Body={body_preview}"
                )
                logger.warning("Trying next model...")
                await self.key_manager.record_perf(provider, False, latency_ms, "model_not_found", self._session_kid)
                invalidate_model_cache(provider)
                continue
            if code == 429 or any(x in msg.lower() for x in ("quota", "exhausted", "rate limit", "resource exhausted")):
                name = self.key_manager._key_name(self._session_kid)
                logger.warning(
                    f"Reason=429 (Quota/rate limit): Provider={provider} Key={name} Model={model} "
                    f"Code={code} Body={body_preview}"
                )
                await self.key_manager.record_perf(provider, False, latency_ms, "rate", self._session_kid)
                await self.key_manager.record_quota_exhausted(self._session_kid)
            elif code == 401:
                logger.warning(f"Reason=401 (Invalid API key): Provider={provider} Model={model} Body={body_preview}")
                await self.key_manager.record_perf(provider, False, latency_ms, "auth", self._session_kid)
                await self.key_manager.mark_disabled(self._session_kid)
            elif code == 402:
                # Payment required (e.g. OpenRouter out of credits): the key is NOT broken.
                # Put it on a normal cooldown and simply try the next key.
                name = self.key_manager._key_name(self._session_kid)
                logger.warning(
                    f"Reason=402 (Payment Required / insufficient credits): Provider={provider} Key={name} "
                    f"Model={model} Code={code} Body={body_preview}. Key intact, cooldown then next key."
                )
                await self.key_manager.record_perf(provider, False, latency_ms, "payment", self._session_kid)
                await self.key_manager.record_failure(self._session_kid, KEY_COOLDOWN)
            elif code == 403:
                logger.warning(f"Reason=403 (Forbidden): Provider={provider} Key={self.key_manager._key_name(self._session_kid)} Model={model}")
                await self.key_manager.record_perf(provider, False, latency_ms, "forbidden", self._session_kid)
                await self.key_manager.record_failure(self._session_kid)
            else:
                logger.warning(
                    f"Reason={code}: Provider={provider} Key={self.key_manager._key_name(self._session_kid)} "
                    f"Model={model} Endpoint={self._endpoint_for(provider, model)} Body={body_preview}"
                )
                await self.key_manager.record_perf(provider, False, latency_ms, f"http_{code}", self._session_kid)
                await self.key_manager.record_failure(self._session_kid, RATE_LIMIT_COOLDOWN)
            return None

    async def generate(self, prompt: str, system: str = None) -> Optional[str]:
        visited_keys = set()
        visited_providers = set()
        attempt = 0
        while attempt < 100:
            attempt += 1
            if not self._session_kid or not self._session_key:
                if self.key_manager.is_global_cooldown_active():
                    logger.info("No AI Provider Available")
                    raise NoAvailableAIProvider("Global cooldown is active")
                result = await self.key_manager.acquire_usable_key()
                if result is None:
                    if not self.key_manager.is_global_cooldown_active():
                        self.key_manager.set_global_cooldown()
                    logger.info("No AI Provider Available")
                    raise NoAvailableAIProvider("No AI provider available")
                if result[1] in visited_keys:
                    self.key_manager._cooldown_until[result[1]] = time.time() + 1
                    self.key_manager._persist_state()
                    continue
                self._session_provider, self._session_kid, self._session_key = result
                self._session_model = None
            kid = self._session_kid
            provider = self._session_provider
            if kid in visited_keys:
                self.release_session()
                continue
            visited_keys.add(kid)
            visited_providers.add(provider)
            model = await self._pick_model()
            logger.info(f"Provider={provider}")
            logger.info(f"Key={self.key_manager._key_name(kid)}")
            if model:
                logger.info(f"Model={model}")
            logger.info(f"Attempt={attempt}")
            result = await self._call_api(prompt, system)
            if result is not None:
                return result
            switch = self.key_manager.switch_to_next_key(kid)
            if switch:
                if switch[1] in visited_keys:
                    self.key_manager._cooldown_until[switch[1]] = time.time() + 1
                    self.key_manager._persist_state()
                    self.release_session()
                    continue
                old_provider = self._session_provider
                self._session_provider, self._session_kid, self._session_key = switch
                self._session_model = None
                if switch[0] != old_provider:
                    logger.info(f"Finished Provider={old_provider}")
                continue
            logger.info("Finished Key Rotation")
            logger.info("No AI Provider Available")
            if not self.key_manager.is_global_cooldown_active():
                self.key_manager.set_global_cooldown()
            raise NoAvailableAIProvider("No AI provider available")
        raise NoAvailableAIProvider("Max attempts exceeded")

    async def generate_json(self, prompt: str, system: str = None) -> Optional[dict]:
        text = await self.generate(prompt, system)
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
            logger.warning(f"AI response is not valid JSON, returning raw text")
            return {"raw": text}