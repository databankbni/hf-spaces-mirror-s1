"""NFL player props from Sleeper's public API — everything, unmapped.

The MLB source next door translates Sleeper's market names onto the stats our
simulator keeps a distribution for, and drops anything it can't price. That's
right there and wrong here. There is no NFL simulator, so there is nothing to
translate onto, and a market we don't recognise is still a market worth showing.
So this maps nothing and keeps everything: Sleeper's own `wager_type` string
travels through to the page as the market label.

That also sidesteps the one thing about NFL I couldn't verify. The endpoint,
the filtering and the odds handling are all shared with the MLB source and are
proven in production; the NFL *market vocabulary* was never confirmed, because
the environment this was written in can't reach the API. Not needing a
vocabulary means there's nothing left to guess.

Two calls, same as MLB:

  GET /lines/available?sport=nfl&include_props=true&dynamic=true
      the lines, each keyed to a Sleeper `subject_id`

  GET /v1/players/nfl
      the player directory, which is how a subject_id becomes a name. Large,
      so it's fetched once and held for the life of the process.

Undocumented and unversioned, so every access is defensive and `probe()`
reports what actually arrived rather than what we hoped would.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests

from ..names import normalize_name

_LINES_URL = "https://api.sleeper.app/lines/available"
_PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl"

SPORT = "nfl"

# Lines move, and a search page can be hammered. A minute keeps a result
# current without asking Sleeper once per keystroke.
TTL_SECONDS = 60.0

# How long to wait before trying the player directory again after it failed.
# Long enough not to hammer a struggling upstream, short enough that a blip
# doesn't outlive the container.
DIRECTORY_RETRY_SECONDS = 120.0


def _as_american(v: Any) -> Optional[int]:
    """American odds from whatever the feed carries.

    Sleeper quotes some markets as a payout multiplier (decimal-style) rather
    than American odds, so both are accepted and multipliers converted. Reading
    the multiplier as American gives +2 where +100 was meant, which is the kind
    of wrong that looks plausible on a page.
    """
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        f = float(v)
        if abs(f) >= 100:          # already American
            return int(round(f))
        if f > 1.0:                # decimal payout multiplier
            b = f - 1.0
            return int(round(b * 100)) if b >= 1.0 else int(round(-100.0 / b))
        return None
    if isinstance(v, str):
        try:
            return _as_american(float(v.replace("+", "")))
        except ValueError:
            return None
    return None


def _first(d: dict, *keys: str) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _tight(name: str) -> str:
    """A search key with the separators taken out as well as the punctuation.

    The shared normalizer leaves a space where an apostrophe was, so "Ja'Marr
    Chase" becomes "ja marr chase" — and nobody searching for him types the
    apostrophe *or* the space. Stripping to letters and digits makes "jamarr",
    "Ja'Marr" and "JaMarr Chase" all land on the same player. Kept local rather
    than changing the shared normalizer, which MLB name-matching depends on.
    """
    return "".join(c for c in normalize_name(name or "") if c.isalnum())


def _label(raw: Any) -> str:
    """Sleeper's market id, made readable without being reinterpreted.

    "pass_yards" becomes "Pass yards". The raw string is kept alongside it,
    because a prettified name is for the eye and the raw one is what you'd
    match on.
    """
    s = str(raw or "").replace("_", " ").strip()
    return s[:1].upper() + s[1:] if s else "—"


@dataclass
class NFLProp:
    """One over/under prop exactly as Sleeper posted it."""

    player_name: str
    player_key: str                 # normalized, for searching
    market: str                     # Sleeper's own wager_type
    market_label: str               # the same thing, readable
    line: float
    over_price: Optional[int]       # American odds
    under_price: Optional[int]
    team: Optional[str] = None
    position: Optional[str] = None
    opponent: Optional[str] = None
    game_status: str = "pre_game"
    is_live: bool = False

    def as_dict(self) -> dict:
        return {
            "player_name": self.player_name, "player_key": self.player_key,
            "market": self.market, "market_label": self.market_label,
            "line": self.line, "over_price": self.over_price,
            "under_price": self.under_price, "team": self.team,
            "position": self.position, "opponent": self.opponent,
            "game_status": self.game_status, "is_live": self.is_live,
        }


class SleeperNFLSource:
    """Every NFL player prop Sleeper is serving, searchable by name."""

    _players_cache: Optional[dict] = None
    _players_failed_at: Optional[float] = None
    _props_cache: Optional[tuple] = None      # (fetched_at, [NFLProp])
    _lock = threading.Lock()

    def _get(self, url: str, params: Optional[dict] = None,
             timeout=(4, 12)) -> Any:
        resp = requests.get(url, params=params, timeout=timeout,
                            headers={"accept": "application/json"})
        resp.raise_for_status()
        return resp.json()

    def _players(self) -> dict:
        """Sleeper's NFL directory, id → record. Fetched once — it's megabytes.

        A failure is *not* cached. It used to be: one slow fetch stored an
        empty directory for the life of the process, and since a prop with no
        resolvable name gets dropped, that turned a single timeout into "every
        search returns nothing, forever, until the container restarts". The
        cooldown stops a broken upstream being hammered without making the
        breakage permanent.
        """
        if SleeperNFLSource._players_cache is not None:
            return SleeperNFLSource._players_cache
        failed = SleeperNFLSource._players_failed_at
        if failed and time.time() - failed < DIRECTORY_RETRY_SECONDS:
            return {}
        try:
            # Generous, because this file is several megabytes and a cold
            # container fetching it is the slowest thing the page ever does.
            data = self._get(_PLAYERS_URL, timeout=(5, 60))
        except Exception as exc:
            SleeperNFLSource._players_failed_at = time.time()
            self.directory_error = f"{type(exc).__name__}: {exc}"[:300]
            return {}
        if not isinstance(data, dict) or not data:
            SleeperNFLSource._players_failed_at = time.time()
            self.directory_error = "the player directory came back empty"
            return {}
        SleeperNFLSource._players_cache = data
        SleeperNFLSource._players_failed_at = None
        return data

    def _identify(self, subject_id: Any) -> tuple:
        rec = self._players().get(str(subject_id))
        if not isinstance(rec, dict):
            return None, None, None
        name = _first(rec, "full_name", "fullName") or " ".join(
            x for x in (rec.get("first_name"), rec.get("last_name")) if x)
        return (name or None), rec.get("team"), rec.get("position")

    def _raw(self) -> list:
        """The feed's items, filtered to NFL and nothing else.

        The `sport` parameter is a hint rather than a filter — an MLB request
        comes back carrying esports — so every item is checked against its own
        sport field instead of being trusted.
        """
        data = self._get(_LINES_URL, params={
            "sport": SPORT, "include_props": "true", "dynamic": "true"})
        items = data if isinstance(data, list) else (
            data.get("lines") if isinstance(data, dict) else None) or []
        return [it for it in items if isinstance(it, dict)
                and str(it.get("sport") or "").lower() == SPORT]

    def _parse(self, items: list, drops: Optional[dict] = None) -> list:
        """Lines → props, optionally counting what was lost and where.

        Every `continue` below is a prop the page won't show, and from outside
        they all look identical: a player who "has props on Sleeper" but
        doesn't appear. `drops` makes the difference visible, which is the only
        way to tell a parser bug from an empty board.
        """
        def lost(stage: str) -> None:
            if drops is not None:
                drops[stage] = drops.get(stage, 0) + 1

        out: list = []
        for it in items:
            if str(it.get("subject_type") or "player").lower() != "player":
                lost("not_a_player_subject")
                continue
            if str(it.get("outcome_type") or "over_under").lower() != "over_under":
                lost(f"outcome_type={it.get('outcome_type')}")
                continue
            if str(it.get("status") or "active").lower() != "active":
                lost(f"status={it.get('status')}")
                continue

            market = _first(it, "wager_type", "stat", "market", "type")
            if not isinstance(market, str) or not market.strip():
                lost("no_market_name")
                continue

            # The line and both prices live on the options, not the parent.
            line = _first(it, "outcome_value", "line", "value")
            over = under = team = None
            for o in it.get("options") or []:
                if not isinstance(o, dict):
                    continue
                if str(o.get("status") or "active").lower() != "active":
                    continue
                if line is None:
                    line = _first(o, "outcome_value", "line", "value")
                team = team or o.get("subject_team")
                price = _as_american(
                    _first(o, "payout_multiplier", "odds", "american_odds"))
                if price is None:
                    continue
                label = str(_first(o, "outcome", "side", "name") or "").lower()
                # Sleeper's higher/lower product uses both vocabularies.
                if label.startswith("over") or label.startswith("high"):
                    over = price
                elif label.startswith("under") or label.startswith("low"):
                    under = price
            if over is None and under is None:
                lost("no_price_either_side")
                continue
            try:
                line = float(line)
            except (TypeError, ValueError):
                lost("no_usable_line_value")
                continue

            subject = _first(it, "subject_id", "player_id", "subject")
            name, directory_team, position = self._identify(subject)
            if not name:
                name = _first(it, "player_name", "subject_name")
            if not name:
                # Almost always the directory, not the line. A prop nothing can
                # name is unfindable by name, so it's dropped — but counted,
                # because a directory outage drops *every* prop and used to do
                # it in total silence.
                self.unnamed += 1
                lost("no_name_resolved")
                continue

            gs = str(it.get("game_status") or "pre_game").lower()
            out.append(NFLProp(
                player_name=str(name), player_key=normalize_name(str(name)),
                market=market.strip().lower(), market_label=_label(market),
                line=line, over_price=over, under_price=under,
                team=team or directory_team, position=position,
                opponent=_first(it, "opponent", "opponent_team"),
                game_status=gs, is_live=gs not in ("pre_game", ""),
            ))
        return out

    def __init__(self) -> None:
        # Why the last fetch came back empty, when it did. "Sleeper is down"
        # and "nobody offers a line on that player" are both empty lists and
        # mean completely different things to whoever typed the name.
        self.last_error: Optional[str] = None
        # Separately tracked, because the directory failing has its own
        # signature: the lines arrive fine and then every one of them is
        # dropped for having no name attached.
        self.directory_error: Optional[str] = None
        # Props thrown away because nothing could name them.
        self.unnamed = 0

    def fetch_props(self) -> list:
        """Every NFL prop on offer. Empty when unreachable — never partial."""
        now = time.time()
        with self._lock:
            hit = SleeperNFLSource._props_cache
            if hit and now - hit[0] < TTL_SECONDS:
                return list(hit[1])
        try:
            props = self._parse(self._raw())
            if not props and self.directory_error:
                # The lines arrived and every one was dropped for having no
                # name. That is a naming outage, not an empty board, and the
                # two read identically from outside.
                self.last_error = (
                    f"the player directory is unavailable "
                    f"({self.directory_error}), so no prop could be named")
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"[:300]
            return []
        if props:
            with self._lock:
                SleeperNFLSource._props_cache = (now, props)
        return props

    def search(self, query: str, limit: int = 200) -> list:
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
        environment it was written in can reach Sleeper. So rather than assert
        the parser works, this reports what arrived: how much of it was NFL,
        which market names are present, and one whole sample.
        """
        out: dict = {"reachable": False, "sport": SPORT, "url": _LINES_URL}
        try:
            data = self._get(_LINES_URL, params={
                "sport": SPORT, "include_props": "true", "dynamic": "true"})
        except Exception as e:
            out["error"] = f"{type(e).__name__}: {e}"[:300]
            return out

        out["reachable"] = True
        items = data if isinstance(data, list) else (
            data.get("lines") if isinstance(data, dict) else None) or []
        out["total_items"] = len(items)
        nfl = [it for it in items if isinstance(it, dict)
               and str(it.get("sport") or "").lower() == SPORT]
        out["nfl_items"] = len(nfl)
        out["other_sports"] = sorted({
            str(it.get("sport")) for it in items if isinstance(it, dict)
            and str(it.get("sport") or "").lower() != SPORT})[:12]

        markets: dict = {}
        for it in nfl:
            wt = it.get("wager_type")
            if isinstance(wt, str):
                markets[wt] = markets.get(wt, 0) + 1
        out["markets"] = dict(sorted(markets.items(), key=lambda kv: -kv[1]))
        if nfl:
            out["sample_keys"] = sorted(nfl[0].keys())
            out["sample"] = {k: v for k, v in nfl[0].items()
                             if k != "recent_performance"}
        drops: dict = {}
        parsed = self._parse(nfl, drops)
        out["parsed"] = len(parsed)
        # Where the ones that didn't make it were lost. Every drop looks the
        # same from the page — a player who "has props" and doesn't appear —
        # so this is the only thing that separates a parser bug from an empty
        # board.
        out["dropped"] = dict(sorted(drops.items(), key=lambda kv: -kv[1]))
        out["directory_error"] = self.directory_error
        out["players"] = len({p.player_key for p in parsed})
        out["directory_loaded"] = len(self._players())
        if not items:
            out["note"] = "The feed returned nothing at all."
        elif not nfl:
            out["note"] = ("Lines came back but none were NFL — out of season, "
                           "between slates, or the sport key has changed.")
        elif drops.get("no_name_resolved"):
            # Ahead of the generic "none parsed", because it names the actual
            # cause and that one only says where to start looking.
            out["note"] = (
                f"{drops['no_name_resolved']} NFL line(s) were dropped because "
                f"nothing could name the player. That is the directory, not the "
                f"lines — check directory_error and directory_loaded.")
        elif not parsed:
            out["note"] = ("NFL lines arrived but none parsed. Compare "
                           "sample_keys against what the parser reads, and "
                           "`dropped` for which filter took them.")
        return out

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._props_cache = None
            cls._players_cache = None
            cls._players_failed_at = None
