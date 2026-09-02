"""Betting splits — share of handle and share of tickets — from VSiN.

VSiN publishes DraftKings' splits free and on purpose: it's the book using its
own numbers as marketing. That makes this the one source of *money* percentage
we can read without a subscription, and unlike an aggregator's blend it is one
book's actual ledger.

**Why the two numbers together are worth more than either alone.** Share of
tickets says how many people took a side; share of handle says how much money
did. When they agree — 65% of bets and 65% of the money — that's the crowd,
lots of small tickets pointing the same way. When they diverge — 25% of bets
but 65% of the money — that's a few large tickets, which is what sharp money
looks like from outside. Line movement alone cannot tell those two apart: both
push the price the same direction.

**The parsing is header-driven, deliberately.** Which column holds which number
is read off the table's own header row rather than assumed by position, because
a layout change should cost us a column mapping and not a wrong answer. If the
headers don't yield a usable mapping the fetch returns nothing and `diagnose()`
reports what it actually saw. That is the intended failure: a market panel with
no splits on it, never a split pinned to the wrong side.

**Teams are resolved against the slate we already know.** The day's schedule
tells us which teams are playing, so a row's team token only has to be matched
against thirty-odd candidates rather than parsed in the abstract. An
unrecognised token is skipped, because attaching DraftKings' Yankees handle to
the wrong game is worse than showing nothing.

Best-effort throughout, like every other source here: unreachable, reshaped, or
ambiguous all yield nothing.
"""
from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import date as date_type
from typing import Any, Iterable, Optional

import requests

# Overridable without a deploy: if VSiN moves the page, this is the one thing
# that needs to change, and waiting on a code push to fix a URL is silly.
SPLITS_URL = os.environ.get(
    "VSIN_SPLITS_URL", "https://data.vsin.com/mlb/betting-splits/")

# Splits move slowly compared to prices — they're a running total over a day of
# betting, not a quote. Five minutes is plenty.
TTL_SECONDS = 300.0

BOOK = "draftkings"

# How far handle has to run ahead of tickets before it reads as sharp rather
# than noise. Ten points is a real gap: a side taking a quarter of the bets and
# a third of the money is not news, one taking a quarter of the bets and two
# thirds of the money is.
SHARP_GAP = 10.0

# Every written form of a club we might meet, mapped to the abbreviation this
# project uses. Deliberately a table and not a fuzzy match: "CHW" and "CWS" are
# the same team, "NYY" and "NYM" are not, and a near-miss between those two
# would be silently catastrophic.
_TEAM_FORMS: dict[str, tuple[str, ...]] = {
    "ATH": ("ath", "oak", "athletics", "oakland", "sacramento", "las vegas"),
    "ATL": ("atl", "braves", "atlanta"),
    "AZ": ("az", "ari", "arizona", "diamondbacks", "dbacks", "d-backs"),
    "BAL": ("bal", "orioles", "baltimore"),
    "BOS": ("bos", "red sox", "redsox", "boston"),
    "CHC": ("chc", "cubs", "chi cubs", "chicago cubs"),
    "CIN": ("cin", "reds", "cincinnati"),
    "CLE": ("cle", "guardians", "cleveland"),
    "COL": ("col", "rockies", "colorado"),
    "CWS": ("cws", "chw", "white sox", "whitesox", "chi white sox",
            "chicago white sox"),
    "DET": ("det", "tigers", "detroit"),
    "HOU": ("hou", "astros", "houston"),
    "KC": ("kc", "kcr", "royals", "kansas city"),
    "LAA": ("laa", "ana", "angels", "los angeles angels", "la angels"),
    "LAD": ("lad", "dodgers", "los angeles dodgers", "la dodgers"),
    "MIA": ("mia", "marlins", "miami"),
    "MIL": ("mil", "brewers", "milwaukee"),
    "MIN": ("min", "twins", "minnesota"),
    "NYM": ("nym", "mets", "ny mets", "new york mets"),
    "NYY": ("nyy", "yankees", "ny yankees", "new york yankees"),
    "PHI": ("phi", "phillies", "philadelphia"),
    "PIT": ("pit", "pirates", "pittsburgh"),
    "SD": ("sd", "sdp", "padres", "san diego"),
    "SEA": ("sea", "mariners", "seattle"),
    "SF": ("sf", "sfg", "giants", "san francisco"),
    "STL": ("stl", "cardinals", "st louis", "st. louis"),
    "TB": ("tb", "tbr", "rays", "tampa bay", "tampa"),
    "TEX": ("tex", "rangers", "texas"),
    "TOR": ("tor", "blue jays", "bluejays", "toronto"),
    "WSH": ("wsh", "was", "wsn", "nationals", "washington"),
}

