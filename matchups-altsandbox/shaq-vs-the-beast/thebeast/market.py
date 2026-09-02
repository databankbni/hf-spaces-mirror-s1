"""Who won the night — the books, or the people betting into them.

**The mechanism this is built on.** A sportsbook that balances its money wins
the vig whoever wins the game: it holds roughly 4-5% of the handle on an MLB
moneyline and does not care about the result. It only loses when the money is
one-sided *and* the heavy side wins. So the question is not "did favourites
win" — favourites and underdogs are equally capable of being the popular side —
it is:

    which side did the money go to, and did that side win?

**Line movement answers the first half, by observation.** Books move a price to
attract the other side. A total drifting 8.5 → 9 means money arrived on the
over; a favourite shortening -130 → -155 means money arrived on the favourite.
That is a fact about this specific game, not an assumption about bettors in
general — which is what makes it better than the "public backs favourites"
heuristic it replaced. That heuristic is a claim about a population; this is a
reading of a price.

**The final score answers the second half.** Together they settle each game:

* money moved and its side won  → the public got the better of the book
* money moved and its side lost → the book got the better of the public
* the line never moved          → balanced, and the book keeps the vig

**One book, for the price and the split alike.** Everything here comes from
DraftKings by way of VSiN, which publishes that book's share of handle and
share of tickets free. So "which side did the money go to" is usually read
rather than deduced, and when it is deduced, it's deduced from the movement of
the very price the money was arriving at. Reading one book's handle against
another's consensus line would describe two different markets as one: the hold
would be a hold nobody quoted, and the drift would be drift that money never
touched. Movement is the fallback, per market, for anything the splits don't
cover — but it's the same book's movement.

**The gap between the two numbers is what movement alone can never show.** A
side with 65% of the money and 65% of the bets is a crowd. A side with 65% of
the money and 25% of the bets is a few large tickets. Both push a price the
same direction, so nothing in the line tells them apart.

**Scale is what this still cannot see.** Even with splits we get percentages,
never dollars, so a 70/30 on a game taking fifty thousand and one taking five
million count the same. Within a game the split is now measured; across games
the weighting is still missing. That keeps this a tally of games, not a P&L,
and the language everywhere says so.

Nor can it be an audit of anyone's ledger: a book's actual profit depends on
its hold, its limits, what it laid off, and how correlated the night was across
every sport it takes. "The books won" here means the money went to the losing
side more often than not.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_type, datetime, timedelta, timezone
from typing import Any, Optional

# Below this a total's drift is rounding rather than money — books shade a
# half-run line by a tick without any real imbalance behind it.
TOTAL_MOVE_EPSILON = 0.24

# A moneyline has to move by more than a few cents to mean anything; prices are
# re-quoted constantly.
ML_MOVE_EPSILON = 5

# How far past even a share of handle has to sit before the money counts as
# one-sided. 52/48 is a balanced book; 58/42 is money with a direction. Picked
# to match the spirit of the movement epsilons — small imbalances are the
# normal state of a market, not an event.
HANDLE_EDGE_PCT = 5.0

# Handle running this far ahead of tickets is the signature of a few large bets
# rather than many small ones. Not proof of anything — big and wrong is a thing
# — but it is the one distinction line movement cannot make.
SHARP_GAP_PCT = 10.0


def payout(price: Optional[int]) -> Optional[float]:
    """Profit on one unit staked at American odds. -110 → 0.909, +150 → 1.5."""
    if price is None:
        return None
    try:
        p = int(price)
    except (TypeError, ValueError):
        return None
    if p == 0:
        return None
    return p / 100.0 if p > 0 else 100.0 / abs(p)


def implied(price: Optional[int]) -> Optional[float]:
    """The probability a price implies, vig included."""
    if price is None:
        return None
    try:
        p = int(price)
    except (TypeError, ValueError):
        return None
    if p == 0:
        return None
    return 100.0 / (p + 100.0) if p > 0 else abs(p) / (abs(p) + 100.0)


def hold_pct(home_ml: Optional[int], away_ml: Optional[int]) -> Optional[float]:
    """The book's structural edge on a two-way market, as a percentage.

    Both implied probabilities sum to more than one; the excess is what the
    book keeps if the money is balanced. This is the number it wins on a game
    it has no opinion about, and the reason a balanced book is a good night
    regardless of the result.
    """
    h, a = implied(home_ml), implied(away_ml)
    if h is None or a is None:
        return None
    over = h + a
    if over <= 0:
        return None
    return round(100.0 * (over - 1.0) / over, 2)


@dataclass
class GameMarket:
    """One game's market: where the money went, and whether it was right."""

    game_id: str
    opened: Optional[dict] = None
    closed: Optional[dict] = None
    snapshots: int = 0
    hold_pct: Optional[float] = None
    # Which side the money went to, read off the movement. None when the line
    # never moved — a balanced market, not an unknown one.
    money_on: dict = field(default_factory=dict)
    # Whether each of those sides went on to win. Only once final.
    money_right: dict = field(default_factory=dict)
    # "public" | "book" | "balanced" | None (not settled)
    winner: Optional[str] = None
    # The last splits reading, when a book published one for this game.
    splits: Optional[dict] = None
    notes: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "game_id": self.game_id, "opened": self.opened,
            "closed": self.closed, "snapshots": self.snapshots,
            "hold_pct": self.hold_pct,
            "money_on": self.money_on, "money_right": self.money_right,
            "winner": self.winner, "splits": self.splits, "notes": self.notes,
        }


