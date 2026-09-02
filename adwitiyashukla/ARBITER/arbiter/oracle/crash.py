from __future__ import annotations

from typing import Dict, List

IGNORED_SUBSTRINGS = ("favicon.ico", "DevTools", "Download the React DevTools")


class CrashOracle:
    source = "crash"

    def __init__(self) -> None:
        self.records: List[Dict[str, str]] = []

    def on_page_error(self, message: str) -> None:
        self._add("page_error", message, "hard")

    def on_console(self, level: str, message: str) -> None:
        if level == "error":
            self._add("console_error", message, "notable")

    def on_request_failed(self, url: str, failure: str) -> None:
        self._add("request_failed", "{0} ({1})".format(url, failure), "notable")

    def on_response(self, url: str, status: int) -> None:
        if status >= 500:
            self._add("server_error", "{0} returned {1}".format(url, status), "notable")

    def _add(self, kind: str, message: str, severity: str) -> None:
        if any(s in message for s in IGNORED_SUBSTRINGS):
            return
        self.records.append({"kind": kind, "message": message.strip()[:500], "severity": severity})

    def drain(self, step: int) -> List["object"]:
        from ..models import Signal
        out = [
            Signal(self.source, r["kind"], r["message"], step, r["severity"], {"raw": r["message"]})
            for r in self.records
        ]
        self.records = []
        return out