# Header keywords. The market a column belongs to, and what it measures.
_MARKET_WORDS = (
    ("moneyline", ("moneyline", "money line", "ml")),
    ("total", ("total", "o/u", "ou", "over/under")),
)
_METRIC_WORDS = (
    ("handle", ("handle", "money", "$")),
    ("bets", ("bets", "tickets", "ticket", "wagers", "count")),
    ("price", ("line", "odds", "price", "current", "open")),
)

# A column headed by a market and nothing else is that market itself — "ML" is
# the moneyline, "ML Handle" is its share of the money. Taking the price from
# the same book that published the split is the whole point: a share of DK's
# handle read against somebody else's consensus price is two different games.
_BARE_MARKET_IS_PRICE = True

_TAG = re.compile(r"<[^>]+>")
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.I | re.S)
_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.I | re.S)
_PCT = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")
_NUM = re.compile(r"([+-]?\d+(?:\.\d+)?)")


def _text(html: str) -> str:
    """Cell text with markup, entities and whitespace flattened out."""
    s = _TAG.sub(" ", html or "")
    for ent, ch in (("&nbsp;", " "), ("&amp;", "&"), ("&#039;", "'"),
                    ("&quot;", '"'), ("&rsquo;", "'"), ("&apos;", "'")):
        s = s.replace(ent, ch)
    return " ".join(s.split()).strip()


def _pct(cell: str) -> Optional[float]:
    m = _PCT.search(cell or "")
    if not m:
        return None
    try:
        v = float(m.group(1))
    except ValueError:
        return None
    return v if 0.0 <= v <= 100.0 else None


def _american(cell: str) -> Optional[int]:
    """A moneyline out of a cell that may also carry the team's name."""
    s = (cell or "").strip()
    if not s or "%" in s:
        return None
    if s.upper().replace(" ", "") in ("EVEN", "EV", "PK", "PICK"):
        return 100
    m = _NUM.search(s.replace(",", ""))
    if not m:
        return None
    try:
        v = int(float(m.group(1)))
    except ValueError:
        return None
    # A price is never inside ±100; anything there is a total or a spread that
    # wandered into the wrong column.
    return v if abs(v) >= 100 else None


def _total(cell: str) -> Optional[float]:
    """A run total: a small positive number, often written "o8.5"."""
    s = (cell or "").strip()
    if not s or "%" in s:
        return None
    m = _NUM.search(s.replace(",", ""))
    if not m:
        return None
    try:
        v = float(m.group(1))
    except ValueError:
        return None
    return v if 0.0 < v <= 30.0 else None


def team_of(token: str, allowed: Optional[set] = None) -> Optional[str]:
    """Which club a written form refers to, or None if it isn't clear.

    `allowed` narrows the field to the teams actually playing, which is what
    makes a short token like "NY" safe to reject rather than guess at.
    """
    t = " ".join(str(token or "").lower().split())
    if not t:
        return None
    t = re.sub(r"[^a-z0-9 .'-]", " ", t)
    t = " ".join(t.split())
    hits = set()
    for abbr, forms in _TEAM_FORMS.items():
        if allowed is not None and abbr not in allowed:
            continue
        for f in forms:
            if t == f or t.startswith(f + " ") or t.endswith(" " + f) \
                    or f" {f} " in f" {t} ":
                hits.add(abbr)
                break
    # Exactly one club, or we don't know which one.
    return hits.pop() if len(hits) == 1 else None