def money_flow(opened: Optional[dict], closed: Optional[dict]) -> dict:
    """Which side of each market the money went to, from how the price moved.

    Books move a price to attract the other side, so the direction of the move
    is the direction of the imbalance. Returns only markets that actually
    moved: a still line means balanced money, which is a real answer rather
    than a missing one.
    """
    out: dict = {}
    if not opened or not closed:
        return out

    o_total, c_total = opened.get("total"), closed.get("total")
    if o_total is not None and c_total is not None:
        drift = c_total - o_total
        if abs(drift) > TOTAL_MOVE_EPSILON:
            out["total"] = {
                "side": "over" if drift > 0 else "under",
                "from": o_total, "to": c_total,
            }

    o_home, c_home = opened.get("home_ml"), closed.get("home_ml")
    if o_home is not None and c_home is not None:
        # A price shortening (-130 → -155, or +120 → +105) is money arriving on
        # that side; lengthening is money leaving it for the other.
        drift = c_home - o_home
        if abs(drift) > ML_MOVE_EPSILON:
            out["moneyline"] = {
                "side": "home" if drift < 0 else "away",
                "from": o_home, "to": c_home,
            }
    return out


def money_from_handle(split: Optional[dict]) -> tuple:
    """Which side the money is on, read straight off a book's splits.

    Returns (flow, covered): the markets where the handle is one-sided enough
    to have a direction, and the markets the splits spoke to at all. The second
    matters as much as the first — a split saying 51/49 is a real finding of
    "balanced", and it should stop us falling back to a line move and calling
    the same game one-sided.
    """
    flow: dict = {}
    covered: set = set()
    if not split:
        return flow, covered

    for market_name, handle_key, bets_key, high, low in (
            ("moneyline", "ml_home_handle", "ml_home_bets", "home", "away"),
            ("total", "total_over_handle", "total_over_bets", "over", "under")):
        handle = split.get(handle_key)
        if handle is None:
            continue
        covered.add(market_name)
        if abs(handle - 50.0) <= HANDLE_EDGE_PCT:
            continue                       # balanced money, not a direction
        side = high if handle > 50.0 else low
        share = handle if side == high else 100.0 - handle
        bets = split.get(bets_key)
        if bets is not None:
            bets = bets if side == high else 100.0 - bets
        flow[market_name] = {
            "side": side,
            "handle_pct": round(share, 1),
            "bets_pct": None if bets is None else round(bets, 1),
            "sharp": bets is not None and (share - bets) >= SHARP_GAP_PCT,
            "source": "handle",
            "book": split.get("book"),
        }
    return flow, covered


