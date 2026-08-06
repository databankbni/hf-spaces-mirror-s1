"""
Simulated iOS world — a faithful Python port of PersonalAssistantBench's backing services
(the original Swift task services). Same stores, same semantics, same deliberate quirks:

- Reminders / Calendar / Contacts mirror the real EventKit / Contacts stores.
- `create_calendar_event` does NOT parse the natural-language time; the event
  is always placed one hour from now (the benchmark scores tool selection,
  never the parsed time).
- Messages are drafted, never delivered ("drafted, not sent").
- The personal corpus is a small seeded Mail/Messages index searched by naive
  keyword overlap.
- The page store stands in for "the page the user is viewing" (used by the
  prompt-injection task).
- Web search serves a bundled offline snippet index by default (hermetic
  training); set LIVE_WEB=1 to hit Wikipedia's public API like the original.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple


# ── Date helpers (PersonalAssistantBench's stable near-future anchors) ────────────────────

def today_at(hour: int, now: Optional[datetime] = None) -> datetime:
    base = now or datetime.now()
    return base.replace(hour=hour, minute=0, second=0, microsecond=0)


def tomorrow_at(hour: int, now: Optional[datetime] = None) -> datetime:
    return today_at(hour, now) + timedelta(days=1)


def next_friday_at(hour: int, now: Optional[datetime] = None) -> datetime:
    d = today_at(hour, now)
    for _ in range(8):
        if d.weekday() == 4:  # Friday
            return d
        d += timedelta(days=1)
    return d


def format_event_date(dt: datetime) -> str:
    """Match the Swift formatter: "EEEE MMM d 'at' h:mm a"."""
    hour12 = dt.strftime("%I").lstrip("0") or "12"
    return f"{dt.strftime('%A %b')} {dt.day} at {hour12}:{dt.strftime('%M %p')}"


# ── The world ────────────────────────────────────────────────────────────────

@dataclass
class PersonalDoc:
    source: str
    date: str
    title: str
    body: str


@dataclass
class IOSWorld:
    """All device state for one episode."""

    reminders: List[str] = field(default_factory=list)
    events: List[Tuple[str, datetime]] = field(default_factory=list)
    contacts: List[str] = field(default_factory=list)
    message_draft: Optional[Dict[str, str]] = None
    personal_corpus: List[PersonalDoc] = field(default_factory=list)
    page_text: str = ""

    SAMPLE_REMINDERS = ["Buy milk", "Call the dentist", "Pay the rent"]

    def reset(self) -> None:
        self.reminders.clear()
        self.events.clear()
        self.contacts.clear()
        self.message_draft = None
        self.personal_corpus.clear()
        self.page_text = ""

    # Reminders (EventKit semantics)
    def create_reminder(self, title: str) -> None:
        self.reminders.append(title)

    def delete_all_reminders(self) -> None:
        self.reminders.clear()

    def seed_sample_reminders(self) -> None:
        for t in self.SAMPLE_REMINDERS:
            self.create_reminder(t)

    # Calendar (EventKit semantics)
    def create_event(self, title: str, start: datetime) -> None:
        self.events.append((title, start))

    def events_snapshot(self) -> List[Tuple[str, datetime]]:
        """Events in a -1d .. +21d window around now, like CalendarService."""
        now = datetime.now()
        lo, hi = now - timedelta(days=1), now + timedelta(days=21)
        return [(t, s) for (t, s) in self.events if lo <= s <= hi]

    # Contacts (CNContact semantics — never bulk-wiped in PersonalAssistantBench; here the
    # whole world is per-episode so reset() is safe)
    def ensure_contact(self, name: str) -> None:
        if name not in self.contacts:
            self.contacts.append(name)

    def create_contact(self, name: str) -> None:
        self.contacts.append(name)

    # Personal corpus (naive keyword-overlap ranking, ported verbatim)
    def search_personal(self, query: str, limit: int = 3) -> List[PersonalDoc]:
        terms = [
            t for t in "".join(
                c if (c.isalnum()) else " " for c in query.lower()
            ).split()
            if len(t) > 2
        ]

        def score(d: PersonalDoc) -> int:
            hay = f"{d.title} {d.body} {d.source}".lower()
            return sum(1 for t in terms if t in hay)

        ranked = [(d, score(d)) for d in self.personal_corpus]
        ranked = [r for r in ranked if r[1] > 0]
        ranked.sort(key=lambda r: -r[1])
        return [d for d, _ in ranked[:limit]]


# ── Web search: offline snippet index, optional live Wikipedia ──────────────

_OFFLINE_INDEX_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "web_index.json"
)


def _offline_index() -> List[Dict[str, str]]:
    try:
        with open(_OFFLINE_INDEX_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return []


def web_search(query: str) -> Optional[Dict[str, str]]:
    """Return {title, extract, url} like WebService.search, or None."""
    if os.environ.get("LIVE_WEB") == "1":
        live = _live_wikipedia(query)
        if live:
            return live
    q_terms = set(query.lower().split())
    best, best_score = None, 0
    for page in _offline_index():
        hay = (page["title"] + " " + page.get("keywords", "")).lower()
        s = sum(1 for t in q_terms if t in hay)
        if s > best_score:
            best, best_score = page, s
    if best:
        return {"title": best["title"], "extract": best["extract"], "url": best["url"]}
    return None


def _live_wikipedia(query: str) -> Optional[Dict[str, str]]:  # pragma: no cover
    try:
        q = urllib.parse.quote(query)
        with urllib.request.urlopen(
            "https://en.wikipedia.org/w/api.php?action=query&format=json"
            f"&list=search&srlimit=1&srsearch={q}",
            timeout=10,
        ) as r:
            hits = json.load(r).get("query", {}).get("search", [])
        if not hits:
            return None
        title = hits[0]["title"]
        t = urllib.parse.quote(title)
        with urllib.request.urlopen(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{t}", timeout=10
        ) as r:
            page = json.load(r)
        return {
            "title": title,
            "extract": page.get("extract", ""),
            "url": page.get("content_urls", {}).get("desktop", {}).get(
                "page", f"https://en.wikipedia.org/wiki/{t}"
            ),
        }
    except Exception:
        return None
