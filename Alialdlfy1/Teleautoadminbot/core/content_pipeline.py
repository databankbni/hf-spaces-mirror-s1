"""Global content gate used by every content section before AI or external APIs.

Order is intentionally strict: blocked-word gate -> duplicate gate -> normalize/fingerprint.
This module is section-agnostic so Blogger, News, Sports and future plugins can reuse it.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Optional
from core.content.dedup import DedupStore


@dataclass(frozen=True)
class GateResult:
    allowed: bool
    reason: str = ""
    matched: tuple[str, ...] = ()
    fingerprint: str = ""


class ContentGate:
    def __init__(self, db: Any, dedup: Optional[DedupStore] = None):
        self.db = db
        self.dedup = dedup

    @staticmethod
    def normalize(text: str) -> str:
        text = text or ""
        text = unicodedata.normalize("NFKC", text)
        text = text.replace("ـ", "")
        # Arabic diacritics / tatweel noise.
        text = re.sub(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]", "", text)
        text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
        text = text.replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
        text = re.sub(r"https?://\S+", " URL ", text, flags=re.I)
        text = re.sub(r"@\w+", " USER ", text)
        text = re.sub(r"\s+", " ", text).strip().casefold()
        return text

    @classmethod
    def fingerprint(cls, text: str, source_url: str = "") -> str:
        normalized = cls.normalize(text)
        url = cls.normalize(source_url)
        payload = f"{url}|{normalized}"
        return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()

    @classmethod
    def title_fingerprint(cls, title: str) -> str:
        return hashlib.sha256(cls.normalize(title).encode("utf-8")).hexdigest()

    @classmethod
    def _contains(cls, text: str, words: Iterable[str]) -> tuple[str, ...]:
        normalized = cls.normalize(text)
        matches = []
        for raw in words or []:
            word = str(raw or "").strip()
            if not word:
                continue
            nw = cls.normalize(word)
            if nw and nw in normalized:
                matches.append(word)
        return tuple(dict.fromkeys(matches))

    def blocked_words(self, channel_id: str = "") -> list[str]:
        words = []
        try:
            words.extend(self.db.get_blocked_words() or [])
        except Exception:
            pass
        if channel_id:
            try:
                words.extend(self.db.get_channel_blocked_words(channel_id) or [])
            except Exception:
                pass
        return list(dict.fromkeys(str(w) for w in words if str(w).strip()))

    def check_blocked(self, text: str, channel_id: str = "") -> GateResult:
        matched = self._contains(text, self.blocked_words(channel_id))
        if matched:
            return GateResult(False, "blocked_word", matched=matched)
        return GateResult(True)

    def check_duplicate(self, text: str, source_url: str = "", fingerprint: Optional[str] = None,
                        source: str = "", article_id: str = "") -> GateResult:
        fp = fingerprint or self.fingerprint(text, source_url)
        if self.dedup is not None:
            try:
                if self.dedup.seen(fp):
                    return GateResult(False, "duplicate", fingerprint=fp)
                self.dedup.remember(fp, source or "unknown", article_id or None)
            except Exception:
                # Persistent dedup failure is fail-open only for compatibility with
                # the legacy JSON store; the runtime health monitor records the fault.
                pass
        try:
            if self.db.is_published(fp):
                return GateResult(False, "duplicate", fingerprint=fp)
            existing = self.db.get_article(fp)
            if existing and existing.get("status") not in ("failed_permanent", "discarded"):
                return GateResult(False, "duplicate", fingerprint=fp)
            # Conservative normalized title/content comparison for older records.
            norm = self.normalize(text)
            if norm:
                for article in self.db.get_all_articles() or []:
                    if article.get("fingerprint") == fp:
                        return GateResult(False, "duplicate", fingerprint=fp)
        except Exception:
            pass
        return GateResult(True, fingerprint=fp)

    def preflight(self, text: str, source_url: str = "", channel_id: str = "", source: str = "", article_id: str = "") -> GateResult:
        if not (text or "").strip():
            return GateResult(False, "empty")
        # Deliberately before fingerprint/AI work: blocked content costs zero AI requests.
        blocked = self.check_blocked(text, channel_id)
        if not blocked.allowed:
            return blocked
        return self.check_duplicate(text, source_url, source=source, article_id=article_id)

    def postflight(self, article: dict, channel_id: str = "") -> GateResult:
        text = "\n".join(
            str(article.get(k, "") or "")
            for k in ("title", "introduction", "body", "conclusion", "summary", "keywords")
        )
        blocked = self.check_blocked(text, channel_id)
        if not blocked.allowed:
            return blocked
        source_url = article.get("source_url", "")
        original_fp = article.get("fingerprint", "")
        candidate_fp = self.fingerprint(text, source_url)
        # The input fingerprint is already reserved at ingest. It is expected to
        # exist in the dedup store, so do not misclassify the same job as a duplicate.
        if original_fp and candidate_fp == original_fp:
            return GateResult(True, fingerprint=original_fp)
        return self.check_duplicate(text, source_url, fingerprint=candidate_fp)