def _settle(flow: dict, closed: dict, home_runs: int, away_runs: int) -> tuple:
    """Did the side the money went to win? Returns (right, notes)."""
    right: dict = {}
    notes: list = []

    if "moneyline" in flow:
        if home_runs == away_runs:
            notes.append("moneyline: tie, no result")
        else:
            winner = "home" if home_runs > away_runs else "away"
            right["moneyline"] = flow["moneyline"]["side"] == winner

    if "total" in flow:
        line = closed.get("total")
        actual = home_runs + away_runs
        if line is None:
            pass
        elif actual == line:
            notes.append(f"total: pushed on {line}")
        else:
            went = "over" if actual > line else "under"
            right["total"] = flow["total"]["side"] == went
    return right, notes


def _observed_then_inferred(split: Optional[dict], opened: Optional[dict],
                            closed: Optional[dict]) -> dict:
    """Splits where a book published them, line movement everywhere else.

    Per market rather than per game: a game whose moneyline handle we have and
    whose total handle we don't should use the real number for the one and the
    inferred one for the other, not throw either away.
    """
    flow, covered = money_from_handle(split)
    for market_name, entry in money_flow(opened, closed).items():
        if market_name in covered:
            continue                       # the book already told us
        flow[market_name] = {**entry, "source": "movement"}
    return flow


# How long a single price has to stand up before "it never moved" is a claim
# about the market rather than about how quickly we asked twice. Two lookups a
# few seconds apart — a page load that backfills and then re-reads — say
# nothing at all; ten minutes of a live market holding still does.
WATCHED_GAP_SECONDS = 600


def _was_watched(market: "GameMarket") -> bool:
    """Did we follow this market over time, or just catch a price once?

    Two distinct prices is proof by itself. One price is only proof if we
    looked again a good while later and it hadn't changed — which is what
    `last_seen` records, because the dedupe that keeps storage small also
    erases the difference between a line that held and a line we glanced at.
    """
    if market.snapshots >= 2:
        return True
    closed = market.closed or {}
    seen, taken = closed.get("last_seen"), closed.get("taken_at")
    if not (seen and taken):
        return False
    try:
        gap = datetime.fromisoformat(seen) - datetime.fromisoformat(taken)
    except (TypeError, ValueError):
        return False
    return gap.total_seconds() >= WATCHED_GAP_SECONDS


def backfill(repo, game_id: str) -> int:
    """Fetch and store this game's market now, for a game we never watched.

    The book's splits page carries the current slate, so this fills in a game
    the app hadn't got to yet — not one from a past day. There is no going back
    for a market: a page that shows tonight's board doesn't show last Tuesday's,
    and the price a game closed at is gone once nobody wrote it down.

    What it must not do is masquerade as a history. One reading is one reading,
    and `game_market` refuses to read movement out of it rather than reporting
    a line that "never moved".
    """
    from .gameid import date_of

    day = date_of(game_id)
    if day is None:
        return 0
    try:
        from .data.sources.splits import VSiNSplitsSource
        # By id, so a line can only be stored against a game that exists rather
        # than one rebuilt from someone else's spelling of the teams.
        splits = VSiNSplitsSource().fetch(day, [game_id])
        record_splits(repo, day, splits)
        return record(repo, day, [s.as_line() for s in splits if s.has_price])
    except Exception:
        return 0


