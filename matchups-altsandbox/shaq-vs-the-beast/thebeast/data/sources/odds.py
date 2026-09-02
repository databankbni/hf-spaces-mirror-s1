"""Game lines — moneyline and total — from ESPN's public scoreboard.

Sleeper was the obvious source and it can't be. Its team markets live behind
`my_picks_init`, which is user-scoped: an anonymous call gets
`{"code": "unauthorized"}`, so without a session token `fetch_team_lines()`
returns nothing. Player props are served anonymously; moneylines and totals are
not. Those two are precisely what a market scorecard needs.

ESPN's scoreboard is public, anonymous and free, and carries both. It is not a
book — it publishes a consensus line rather than any one shop's — which is fine
here, because the question is which way a market moved and how it settled, not
what a particular counter was offering at a particular second.

What this does *not* carry, and no free source does: how much money is on each
side. Handle and ticket splits are paid data. Everything downstream of this
treats line movement as a proxy for money and says so.

Best-effort throughout: an unreachable or reshaped source yields nothing, and
the caller shows no market rather than a made-up one.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import date as date_type
from typing import Any, Optional

import requests

_SCOREBOARD = ("https://site.api.espn.com/apis/site/v2/sports/baseball/mlb"
               "/scoreboard")

# Lines move, but not by the second, and a slate is polled repeatedly. Two
# minutes keeps a snapshot current without asking ESPN once per page view.
TTL_SECONDS = 120.0

# ESPN's abbreviations mostly match MLB's; these are the ones that don't.
# Mapped rather than guessed — an unmatched team is skipped, because pinning a
# line on the wrong game is worse than having no line.
_ALIASES = {
    "CHW": "CWS", "WSH": "WSH", "ARI": "AZ", "AZ": "AZ", "OAK": "ATH",
    "SF": "SF", "SD": "SD", "TB": "TB", "KC": "KC",
}


def _team(abbr: Any) -> str:
    a = str(abbr or "").strip().upper()
    return _ALIASES.get(a, a)


def _int(v: Any) -> Optional[int]:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _american(v: Any) -> Optional[int]:
    """A moneyline in any of the forms ESPN writes it.

    Sometimes an int, sometimes "+150", sometimes "EVEN". Reading only the int
    form is how a payload that carries prices reads as a payload that doesn't.
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip().upper().replace(" ", "")
    if s in ("EVEN", "EV", "PK", "PICK"):
        return 100
    s = s.lstrip("+")
    try:
        return int(float(s))
    except ValueError:
        return None