@dataclass
class GameSplits:
    """Where DraftKings' money and tickets sat on one game.

    Percentages are the *home* side and the *over*, so one number per market
    says everything: the other side is the remainder.
    """

    game_id: str
    home: str
    away: str
    book: str = BOOK
    ml_home_handle: Optional[float] = None
    ml_home_bets: Optional[float] = None
    total_over_handle: Optional[float] = None
    total_over_bets: Optional[float] = None
    # The same book's posted price, where the page carries it. Worth having
    # even though ESPN can supply a price too: this one belongs to the ledger
    # the percentages came from, so the hold is that book's hold and the
    # movement is the movement the money was actually reacting to.
    ml_home_price: Optional[int] = None
    ml_away_price: Optional[int] = None
    total_line: Optional[float] = None

    @property
    def usable(self) -> bool:
        """Worth storing — at least one market's handle actually arrived."""
        return (self.ml_home_handle is not None
                or self.total_over_handle is not None)

    @property
    def has_price(self) -> bool:
        return (self.ml_home_price is not None
                and self.ml_away_price is not None) or self.total_line is not None

    def as_line(self):
        """This book's posted price, in the shape the odds recorder stores."""
        from .lines import GameLine

        return GameLine(
            game_id=self.game_id, home=self.home, away=self.away,
            home_ml=self.ml_home_price, away_ml=self.ml_away_price,
            total=self.total_line, book=self.book)

    def as_dict(self) -> dict:
        return {
            "game_id": self.game_id, "home": self.home, "away": self.away,
            "book": self.book,
            "ml_home_handle": self.ml_home_handle,
            "ml_home_bets": self.ml_home_bets,
            "total_over_handle": self.total_over_handle,
            "total_over_bets": self.total_over_bets,
            "ml_home_price": self.ml_home_price,
            "ml_away_price": self.ml_away_price,
            "total_line": self.total_line,
        }


def _header_map(cells: list) -> dict:
    """Column index → (market, metric), read off the table's own header.

    Position is never assumed. A table we can't read the headers of is a table
    we decline to parse.
    """
    out: dict = {}
    for i, raw in enumerate(cells):
        low = _text(raw).lower()
        if not low:
            continue
        market = next((m for m, words in _MARKET_WORDS
                       if any(w in low for w in words)), None)
        metric = next((k for k, words in _METRIC_WORDS
                       if any(w in low for w in words)), None)
        if market and metric:
            out[i] = (market, metric)
        elif market and _BARE_MARKET_IS_PRICE:
            out[i] = (market, "price")
    return out


