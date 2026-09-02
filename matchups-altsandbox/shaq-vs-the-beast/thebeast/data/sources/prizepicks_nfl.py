"""NFL player props from PrizePicks — everything, unmapped.

The MLB source next door translates PrizePicks' market names onto the stats our
simulator keeps a distribution for, and drops anything it can't price. That's
right there and wrong here. There is no NFL simulator, so there is nothing to
translate onto, and a market we don't recognise is still a market worth showing.
So this maps nothing and keeps everything: PrizePicks' own `stat_type` string
travels through to the page as the market label.

That also sidesteps the one thing about NFL nobody here could verify. The
endpoint, the paging, the JSON:API joining and the league lookup are all shared
with the MLB source; the NFL *market vocabulary* was never confirmed, because
the environment this was written in can't reach PrizePicks. Not needing a
vocabulary means there's nothing left to guess.

Nor is there a price to guess at. PrizePicks posts none — the payout is on the
slip — so unlike the MLB board, which converts a break-even into odds so it can
compute an edge, this shows the line and the side and stops there. There is no
model to compare against, so inventing a number to compare it to would be
inventing the whole thing.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

from ..names import normalize_name
from .prizepicks import (
    PrizePicksFeed,
    _first,
    _norm_stat,
    _truthy,
)

SPORT = "nfl"

# Fallback only — `league_id()` asks PrizePicks for it by name first.
NFL_LEAGUE_ID = 9

# Lines move, and a search page can be hammered. A minute keeps a result
# current without asking PrizePicks once per keystroke.
TTL_SECONDS = 60.0


def _label(raw: Any) -> str:
    """PrizePicks' market name, tidied without being reinterpreted.

    Theirs is already prose ("Pass Yards"), so this only normalises the casing.
    The raw string is kept alongside it, because a prettified name is for the
    eye and the raw one is what you'd match on.
    """
    s = str(raw or "").strip()
    return s if s else "—"


def _tight(name: str) -> str:
    """A search key with the separators taken out as well as the punctuation.

    The shared normalizer leaves a space where an apostrophe was, so "Ja'Marr
    Chase" becomes "ja marr chase" — and nobody searching for him types the
    apostrophe *or* the space. Stripping to letters and digits makes "jamarr",
    "Ja'Marr" and "JaMarr Chase" all land on the same player. Kept local rather
    than changing the shared normalizer, which MLB name-matching depends on.
    """
    return "".join(c for c in normalize_name(name or "") if c.isalnum())


@dataclass
class NFLProp:
    """One projection exactly as PrizePicks posted it."""

    player_name: str
    player_key: str                 # normalized, for searching
    market: str                     # PrizePicks' own stat_type, normalized
    market_label: str               # the same thing, as they wrote it
    line: float
    team: Optional[str] = None
    position: Optional[str] = None
    opponent: Optional[str] = None
    # "standard" | "demon" | "goblin". Shown rather than dropped: this page is
    # a browser, not a bet, and a demon is a real thing on their board.
    odds_type: str = "standard"
    is_promo: bool = False
    game_status: str = "pre_game"
    is_live: bool = False

    def as_dict(self) -> dict:
        return {
            "player_name": self.player_name, "player_key": self.player_key,
            "market": self.market, "market_label": self.market_label,
            "line": self.line, "team": self.team, "position": self.position,
            "opponent": self.opponent, "odds_type": self.odds_type,
            "is_promo": self.is_promo,
            "game_status": self.game_status, "is_live": self.is_live,
        }


class PrizePicksNFLSource(PrizePicksFeed):
    """Every NFL projection PrizePicks is serving, searchable by name."""

    _props_cache: Optional[tuple] = None      # (fetched_at, [NFLProp])
    _cache_lock = threading.Lock()

    NAME = "PrizePicks"

    def __init__(self) -> None:
        # Why the last fetch came back empty, when it did. "PrizePicks is
        # unreachable" and "nobody offers a line on that player" are both empty
        # lists and mean completely different things to whoever typed the name.
        self.last_error: Optional[str] = None
        # Projections thrown away because nothing could name them. On this feed
        # that means the `included` array didn't carry the player, which is a
        # different failure from an empty board and used to be invisible.
        self.unnamed = 0

    def _parse(self, docs: list[dict]) -> list[NFLProp]:
        """Projections → props. Nothing is dropped for being unrecognised."""
        players = self.included(docs)
        out: list[NFLProp] = []
        for doc in docs:
            for row in doc.get("data") or []:
                if not isinstance(row, dict):
                    continue
                attrs = row.get("attributes")
                if not isinstance(attrs, dict):
                    continue
                who = self.player_for(row, players)

                name = _first(who, "display_name", "name") or _first(
                    attrs, "name", "player_name")
                if not name:
                    # A projection nothing can name is unfindable by name, so
                    # it's dropped — but counted, because a broken `included`
                    # array drops *every* prop and used to do it in silence.
                    self.unnamed += 1
                    continue
                line = _first(attrs, "line_score", "line", "stat_line")
                try:
                    line = float(line)
                except (TypeError, ValueError):
                    continue

                status = str(_first(attrs, "status") or "pre_game").lower()
                stat = _first(attrs, "stat_type", "stat_display_name") or ""
                out.append(NFLProp(
                    player_name=str(name),
                    player_key=normalize_name(str(name)),
                    market=_norm_stat(stat), market_label=_label(stat),
                    line=line,
                    team=_first(who, "team", "team_abbreviation"),
                    position=_first(who, "position"),
                    opponent=_first(attrs, "description", "opponent"),
                    odds_type=str(_first(attrs, "odds_type") or "standard").lower(),
                    is_promo=_truthy(attrs.get("is_promo")),
                    game_status=status,
                    is_live=status not in ("pre_game", ""),
                ))
        return out

    def fetch_props(self) -> list[NFLProp]:
        """Every NFL prop on offer. Empty when unreachable — never partial."""
        now = time.time()
        with self._cache_lock:
            hit = PrizePicksNFLSource._props_cache
            if hit and now - hit[0] < TTL_SECONDS:
                return list(hit[1])
        try:
            props = self._parse(self.pages(self.league_id("NFL", NFL_LEAGUE_ID)))
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"[:300]
            return []
        if not props and self.unnamed:
            self.last_error = (
                f"{self.unnamed} projection(s) arrived with no player attached, "
                f"so none could be named")
        if props:
            with self._cache_lock:
                PrizePicksNFLSource._props_cache = (now, props)
        return props

    def search(self, query: str, limit: int = 200) -> list[NFLProp]:
        """Props for players whose name matches. Empty query returns nothing.

        Matched on a key with punctuation and spacing removed, so none of it
        has to be typed exactly — "ja'marr", "Ja'Marr Chase Jr." and "jamarr"
        all find the same player.
        """
        q = _tight(query)
        if not q:
            return []
        hits = [p for p in self.fetch_props() if q in _tight(p.player_name)]
        # Name, then market, so one player's markets arrive together and in a
        # stable order rather than however the feed happened to list them.
        hits.sort(key=lambda p: (p.player_name.lower(), p.market, p.line))
        return hits[:limit]

    def probe(self) -> dict:
        """What the endpoint actually returned, for confirming shape live.

        This source has never been run against the real API — nothing in the
        environment it was written in can reach PrizePicks. So rather than
        assert the parser works, this reports what arrived: how many
        projections, which market names are present, and one whole sample.
        """
        league = self.league_id("NFL", NFL_LEAGUE_ID)
        out: dict = {"source": self.NAME, "sport": SPORT, "league_id": league,
                     "reachable": False}
        try:
            docs = self.pages(league)
        except Exception as e:
            out["error"] = f"{type(e).__name__}: {e}"[:300]
            return out

        out["reachable"] = True
        out["pages"] = len(docs)
        rows = [r for doc in docs for r in (doc.get("data") or [])]
        out["projections"] = len(rows)
        out["included"] = len(self.included(docs))
        if rows and isinstance(rows[0], dict):
            out["sample_keys"] = sorted((rows[0].get("attributes") or {}).keys())
            out["sample"] = rows[0]

        self.unnamed = 0
        parsed = self._parse(docs)
        out["parsed"] = len(parsed)
        out["unnamed"] = self.unnamed
        markets: dict = {}
        for p in parsed:
            markets[p.market] = markets.get(p.market, 0) + 1
        out["markets"] = dict(sorted(markets.items(), key=lambda kv: -kv[1]))
        out["players"] = len({p.player_key for p in parsed})

        if not rows:
            out["note"] = ("The endpoint answered but carried no NFL "
                           "projections — out of season, between slates, or "
                           "the league id is wrong. Check "
                           "/api/props-probe/leagues.")
        elif self.unnamed and not parsed:
            out["note"] = (
                f"{self.unnamed} projection(s) were dropped because nothing "
                f"could name the player. That is the `included` array, not the "
                f"lines — compare `projections` against `included`.")
        return out

    @classmethod
    def clear(cls) -> None:
        with cls._cache_lock:
            cls._props_cache = None
        cls.clear_leagues()
