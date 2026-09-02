from __future__ import annotations

import hashlib
import math
import threading
import time
from collections import deque
from typing import Any
from uuid import uuid4


class MOKPublicIngressGuard:
    """Public admission boundary with no production authority."""

    def __init__(
        self,
        *,
        window_seconds: int = 60,
        max_requests_per_window: int = 3,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")

        if max_requests_per_window <= 0:
            raise ValueError(
                "max_requests_per_window must be positive"
            )

        self.window_seconds = int(window_seconds)
        self.max_requests_per_window = int(
            max_requests_per_window
        )

        self._lock = threading.Lock()
        self._history: dict[str, deque[float]] = {}
        self._admitted_total = 0
        self._rejected_total = 0

    @staticmethod
    def _normalize_identity(client_identity: Any) -> str:
        value = str(client_identity or "unknown").strip()

        if not value:
            return "unknown"

        return value[:512]

    @staticmethod
    def _tokenize_identity(client_identity: str) -> str:
        return hashlib.sha256(
            client_identity.encode(
                "utf-8",
                errors="replace",
            )
        ).hexdigest()[:16]

    def admit(self, client_identity: Any) -> dict[str, Any]:
        identity = self._normalize_identity(client_identity)
        client_token = self._tokenize_identity(identity)
        request_id = uuid4().hex

        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            history = self._history.setdefault(
                client_token,
                deque(),
            )

            while history and history[0] <= cutoff:
                history.popleft()

            if len(history) >= self.max_requests_per_window:
                retry_after = max(
                    1,
                    math.ceil(
                        self.window_seconds
                        - (now - history[0])
                    ),
                )

                self._rejected_total += 1

                return {
                    "allowed": False,
                    "request_id": request_id,
                    "client_token": client_token,
                    "retry_after_seconds": retry_after,
                    "authority": "ADMISSION_ONLY",
                }

            history.append(now)
            self._admitted_total += 1

            return {
                "allowed": True,
                "request_id": request_id,
                "client_token": client_token,
                "retry_after_seconds": 0,
                "authority": "ADMISSION_ONLY",
            }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "component": "MOK_PUBLIC_INGRESS_GUARD",
                "authority": "ADMISSION_ONLY",
                "window_seconds": self.window_seconds,
                "max_requests_per_window": (
                    self.max_requests_per_window
                ),
                "tracked_client_tokens": len(self._history),
                "admitted_total": self._admitted_total,
                "rejected_total": self._rejected_total,
            }