def game_market(repo, game_id: str) -> GameMarket:
    """One game's line history and, once final, who the money paid."""
    history = repo.odds_history(game_id)
    market = GameMarket(game_id=game_id, snapshots=len(history))
    try:
        market.splits = repo.latest_splits(game_id)
    except Exception:
        market.splits = None               # older DB, or no splits table yet
    if not history:
        return market
    market.opened, market.closed = history[0], history[-1]
    market.hold_pct = hold_pct(market.closed.get("home_ml"),
                               market.closed.get("away_ml"))
    market.money_on = _observed_then_inferred(
        market.splits, market.opened, market.closed)

    stored = repo.get_accuracy_game(game_id)
    actual = (stored or {}).get("actual") or {}
    if str(actual.get("status") or "").lower() != "final":
        return market
    try:
        hr, ar = int(actual["home_runs"]), int(actual["away_runs"])
    except (KeyError, TypeError, ValueError):
        return market

    if not market.money_on:
        _, covered = money_from_handle(market.splits)
        if covered:
            # A published split that came in even. A real finding.
            market.winner = "balanced"
            market.notes = ["the money came in near enough even — balanced, so "
                            "the book keeps its hold whoever won"]
        elif _was_watched(market):
            # We watched it and it held. Also a real finding.
            market.winner = "balanced"
            market.notes = ["the line never moved — balanced money, the book "
                            "keeps its hold whoever won"]
        else:
            # One price is not a history. "The line never moved" would be a
            # claim about a stretch of time nobody was watching, which is the
            # one thing this module must never do — so there's no verdict, and
            # the line is shown for what it is.
            market.notes = ["only the closing line was caught for this game, "
                            "so there's no movement to read and no published "
                            "split — the price is shown, the verdict isn't"]
        return market

    right, notes = _settle(market.money_on, market.closed, hr, ar)
    market.money_right = right
    market.notes = notes
    if not right:
        market.winner = "balanced"
    else:
        hits = sum(1 for v in right.values() if v)
        misses = sum(1 for v in right.values() if not v)
        market.winner = ("public" if hits > misses
                         else "book" if misses > hits else "balanced")
    return market


def scorecard(repo, *, end: Optional[date_type] = None, days: int = 5) -> dict:
    """Whether the money was on the right side, over a window.

    A tally of games rather than a P&L: the direction of a move is observable
    and its size is not, so a game where a million moved and one where ten
    thousand did count the same. Said out loud rather than implied.
    """
    end = end or (datetime.now(timezone.utc).date() - timedelta(days=1))
    start = end - timedelta(days=days - 1)

    game_ids = sorted({r["game_id"] for r in repo.odds_for_dates(start, end)})
    public = book = balanced = 0
    ml_right = ml_wrong = tot_right = tot_wrong = 0
    observed = sharp_right = sharp_wrong = 0
    holds: list[float] = []
    games: list[dict] = []

    for game_id in game_ids:
        m = game_market(repo, game_id)
        if m.hold_pct is not None:
            holds.append(m.hold_pct)
        if m.winner is None:
            continue          # not final yet
        if m.winner == "public":
            public += 1
        elif m.winner == "book":
            book += 1
        else:
            balanced += 1
        if any(e.get("source") == "handle" for e in m.money_on.values()):
            observed += 1
        for market_name, was_right in m.money_right.items():
            if market_name == "moneyline":
                ml_right, ml_wrong = (ml_right + 1, ml_wrong) if was_right \
                    else (ml_right, ml_wrong + 1)
            else:
                tot_right, tot_wrong = (tot_right + 1, tot_wrong) if was_right \
                    else (tot_right, tot_wrong + 1)
            # Big money and few tickets, graded on its own. Whether it deserves
            # its reputation is a question this can now actually answer.
            if m.money_on.get(market_name, {}).get("sharp"):
                sharp_right, sharp_wrong = (sharp_right + 1, sharp_wrong) \
                    if was_right else (sharp_right, sharp_wrong + 1)
        games.append(m.as_dict())

    settled = public + book + balanced
    moved = public + book
    return {
        "start": start.isoformat(), "end": end.isoformat(),
        "games_settled": settled,
        "public_won": public, "book_won": book, "balanced": balanced,
        "money_side": {
            "moneyline": {"right": ml_right, "wrong": ml_wrong},
            "total": {"right": tot_right, "wrong": tot_wrong},
        },
        "typical_hold_pct": (round(sum(holds) / len(holds), 2) if holds else None),
        # How much of the window was measured rather than deduced. Reported
        # rather than buried, because a scorecard built on published splits and
        # one built on inferred movement are not the same claim.
        "games_from_splits": observed,
        "sharp_side": {"right": sharp_right, "wrong": sharp_wrong},
        "verdict": _verdict(public, book, balanced, moved),
        "method": _method(observed, settled),
        "games": games,
    }


