"""Player props from PrizePicks' projections endpoint. The only prop source.

PrizePicks publishes **no developer API**. What exists is the JSON:API endpoint
their own app calls — `GET /projections?league_id=…` — which is reachable
without a key, a login or a cookie, and which a number of open-source projects
read. It is public, real, and completely unpromised, so every access here is
defensive and `probe()` reports what actually arrived rather than what this
parser hoped would.

Two things make PrizePicks different from a sportsbook, and both change the
arithmetic rather than just the plumbing:

**There is no price on a pick.** PrizePicks is DFS pick'em. A projection is a
line and a side, and the payout lives on the *slip* — a 2-pick power play pays
3x, a 6-pick pays 25x — so no individual pick carries odds. Pricing one against
our model therefore needs a stated break-even rather than a quoted number, and
`BREAK_EVEN` below is that number, derived from the flagship slip and applied
symmetrically to both sides. It is an assumption, it is the only one in this
file, and it is reported on every payload so nobody reads it as a market price.

**Not every pick is a straight one.** Demons take a harder line for a bigger
share of the slip and goblins take an easier line for less. Priced at the
standard break-even a demon comes out too pessimistic and a goblin too
optimistic — and the optimistic direction is the one that puts money down. The
feed does not reliably carry the per-leg multiplier that would let them be
priced properly, so they are dropped by default and counted where they went.
`PRIZEPICKS_INCLUDE_SPECIALS=1` puts them back, flagged, for anyone who wants
to eyeball them.

The response is JSON:API, so a projection points at its player by reference and
the player records arrive alongside in `included`. Both halves are needed: the
line is in `data`, the name is not.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests

from ..names import normalize_name

_BASE = "https://api.prizepicks.com"
_PROJECTIONS_URL = f"{_BASE}/projections"
_LEAGUES_URL = f"{_BASE}/leagues"

BOOK = "PrizePicks"

# PrizePicks' own league id for MLB. Used only as a fallback: the sources below
# ask `/leagues` for the id by name first, because a hardcoded number that goes
# stale looks exactly like an empty slate and there is no reason to guess at
# something the server will tell us.
MLB_LEAGUE_ID = 2

# Their pages are small by default and a slate is not. Asked for explicitly,
# and paged through, because a board that quietly stops at the first 25 props
# is exactly the failure this app has already spent a week chasing once.
PAGE_SIZE = 250
MAX_PAGES = 20

# Lines move. A minute is current enough to bet off and slow enough not to
# hammer an endpoint nobody promised us.
TTL_SECONDS = 60.0

# The league list barely changes, so it is worth holding for the life of the
# process rather than paying for it on every board build.
LEAGUE_TTL_SECONDS = 3600.0

# ── What a pick has to hit to be worth taking ────────────────────────────────
# A PrizePicks pick has no odds, so the bar comes from the slip it goes into.
# The 2-pick power play is the reference: it pays 3x and both legs must land,
# so the break-even per leg is (1/3)^(1/2) = 57.7%. That is the honest question
# to ask our model — "does this beat the rate the slip needs?" — and it is a
# far higher bar than the 50% a naive reading of a pick'em line suggests.
#
# The larger power plays sit close to it (4-pick at 10x needs 56.2%, 6-pick at
# 25x needs 58.8%), so one number covers the product without being tuned to a
# slip size nobody said they were playing.
POWER_PLAY_PAYOUT = 3.0
POWER_PLAY_LEGS = 2
BREAK_EVEN = (1.0 / POWER_PLAY_PAYOUT) ** (1.0 / POWER_PLAY_LEGS)


def _american_for(break_even: float) -> Optional[int]:
    """The American price whose vig-inclusive implied probability is `break_even`.

    Everything downstream — the edge, the Kelly stake, the implied percentage
    on the card — speaks American odds, and translating here means none of it
    has to learn that this source is a pick'em. The rounding to a whole number
    costs about a twelfth of a percentage point and costs it in the
    conservative direction, so a play that clears the bar here clears it really.
    """
    if not 0.0 < break_even < 1.0:
        return None
    if break_even > 0.5:
        return -int(round(100.0 * break_even / (1.0 - break_even)))
    return int(round(100.0 * (1.0 - break_even) / break_even))


STANDARD_PRICE = _american_for(BREAK_EVEN)          # −137 at a 3x power play


def pricing_note() -> str:
    """One sentence on where this source's prices come from.

    A sportsbook doesn't need this and PrizePicks does: its picks carry no
    odds, so the implied percentage on every card is a break-even we chose
    rather than a number anyone quoted. Saying so wherever those percentages
    appear is the difference between a stated assumption and a fabricated
    price.
    """
    return (
        f"PrizePicks picks carry no odds of their own — the payout is on the "
        f"slip, not the pick. Every 'needs' percentage here is the break-even "
        f"for a {POWER_PLAY_LEGS}-pick power play at "
        f"{POWER_PLAY_PAYOUT:g}x, which is {100 * BREAK_EVEN:.1f}%. It is our "
        f"assumption, not a quoted price."
    )


@dataclass
class PlayerProp:
    """One over/under prop, normalized onto our stat vocabulary."""
    player_name: str
    player_key: str            # normalized name, for matching
    side: str                  # "batter" | "pitcher"
    stat: str                  # our stat id (hits, home_runs, k, ...)
    line: float
    over_price: Optional[int]  # American odds
    under_price: Optional[int]
    team: Optional[str] = None
    raw_stat: Optional[str] = None
    # The feed's own label for the game's state ("pre_game", "in_progress").
    game_status: str = "pre_game"
    # True once the game is under way, which decides whether this has to be
    # priced against the rest of the game rather than against all nine innings.
    is_live: bool = False


# ── Stat vocabulary ──────────────────────────────────────────────────────────
# PrizePicks names a market in prose ("Pitcher Strikeouts") rather than with a
# slug, and the same word means different things either side of the ball:
# "Walks" is a batter drawing them, "Walks Allowed" is a pitcher giving them up.
# So the side is decided *first* — from an explicit prefix if the market names
# one, otherwise from the player's position — and only then is the stat looked
# up in that side's vocabulary. Getting this backwards would price a pitcher's
# strikeout prop off a batter's strikeout distribution, which is the kind of
# wrong that produces a confident number and a nonsense bet.
#
# Absent on purpose, so they are dropped rather than mispriced:
#   Runs, Hits+Runs+RBIs — a run is credited to the runner, and the simulator's
#     bases are an occupancy bitmap with no runner identity, so there is no
#     per-batter runs distribution to price against.
#   Stolen Bases, Pitches Thrown, Fantasy Score — not simulated at all.
_BATTER_STATS: dict[str, str] = {
    "hits": "hits",
    "singles": "singles",
    "doubles": "doubles",
    "triples": "triples",
    "home runs": "home_runs",
    "hr": "home_runs",
    "total bases": "total_bases",
    "rbis": "rbi",
    "rbi": "rbi",
    "runs batted in": "rbi",
    "walks": "bb",
    "walks drawn": "bb",
    "hitter strikeouts": "k",
    "batter strikeouts": "k",
    "strikeouts": "k",
}
_PITCHER_STATS: dict[str, str] = {
    "pitcher strikeouts": "k",
    "strikeouts": "k",
    "pitching outs": "outs",
    "outs": "outs",
    "outs recorded": "outs",
    "hits allowed": "hits_allowed",
    "walks allowed": "bb_allowed",
    "earned runs allowed": "runs_allowed",
    # We simulate runs allowed rather than earned runs; unearned runs are rare
    # enough that the difference is far inside this product's hold.
    "earned runs": "runs_allowed",
    "runs allowed": "runs_allowed",
}

# A market that names its own side wins over the player's listed position —
# a two-way player is listed as a hitter and still gets pitching projections.
_SIDE_PREFIX = (
    ("pitcher ", "pitcher"), ("pitching ", "pitcher"),
    ("hitter ", "batter"), ("batter ", "batter"),
)
_PITCHER_POSITIONS = {"P", "SP", "RP", "PITCHER"}

# PrizePicks abbreviates a few clubs differently from the MLB Stats API, which
# is where the rest of this app's team ids come from. Only used to attribute a
# prop to a game for the coverage count — matching is by player name — but a
# prop filed under the wrong game is worse than one filed under none.
_TEAM_ALIAS = {
    "CHW": "CWS", "CHA": "CWS", "SOX": "CWS",
    "OAK": "ATH", "OAKLAND": "ATH",
    "WAS": "WSH", "WSN": "WSH",
    "SDP": "SD", "SFG": "SF", "TBR": "TB", "KCR": "KC",
    "ARI": "AZ", "ARZ": "AZ",
}


def _norm_stat(raw: Any) -> str:
    """A market name flattened to something a dict can be keyed on."""
    s = str(raw or "").strip().lower()
    return " ".join(s.replace(".", "").replace("-", " ").split())


def _team(raw: Any) -> Optional[str]:
    t = str(raw or "").strip().upper()
    if not t:
        return None
    return _TEAM_ALIAS.get(t, t)


def _side_and_stat(stat_type: Any,
                   position: Any) -> Optional[tuple[str, str]]:
    """(side, our stat id) for a PrizePicks market, or None if we can't price it."""
    name = _norm_stat(stat_type)
    if not name:
        return None

    side = None
    for prefix, which in _SIDE_PREFIX:
        if name.startswith(prefix):
            side = which
            break
    if side is None and name.endswith(" allowed"):
        side = "pitcher"
    if side is None:
        pos = str(position or "").strip().upper()
        side = "pitcher" if pos in _PITCHER_POSITIONS else "batter"

    table = _PITCHER_STATS if side == "pitcher" else _BATTER_STATS
    stat = table.get(name)
    if stat is None:
        return None
    return side, stat


