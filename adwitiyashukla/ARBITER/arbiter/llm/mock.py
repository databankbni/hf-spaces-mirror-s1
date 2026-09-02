from __future__ import annotations

import hashlib
import json
import os
from typing import List, Optional

from ..models import Usage
from .base import LLMError, LLMProvider, Reply


def _fingerprint(system: str, user: str, images: int) -> str:
    h = hashlib.sha256()
    h.update(system.encode("utf-8", "ignore"))
    h.update(b"\x00")
    h.update(user.encode("utf-8", "ignore"))
    h.update(str(images).encode())
    return h.hexdigest()[:16]


class MockProvider(LLMProvider):

    name = "mock"

    def __init__(self, model: str = "mock", api_key: str = "", trace_dir: str = "traces", **kw):
        super().__init__(model or "mock", api_key, **kw)
        self.trace_dir = trace_dir
        self.scope = "default"
        self._index = 0

    def start_scope(self, scope: str) -> None:
        self.scope = scope
        self._index = 0

    def complete(self, system: str, user: str, images: Optional[List[bytes]] = None) -> Reply:
        path = os.path.join(self.trace_dir, self.scope, "{0:03d}.json".format(self._index))
        if not os.path.exists(path):
            raise LLMError(
                "no recorded reply at {0}. Record a live run first with "
                "`arbiter run --record`, or run with --provider gemini.".format(path))
        with open(path, "r", encoding="utf-8") as fh:
            rec = json.load(fh)
        self._index += 1
        expected = rec.get("fingerprint")
        actual = _fingerprint(system, user, len(images or []))
        if expected and expected != actual:
            print("  [mock] prompt drift at {0} (recorded {1}, now {2})".format(path, expected, actual))
        u = rec.get("usage", {})
        return Reply(text=rec["text"],
                     usage=Usage(prompt_tokens=int(u.get("prompt_tokens", 0)),
                                 completion_tokens=int(u.get("completion_tokens", 0)),
                                 calls=1, model=rec.get("model", self.model)),
                     raw={"replayed_from": path})


class RecordingProvider(LLMProvider):

    name = "recording"

    def __init__(self, inner: LLMProvider, trace_dir: str = "traces"):
        super().__init__(inner.model, inner.api_key)
        self.inner = inner
        self.trace_dir = trace_dir
        self.scope = "default"
        self._index = 0
        self._cleared = False

    def start_scope(self, scope: str) -> None:
        self.scope = scope
        self._index = 0
        self.inner.start_scope(scope)
        self._cleared = False

    def complete(self, system: str, user: str, images: Optional[List[bytes]] = None) -> Reply:
        reply = self.inner.complete(system, user, images)
        out_dir = os.path.join(self.trace_dir, self.scope)
        os.makedirs(out_dir, exist_ok=True)
        if not self._cleared:
            for name in os.listdir(out_dir):
                if name.endswith(".json"):
                    try:
                        os.remove(os.path.join(out_dir, name))
                    except OSError:
                        pass
            self._cleared = True
        with open(os.path.join(out_dir, "{0:03d}.json".format(self._index)), "w", encoding="utf-8") as fh:
            json.dump({
                "fingerprint": _fingerprint(system, user, len(images or [])),
                "model": reply.usage.model or self.inner.model,
                "images": len(images or []),
                "text": reply.text,
                "usage": {"prompt_tokens": reply.usage.prompt_tokens,
                          "completion_tokens": reply.usage.completion_tokens},
            }, fh, indent=2)
        self._index += 1
        return reply