class VSiNSplitsSource:
    """DraftKings' handle and ticket splits for a slate, cached briefly."""

    _cache: dict[str, tuple[float, list[GameSplits]]] = {}
    _lock = threading.Lock()

    def _get(self) -> str:
        resp = requests.get(
            SPLITS_URL, timeout=(4, 10),
            headers={"User-Agent": "Mozilla/5.0 (compatible; thebeast/1.0)"})
        resp.raise_for_status()
        return resp.text

    def _parse(self, html: str, day: date_type,
               games: Iterable) -> list[GameSplits]:
        """Rows → splits, matched against the games we know are on."""
        from ...gameid import teams_of

        by_pair: dict = {}
        allowed: set = set()
        for g in games or []:
            gid = g if isinstance(g, str) else getattr(g, "game_id", None)
            if not gid:
                continue
            home, away = teams_of(gid)
            if not (home and away):
                continue
            allowed.update((home, away))
            by_pair[home] = by_pair[away] = (gid, home, away)
        if not by_pair:
            return []

        found: dict = {}
        columns: dict = {}
        for row_html in _ROW.findall(html or ""):
            cells = _CELL.findall(row_html)
            if len(cells) < 2:
                continue
            mapped = _header_map(cells)
            if mapped:
                # A header row — every table on the page gets its own, so this
                # re-arms rather than being read once at the top.
                columns = mapped
                continue
            if not columns:
                continue

            label = _text(cells[0])
            team = team_of(label, allowed)
            if team is None or team not in by_pair:
                continue
            gid, home, away = by_pair[team]
            rec = found.setdefault(gid, GameSplits(gid, home, away))

            for idx, (market, metric) in columns.items():
                if idx >= len(cells):
                    continue
                cell = _text(cells[idx])

                if metric == "price":
                    # The posted line rather than a share of it. A moneyline
                    # belongs to whichever team's row it sits on; a total is
                    # the same number on both rows.
                    if market == "moneyline":
                        price = _american(cell)
                        field = ("ml_home_price" if team == home
                                 else "ml_away_price")
                    else:
                        price, field = _total(cell), "total_line"
                    if price is not None and getattr(rec, field) is None:
                        setattr(rec, field, price)
                    continue

                value = _pct(cell)
                if value is None:
                    continue
                # Stored home-relative and over-relative. A row for the away
                # team carries the away share, so it flips; the total column on
                # either row is the over, which doesn't.
                if market == "moneyline":
                    share = value if team == home else 100.0 - value
                    field = ("ml_home_handle" if metric == "handle"
                             else "ml_home_bets")
                else:
                    share = value
                    field = ("total_over_handle" if metric == "handle"
                             else "total_over_bets")
                if getattr(rec, field) is None:
                    setattr(rec, field, round(share, 1))

        return [s for s in found.values() if s.usable]

    def fetch(self, day: date_type, games: Iterable) -> list[GameSplits]:
        """Splits for one slate. Empty when unreachable or unreadable."""
        key = day.isoformat()
        now = time.time()
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None and now - hit[0] < TTL_SECONDS:
                return list(hit[1])
        try:
            html = self._get()
        except Exception:
            return []
        try:
            out = self._parse(html, day, games)
        except Exception:
            return []
        if out:
            with self._lock:
                self._cache[key] = (now, out)
        return out

    def diagnose(self, day: date_type, games: Iterable) -> dict:
        """What the scrape actually saw — the thing that makes this fixable.

        A scraper written against a page nobody could load yet fails silently
        by nature: no splits and no reason. This reports the reason, so
        correcting a column mapping is a one-line change against real evidence
        rather than a guess at what went wrong.
        """
        out: dict = {"url": SPLITS_URL, "book": BOOK, "reachable": False}
        try:
            html = self._get()
        except Exception as exc:
            out["error"] = f"{type(exc).__name__}: {exc}"
            return out

        out["reachable"] = True
        out["bytes"] = len(html)
        rows = _ROW.findall(html)
        out["table_rows"] = len(rows)

        headers: list = []
        samples: list = []
        for row_html in rows:
            cells = _CELL.findall(row_html)
            if not cells:
                continue
            mapped = _header_map(cells)
            texts = [_text(c) for c in cells]
            if mapped:
                headers.append({"cells": texts[:12],
                                "mapped": {str(k): list(v)
                                           for k, v in mapped.items()}})
            elif len(samples) < 5 and any(texts):
                samples.append(texts[:12])
        out["headers_found"] = headers[:4]
        out["sample_rows"] = samples
        out["parsed"] = [s.as_dict() for s in self._parse(html, day, games)]
        if not out["headers_found"]:
            out["note"] = ("No header row matched. The column keywords in "
                           "_MARKET_WORDS / _METRIC_WORDS need to match what "
                           "sample_rows shows; nothing is parsed until they do.")
        elif not out["parsed"]:
            out["note"] = ("Headers matched but no row's first cell resolved "
                           "to a team on this slate — compare sample_rows "
                           "against _TEAM_FORMS.")
        return out

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._cache.clear()