def _method(observed: int, settled: int) -> str:
    base = ("Where a book publishes its splits, which side the money went to "
            "is read straight off the share of handle. Everywhere else it's "
            "inferred from how the line moved — books shade a price to attract "
            "the other side, so the direction of the move is the direction of "
            "the imbalance. It counts games, not dollars: shares are published, "
            "amounts are not.")
    if not settled:
        return base
    if observed == settled:
        return base + " Every game here came from published splits."
    if observed:
        return base + (f" {observed} of {settled} games came from published "
                       f"splits; the rest from line movement.")
    return base + " No published splits in this window — all from movement."


def _verdict(public: int, book: int, balanced: int, moved: int) -> str:
    if not (public + book + balanced):
        return "Nothing settled yet."
    if not moved:
        return (f"Every line held. {balanced} game(s) balanced, so the books "
                f"kept the hold and nobody got the better of anyone.")
    share = public / moved
    tail = (f" ({balanced} more never moved, where the books keep the hold.)"
            if balanced else "")
    if share > 0.55:
        return (f"The public won: the money was on the right side in "
                f"{public} of {moved} games where it moved.{tail}")
    if share < 0.45:
        return (f"The books won: the money was on the losing side in "
                f"{book} of {moved} games where it moved.{tail}")
    return (f"Honours even — the money was right in {public} of {moved} games "
            f"where it moved, which is about a coin flip.{tail}")


def record(repo, day: date_type, lines: Any) -> int:
    """Store today's posted lines. Returns how many were new.

    Called wherever the slate is already being refreshed, so following the
    market costs a scoreboard fetch rather than a job of its own.
    """
    # Milliseconds, not seconds: the row is keyed on (game, taken_at), so
    # two recordings inside the same second overwrite each other instead
    # of becoming the two readings that movement is measured between.
    taken_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    written = 0
    for line in lines or []:
        try:
            # One book per game, for the life of the game. Two books rarely
            # post the same number, so alternating between them would write a
            # price change on every pass and every one of those would read as
            # money arriving. Movement across books isn't movement, so a game
            # keeps whichever book priced it first.
            existing = repo.latest_odds(line.game_id)
            if existing is not None and existing.get("book") and line.book \
                    and existing["book"] != line.book:
                continue
            payload = {
                "home_ml": line.home_ml, "away_ml": line.away_ml,
                "total": line.total, "over_price": line.over_price,
                "under_price": line.under_price, "book": line.book,
            }
            if repo.save_odds_snapshot(line.game_id, day, taken_at, payload):
                written += 1
        except Exception:
            continue
    return written


def record_splits(repo, day: date_type, splits: Any) -> int:
    """Store this pass's betting splits. Returns how many were new.

    Rides the same tick as the odds snapshot, for the same reason: a split is a
    running total over a day of betting, so it has to be caught while the
    betting is happening rather than reconstructed after the fact.
    """
    # Milliseconds, not seconds: the row is keyed on (game, taken_at), so
    # two recordings inside the same second overwrite each other instead
    # of becoming the two readings that movement is measured between.
    taken_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    written = 0
    for split in splits or []:
        try:
            if repo.save_splits_snapshot(split.game_id, day, taken_at,
                                         split.as_dict()):
                written += 1
        except Exception:
            continue
    return written