def _dig(obj: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


# Every place ESPN has put a moneyline. The nested `current`/`open` forms are
# the modern payload; the flat one is the older shape this was first written
# against, which is why it found nothing on a live slate.
_ML_PATHS = (
    ("moneyLine",),
    ("moneyLineOdds",),
    ("current", "moneyLine", "american"),
    ("close", "moneyLine", "american"),
    ("open", "moneyLine", "american"),
)


def _money_line(side: Any) -> Optional[int]:
    for path in _ML_PATHS:
        got = _american(_dig(side, *path))
        if got is not None:
            return got
    return None


def _float(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


@dataclass
class GameLine:
    """One game's posted market, as of a moment."""

    game_id: str
    home: str
    away: str
    home_ml: Optional[int] = None
    away_ml: Optional[int] = None
    total: Optional[float] = None
    over_price: Optional[int] = None
    under_price: Optional[int] = None
    book: Optional[str] = None

    @property
    def usable(self) -> bool:
        """Enough to be worth recording — a moneyline pair or a total."""
        return (self.home_ml is not None and self.away_ml is not None) \
            or self.total is not None


class ESPNOddsSource:
    """Posted game lines by date, cached briefly."""

    _cache: dict[str, tuple[float, list[GameLine]]] = {}
    _lock = threading.Lock()

    def _get(self, params: dict) -> Any:
        # Tight timeout: this can fire behind a page load.
        resp = requests.get(_SCOREBOARD, params=params, timeout=(3, 6))
        resp.raise_for_status()
        return resp.json()

    def _teams_of(self, comp: Any) -> tuple:
        home = away = None
        for c in (comp or {}).get("competitors") or []:
            abbr = _team(((c.get("team") or {}).get("abbreviation")))
            if c.get("homeAway") == "home":
                home = abbr
            elif c.get("homeAway") == "away":
                away = abbr
        return home, away

    def _line_from(self, event: Any, day: date_type,
                   known: Optional[dict] = None) -> Optional[GameLine]:
        comps = (event or {}).get("competitions") or []
        if not comps:
            return None
        comp = comps[0]
        home, away = self._teams_of(comp)
        if not home or not away:
            return None

        # Match the id we already use for this game rather than rebuilding one
        # from ESPN's abbreviations. A constructed id only has to differ by a
        # character — a club we didn't alias, a doubleheader's suffix — and the
        # row lands under a key no game page ever asks for. Stored, invisible,
        # and silent, which is the worst way for this to fail.
        game_id = (known or {}).get((away, home))
        if known is not None and game_id is None:
            return None
        if game_id is None:
            game_id = f"{day.isoformat()}-{away}-{home}"

        # Every provider, not just the first. A book with no prices posted
        # shouldn't stand in for one that has them.
        best: Optional[GameLine] = None
        for odds in comp.get("odds") or []:
            line = GameLine(
                game_id=game_id, home=home, away=away,
                home_ml=_money_line(odds.get("homeTeamOdds")),
                away_ml=_money_line(odds.get("awayTeamOdds")),
                total=_float(odds.get("overUnder")),
                over_price=_american(_dig(odds, "current", "over", "american")),
                under_price=_american(_dig(odds, "current", "under", "american")),
                book=str((odds.get("provider") or {}).get("name") or "") or None,
            )
            if line.total is None:
                line.total = _float(_dig(odds, "current", "total", "value"))
            if not line.usable:
                continue
            # A moneyline pair is what the market panel is mostly about, so a
            # provider carrying one wins over a provider carrying only a total.
            if line.home_ml is not None and line.away_ml is not None:
                return line
            best = best or line
        return best

    @staticmethod
    def index(game_ids) -> dict:
        """(away, home) → the game id we already use, for matching on."""
        from ...gameid import teams_of

        out: dict = {}
        for gid in game_ids or []:
            home, away = teams_of(gid)
            if home and away:
                out.setdefault((away, home), gid)
        return out

    def fetch(self, day: date_type, game_ids=None) -> list[GameLine]:
        """Posted lines for one slate. Empty when unreachable — never partial
        guesses.

        Pass the slate's game ids and every line comes back keyed to one of
        them, or not at all. Without them the id is reconstructed from ESPN's
        abbreviations, which works right up until it doesn't.
        """
        key = f"{day.isoformat()}|{'m' if game_ids else 'r'}"
        now = time.time()
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None and now - hit[0] < TTL_SECONDS:
                return list(hit[1])
        try:
            data = self._get({"dates": day.strftime("%Y%m%d")})
        except Exception:
            return []

        known = self.index(game_ids) if game_ids else None
        out: list[GameLine] = []
        for event in (data or {}).get("events") or []:
            try:
                line = self._line_from(event, day, known)
            except Exception:
                continue
            if line is not None:
                out.append(line)
        if out:
            with self._lock:
                self._cache[key] = (now, out)
        return out

    def diagnose(self, day: date_type, game_ids=None) -> dict:
        """What the scoreboard actually returned, and where it was lost.

        This source was written against an assumed payload and shipped without
        anyone being able to call the real thing, which is exactly how it came
        to produce nothing on a live slate without saying why. Every stage that
        can drop a game reports its own count, so the answer is a number rather
        than a theory.
        """
        out: dict = {"date": day.isoformat(), "reachable": False,
                     "url": _SCOREBOARD}
        try:
            data = self._get({"dates": day.strftime("%Y%m%d")})
        except Exception as exc:
            out["error"] = f"{type(exc).__name__}: {exc}"
            return out

        out["reachable"] = True
        events = (data or {}).get("events") or []
        out["events"] = len(events)
        known = self.index(game_ids) if game_ids else None
        out["slate_game_ids"] = len(known or {})

        with_odds = matched = usable = 0
        providers: list = []
        samples: list = []
        unmatched: list = []
        for event in events:
            comp = ((event or {}).get("competitions") or [{}])[0]
            home, away = self._teams_of(comp)
            odds_list = comp.get("odds") or []
            if odds_list:
                with_odds += 1
                for o in odds_list:
                    name = str((o.get("provider") or {}).get("name") or "?")
                    if name not in providers:
                        providers.append(name)
            if known is not None:
                if (away, home) in known:
                    matched += 1
                else:
                    unmatched.append(f"{away}@{home}")
            line = self._line_from(event, day, known)
            if line is not None:
                usable += 1
                if len(samples) < 3:
                    samples.append({
                        "game_id": line.game_id, "home_ml": line.home_ml,
                        "away_ml": line.away_ml, "total": line.total,
                        "book": line.book})
            elif odds_list and len(samples) < 3:
                # The interesting failure: odds present, nothing extracted.
                samples.append({"unparsed": f"{away}@{home}",
                                "odds_keys": sorted(odds_list[0].keys())[:14]})

        out["events_with_odds"] = with_odds
        out["matched_to_slate"] = matched
        out["lines_parsed"] = usable
        out["providers"] = providers[:8]
        out["samples"] = samples
        out["unmatched_pairs"] = unmatched[:8]
        if not events:
            out["note"] = "The scoreboard returned no games for this date."
        elif not with_odds:
            out["note"] = ("Games came back but none carried odds — ESPN often "
                           "drops the odds block once a game is final.")
        elif known is not None and not matched:
            out["note"] = ("Odds arrived but no ESPN matchup matched a game id "
                           "on our slate — compare unmatched_pairs against the "
                           "_ALIASES table.")
        elif not usable:
            out["note"] = ("Odds arrived and matched, but nothing could be "
                           "read out of them — compare samples[].odds_keys "
                           "against _ML_PATHS.")
        return out

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._cache.clear()