def _first(d: dict, *keys: str) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _truthy(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes")
    return bool(v)


def _include_specials() -> bool:
    return _truthy(os.environ.get("PRIZEPICKS_INCLUDE_SPECIALS"))


@dataclass
class Projection:
    """One PrizePicks projection, before it becomes a two-sided prop.

    Kept as its own type so the probe can report what the feed carries without
    that reporting depending on whether our stat map recognised it.
    """
    player_name: str
    team: Optional[str]
    position: Optional[str]
    stat_type: str
    line: float
    odds_type: str
    status: str
    is_promo: bool
    projection_type: str


class PrizePicksFeed:
    """The bits every PrizePicks reader needs: HTTP, paging, league lookup.

    Shared by the MLB source below and the NFL one next door so the transport
    is written and fixed once. Neither sport's parser should be the place a
    pagination bug gets found.
    """

    _leagues_cache: Optional[tuple] = None    # (fetched_at, {NAME: id})
    _lock = threading.Lock()

    def _get(self, url: str, params: Optional[dict] = None,
             timeout=(5, 20)) -> Any:
        # A browser-ish Accept header, because this is an app's own endpoint
        # rather than a documented API and the default python-requests header
        # set is the least like a client it has ever served. Nothing here
        # forges a user agent or works around a block — if PrizePicks does not
        # want to answer, the honest outcome is an error we report.
        resp = requests.get(url, params=params, timeout=timeout, headers={
            "accept": "application/json",
            "accept-language": "en-US,en;q=0.9",
        })
        resp.raise_for_status()
        return resp.json()

    def leagues(self) -> dict[str, int]:
        """{LEAGUE NAME: id}, straight off the server. Empty if unreachable."""
        now = time.time()
        with PrizePicksFeed._lock:
            hit = PrizePicksFeed._leagues_cache
            if hit and now - hit[0] < LEAGUE_TTL_SECONDS:
                return dict(hit[1])
        try:
            doc = self._get(_LEAGUES_URL)
        except Exception:
            return {}
        found: dict[str, int] = {}
        for row in (doc.get("data") if isinstance(doc, dict) else None) or []:
            if not isinstance(row, dict):
                continue
            attrs = row.get("attributes")
            name = attrs.get("name") if isinstance(attrs, dict) else None
            try:
                lid = int(row.get("id"))
            except (TypeError, ValueError):
                continue
            if name:
                found[str(name).strip().upper()] = lid
        if found:
            with PrizePicksFeed._lock:
                PrizePicksFeed._leagues_cache = (now, found)
        return found

    def league_id(self, name: str, fallback: int) -> int:
        """The league's id by name, falling back to a constant.

        Asking beats hardcoding: a stale league id returns an empty page, which
        is indistinguishable from "no games today" and would send anyone
        debugging it straight at the parser. The fallback keeps a `/leagues`
        outage from taking the board down with it.
        """
        return self.leagues().get(name.strip().upper(), fallback)

    def pages(self, league_id: int) -> list[dict]:
        """Every page of projections for a league, as raw JSON:API documents.

        Paged rather than taken on trust: `per_page` is a request, not a
        promise, and a board silently truncated at one page looks exactly like
        a book that only posted 25 props.
        """
        out: list[dict] = []
        seen = 0
        for page in range(1, MAX_PAGES + 1):
            doc = self._get(_PROJECTIONS_URL, params={
                "league_id": league_id,
                "per_page": PAGE_SIZE,
                "page": page,
                "single_stat": "true",
            })
            if not isinstance(doc, dict):
                break
            out.append(doc)
            rows = doc.get("data")
            n = len(rows) if isinstance(rows, list) else 0
            seen += n
            if n < PAGE_SIZE:
                break
            meta = doc.get("meta")
            total = meta.get("total_count") if isinstance(meta, dict) else None
            if isinstance(total, int) and seen >= total:
                break
        return out

    @staticmethod
    def included(docs: list[dict]) -> dict[tuple, dict]:
        """{(type, id): attributes} for everything in `included`.

        JSON:API keeps the projections and the players in separate arrays and
        joins them by reference, so a projection on its own cannot name anyone.
        """
        out: dict[tuple, dict] = {}
        for doc in docs:
            for row in doc.get("included") or []:
                if not isinstance(row, dict):
                    continue
                attrs = row.get("attributes")
                if isinstance(attrs, dict):
                    out[(str(row.get("type")), str(row.get("id")))] = attrs
        return out

    @classmethod
    def player_for(cls, row: dict, players: dict[tuple, dict]) -> dict:
        """The player record a projection points at, or an empty dict."""
        rels = row.get("relationships")
        if not isinstance(rels, dict):
            return {}
        ref = rels.get("new_player") or rels.get("player")
        data = ref.get("data") if isinstance(ref, dict) else None
        if not isinstance(data, dict):
            return {}
        return players.get((str(data.get("type")), str(data.get("id")))) or {}

    def discover(self) -> dict:
        """The league list, reported rather than used. For the probe endpoint."""
        out: dict = {"url": _LEAGUES_URL, "reachable": False}
        try:
            doc = self._get(_LEAGUES_URL)
        except Exception as exc:
            out["error"] = f"{type(exc).__name__}: {exc}"[:300]
            return out
        out["reachable"] = True
        rows = doc.get("data") if isinstance(doc, dict) else None
        leagues = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            attrs = row.get("attributes") or {}
            leagues.append({
                "id": row.get("id"),
                "name": attrs.get("name") if isinstance(attrs, dict) else None,
            })
        out["leagues"] = leagues
        out["resolved"] = {"MLB": self.league_id("MLB", MLB_LEAGUE_ID)}
        return out

    @classmethod
    def clear_leagues(cls) -> None:
        # Assigned on the base explicitly. `cls._leagues_cache = None` from a
        # subclass would create a shadowing attribute there and leave the real
        # cache untouched, so clearing from one sport wouldn't clear the other.
        with PrizePicksFeed._lock:
            PrizePicksFeed._leagues_cache = None


class PrizePicksSource(PrizePicksFeed):
    """Every MLB projection PrizePicks is serving, as two-sided props."""

    # The board is the same for every caller, so one fetch serves them all.
    _cache: Optional[tuple] = None            # (fetched_at, [PlayerProp])

    #: How this source is named on a page or in a note.
    NAME = BOOK

    def __init__(self) -> None:
        # Why the last fetch came back empty. "PrizePicks blocked us" and
        # "there is no slate today" are both an empty list and mean completely
        # different things to whoever is looking at the board.
        self.last_error: Optional[str] = None
        # Market names the feed carried that our stat map doesn't know. These
        # are the difference between "they don't offer it" and "we don't read
        # it", and only one of those is our bug.
        self.unmapped: dict[str, int] = {}

    def _projections(self, docs: list[dict]) -> list[Projection]:
        """The feed's rows, resolved against `included`, before any filtering.

        Everything that arrived and could be named comes through here —
        including the demons, the promos and the markets we can't price — so
        the probe can report the board as PrizePicks actually posted it.
        """
        players = self.included(docs)
        out: list[Projection] = []
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
                    continue
                line = _first(attrs, "line_score", "line", "stat_line")
                try:
                    line = float(line)
                except (TypeError, ValueError):
                    continue

                out.append(Projection(
                    player_name=str(name),
                    team=_team(_first(who, "team", "team_abbreviation")),
                    position=_first(who, "position"),
                    stat_type=str(_first(attrs, "stat_type",
                                         "stat_display_name") or ""),
                    line=line,
                    odds_type=str(_first(attrs, "odds_type") or "standard").lower(),
                    status=str(_first(attrs, "status") or "pre_game").lower(),
                    is_promo=_truthy(attrs.get("is_promo")),
                    projection_type=str(
                        _first(attrs, "projection_type") or "Single Stat"),
                ))
        return out

    def _to_props(self, rows: list[Projection],
                  drops: Optional[dict] = None) -> list[PlayerProp]:
        """Projections → priced two-sided props.

        Each `continue` is a prop that won't reach the board, and from the page
        they all look identical — a player PrizePicks plainly offers who simply
        isn't there. `drops` is what tells them apart.
        """
        def lost(stage: str) -> None:
            if drops is not None:
                drops[stage] = drops.get(stage, 0) + 1

        specials = _include_specials()
        out: list[PlayerProp] = []
        for r in rows:
            if r.projection_type and "combo" in r.projection_type.lower():
                # Two players in one line. There is no single distribution to
                # price it against, so it cannot be honestly compared.
                lost("combo_projection")
                continue
            if r.is_promo and not specials:
                lost("promo_line")
                continue
            if r.odds_type != "standard" and not specials:
                # Demons and goblins move the line without telling us what the
                # leg now pays, and a goblin priced at the standard break-even
                # reads as free money. See the module docstring.
                lost(f"odds_type={r.odds_type}")
                continue

            found = _side_and_stat(r.stat_type, r.position)
            if found is None:
                key = _norm_stat(r.stat_type) or "(blank)"
                self.unmapped[key] = self.unmapped.get(key, 0) + 1
                lost(f"unmapped_market={key}")
                continue
            side, stat = found

            if STANDARD_PRICE is None:      # unreachable with a sane break-even
                lost("no_break_even")
                continue

            live = r.status not in ("pre_game", "")
            out.append(PlayerProp(
                player_name=r.player_name,
                player_key=normalize_name(r.player_name),
                side=side, stat=stat, line=r.line,
                # Symmetric by construction: PrizePicks charges the same for
                # MORE and LESS, so the bar is the same on both sides and the
                # only thing separating them is what our model says.
                over_price=STANDARD_PRICE, under_price=STANDARD_PRICE,
                team=r.team, raw_stat=r.stat_type,
                game_status=r.status, is_live=live,
            ))
        return out

    def fetch_props(self, sport: str = "mlb",
                    drops: Optional[dict] = None) -> list[PlayerProp]:
        """Every priceable MLB prop on the board. Empty if unreachable.

        `sport` is accepted so callers can stay sport-agnostic; PrizePicks
        selects by league id instead, and anything other than MLB returns
        nothing rather than quietly serving MLB.
        """
        if sport.lower() != "mlb":
            return []
        now = time.time()
        with self._lock:
            hit = PrizePicksSource._cache
            if hit and now - hit[0] < TTL_SECONDS and drops is None:
                return list(hit[1])
        try:
            docs = self.pages(self.league_id("MLB", MLB_LEAGUE_ID))
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"[:300]
            return []
        props = self._to_props(self._projections(docs), drops)
        if props:
            with self._lock:
                PrizePicksSource._cache = (now, props)
        return props

    def probe(self, sport: str = "mlb") -> dict:
        """What the endpoint actually sent, with no interpretation on top.

        Nothing in the environment this was written in can reach PrizePicks —
        the egress policy refuses the connection outright — so every field name
        this parser reads is informed by other people's readers rather than by
        a response anyone here has seen. This reports the real shape so the map
        can be corrected against it instead of guessed at twice.
        """
        league = self.league_id("MLB", MLB_LEAGUE_ID)
        out: dict[str, Any] = {
            "source": self.NAME,
            "url": _PROJECTIONS_URL,
            "league_id": league,
            "league_id_was_resolved": league != MLB_LEAGUE_ID
            or bool(self.leagues()),
            "reachable": False,
            # Stated on every probe, because it is the one number here that is
            # a decision rather than a measurement.
            "break_even_pct": round(100.0 * BREAK_EVEN, 2),
            "synthetic_price": STANDARD_PRICE,
            "include_specials": _include_specials(),
        }
        try:
            docs = self.pages(league)
        except Exception as exc:
            out["error"] = f"{type(exc).__name__}: {exc}"[:300]
            return out

        out["reachable"] = True
        out["pages"] = len(docs)
        rows = [r for doc in docs for r in (doc.get("data") or [])]
        out["projections"] = len(rows)
        out["included"] = len(self.included(docs))
        if docs and isinstance(docs[0].get("meta"), dict):
            out["meta"] = docs[0]["meta"]
        if rows and isinstance(rows[0], dict):
            out["sample_keys"] = sorted((rows[0].get("attributes") or {}).keys())
            out["sample"] = rows[0]

        parsed_rows = self._projections(docs)
        out["named"] = len(parsed_rows)

        # The market vocabulary, which is the thing most likely to be wrong:
        # our stat map has to key off whatever strings actually appear here.
        vocab: dict[str, int] = {}
        odds_types: dict[str, int] = {}
        teams: dict[str, int] = {}
        for r in parsed_rows:
            k = _norm_stat(r.stat_type) or "(blank)"
            vocab[k] = vocab.get(k, 0) + 1
            odds_types[r.odds_type] = odds_types.get(r.odds_type, 0) + 1
            if r.team:
                teams[r.team] = teams.get(r.team, 0) + 1
        out["stat_types"] = dict(sorted(vocab.items(), key=lambda kv: -kv[1]))
        out["odds_types"] = dict(sorted(odds_types.items(), key=lambda kv: -kv[1]))
        out["teams"] = dict(sorted(teams.items()))

        drops: dict = {}
        self.unmapped = {}
        props = self._to_props(parsed_rows, drops)
        out["parsed"] = len(props)
        out["dropped"] = dict(sorted(drops.items(), key=lambda kv: -kv[1])[:30])
        out["unmapped_markets"] = dict(
            sorted(self.unmapped.items(), key=lambda kv: -kv[1]))
        per_stat: dict[str, int] = {}
        for p in props:
            k = f"{p.side}/{p.stat}"
            per_stat[k] = per_stat.get(k, 0) + 1
        out["parsed_by_stat"] = dict(sorted(per_stat.items()))
        out["players"] = len({p.player_key for p in props})

        if not rows:
            out["note"] = ("The endpoint answered but carried no projections — "
                           "no slate up, or the league id is wrong. Check "
                           "/api/props-probe/leagues.")
        elif not props:
            out["note"] = ("Projections arrived and none could be priced. "
                           "Compare `stat_types` against the parser's "
                           "vocabulary and read `dropped`.")
        return out

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            PrizePicksSource._cache = None
        cls.clear_leagues()
