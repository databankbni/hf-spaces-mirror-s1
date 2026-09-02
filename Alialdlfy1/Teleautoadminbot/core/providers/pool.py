"""
P29 AI Provider Pool
- Discovers legacy key names without renaming them.
- Rotates keys using least-recently-used selection.
- Applies cooldowns for rate limits/transient failures.
- Keeps provider/key state in memory; persistence can be added to SQLite later.
"""
from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from threading import RLock
import os
import re
from typing import Iterable, Optional
from core.infra.rate_limiter import ProviderLimiter


@dataclass
class KeyState:
    name: str
    value: str
    provider: str
    uses: int = 0
    failures: int = 0
    tokens: int = 0
    cooldown_until: float = 0.0
    last_used: float = 0.0
    rate_key: str = ""

    @property
    def available(self) -> bool:
        return bool(self.value) and monotonic() >= self.cooldown_until


class AIProviderPool:
    """
    Provider/key scheduler. It never requires changing existing secret names.

    Recognized examples:
      GEMINI_KEY_1, GEMINI_KEY_2, ...
      GROQ_KEY_1, GROQ_KEY_2, ...
      OPENROUTER_KEY_1, OPENROUTER_KEY_2, ...
    """
    PATTERNS = {
        "gemini": re.compile(r"^GEMINI_KEY_(\d+)$", re.I),
        "groq": re.compile(r"^GROQ_KEY_(\d+)$", re.I),
        "openrouter": re.compile(r"^OPENROUTER_KEY_(\d+)$", re.I),
    }

    def __init__(self, environ: Optional[dict] = None):
        self._env = environ if environ is not None else os.environ
        self._lock = RLock()
        self._keys: dict[str, list[KeyState]] = {}
        self.limiter = ProviderLimiter()
        self.reload()

    def reload(self) -> None:
        with self._lock:
            self._keys.clear()
            for provider, pattern in self.PATTERNS.items():
                found = []
                for name, value in self._env.items():
                    if pattern.match(name) and value:
                        found.append(KeyState(name=name, value=value, provider=provider, rate_key=name))
                        # Per-key limiter. Defaults are intentionally conservative and
                        # can be tuned per provider/key through environment variables.
                        rate = float(self._env.get(f"P29_RATE_{provider.upper()}_PER_SEC", "2"))
                        capacity = int(self._env.get(f"P29_RATE_{provider.upper()}_CAPACITY", "2"))
                        self.limiter.configure(name, rate, capacity)
                found.sort(key=lambda x: int(pattern.match(x.name).group(1)))
                if found:
                    self._keys[provider] = found

    def providers(self) -> list[str]:
        with self._lock:
            return list(self._keys)

    def key_names(self, provider: str) -> list[str]:
        with self._lock:
            return [k.name for k in self._keys.get(provider.lower(), [])]

    def acquire(self, provider: str) -> Optional[KeyState]:
        """Select the least-used available key; ties go to least recently used.
        The rate limiter is waited on outside the pool lock so another worker can
        still report failures/cooldowns while one key is rate-limited.
        """
        with self._lock:
            candidates = [k for k in self._keys.get(provider.lower(), []) if k.available]
            if not candidates:
                return None
            candidates.sort(key=lambda k: (k.uses, k.last_used))
            selected = candidates[0]
        self.limiter.acquire(selected.name)
        with self._lock:
            selected.uses += 1
            selected.last_used = monotonic()
        return selected

    def report_success(self, key: KeyState, tokens: int = 0) -> None:
        with self._lock:
            key.tokens += max(0, int(tokens or 0))

    def report_failure(self, key: KeyState, cooldown_seconds: int = 30, rate_limited: bool = False) -> None:
        with self._lock:
            key.failures += 1
            # Longer cooldown for explicit rate limits, bounded to avoid permanent lockout.
            cd = max(1, min(3600, cooldown_seconds * (4 if rate_limited else 1)))
            key.cooldown_until = monotonic() + cd

    def choose(self, preferred: Optional[Iterable[str]] = None) -> Optional[KeyState]:
        order = list(preferred or self.providers())
        for provider in order:
            key = self.acquire(provider)
            if key:
                return key
        return None

    def snapshot(self) -> dict:
        with self._lock:
            return {
                p: [
                    {
                        "name": k.name,
                        "uses": k.uses,
                        "failures": k.failures,
                        "tokens": k.tokens,
                        "cooldown": max(0, round(k.cooldown_until - monotonic(), 2)),
                    }
                    for k in keys
                ]
                for p, keys in self._keys.items()
            }
