"""Every priced player prop, as one card per prop rather than one per side.

The ranked panel answers "what are the five best plays". This answers a
different question — "what is on the board, and what does our model say about
each of them" — so it keeps everything and sorts rather than filtering.

**It is a view over the ranked report, not a second pricing.** Asking
`build_best_bets` for an unlimited ranking and pairing its rows up is a
deliberate choice: two code paths pricing the same prop would eventually
disagree, and the version a reader saw would depend on which page they opened.
Everything here — the simulations, the Laplace correction, the live-line
adjustment, the vig-inclusive implied probability — is the machinery the Best
Bets panel already uses.

The pairing matters because a prop is one object with two sides. PrizePicks draws
it that way (a line, with MORE and LESS under it) and so does this; the ranked
report splits it into two rows because it ranks *bets*, and a bet is a side.
"""
from __future__ import annotations

from datetime import date as date_type
from typing import Any, Optional

# Big enough to mean "every play", small enough to stay a number. The ranker
# takes a per-category limit rather than a flag for unlimited.
_ALL = 100_000

# The order the tabs come in: the batter's night first, in roughly the order
# the stats happen, then the pitcher's. PrizePicks groups its board the same way
# and there's no reason to disagree with a layout people already read.
_STAT_ORDER = (
    ("batter", "hits", "Hits"),
    ("batter", "total_bases", "Total bases"),
    ("batter", "home_runs", "Home runs"),
    ("batter", "rbi", "RBI"),
    ("batter", "singles", "Singles"),
    ("batter", "doubles", "Doubles"),
    ("batter", "triples", "Triples"),
    ("batter", "bb", "Walks"),
    ("batter", "k", "Strikeouts"),
    ("pitcher", "k", "Strikeouts"),
    ("pitcher", "outs", "Outs recorded"),
    ("pitcher", "hits_allowed", "Hits allowed"),
    ("pitcher", "bb_allowed", "Walks allowed"),
    ("pitcher", "runs_allowed", "Earned runs"),
)


def _side_of(category: str) -> str:
    return "pitcher" if category == "pitcher_prop" else "batter"


def _multiplier(price: Optional[int]) -> Optional[float]:
    """American odds back to the payout multiple a board displays.

    Their board is in multiples — 1.53x — and a reader comparing our page to
    the app should not have to convert in their head. The American price is
    kept alongside it, because that's what the edge is computed from.
    """
    if price is None:
        return None
    try:
        p = int(price)
    except (TypeError, ValueError):
        return None
    if p == 0:
        return None
    profit = p / 100.0 if p > 0 else 100.0 / abs(p)
    return round(1.0 + profit, 2)


def _side_payload(bet: Optional[dict], multipliers: bool = True) -> Optional[dict]:
    """One side of a card. `multipliers` is off for a source that posts no odds.

    A PrizePicks pick has no price, so the American number on it is a
    break-even we derived. Rendering that as "1.73x" would put a payout on the
    card that PrizePicks does not offer and nobody could collect, so the
    multiplier is dropped rather than computed from a synthetic price.
    """
    if bet is None:
        return None
    return {
        "price": bet["price"],
        "multiplier": _multiplier(bet["price"]) if multipliers else None,
        # What our simulation says. The number the page is for.
        "model_pct": round(100.0 * bet["model_probability"], 1),
        # What the price says, vig included — so the two are comparable and
        # the gap between them is not flattered by ignoring the hold.
        "implied_pct": round(100.0 * bet["implied_probability"], 1),
        "edge_pct": round(100.0 * bet["edge"], 1),
        "has_edge": bool(bet.get("has_edge")),
        "kelly_pct": bet.get("kelly_pct"),
    }


def _card(over: Optional[dict], under: Optional[dict],
          multipliers: bool = True) -> dict:
    ref = over or under
    assert ref is not None
    o, u = _side_payload(over, multipliers), _side_payload(under, multipliers)

    # Which side, if either, our model actually prefers at the posted price.
    # Edge rather than probability: a 70% shot at a price implying 75% is not a
    # bet, and reading the bigger percentage as the better side is exactly the
    # mistake this page could otherwise encourage.
    best = None
    if o and u:
        if o["has_edge"] or u["has_edge"]:
            best = "over" if o["edge_pct"] >= u["edge_pct"] else "under"
    elif o and o["has_edge"]:
        best = "over"
    elif u and u["has_edge"]:
        best = "under"

    return {
        "game_id": ref["game_id"],
        "away": ref["away"], "home": ref["home"],
        "matchup": f"{ref['away']} @ {ref['home']}",
        "first_pitch": ref["first_pitch"],
        "is_live": ref["is_live"],
        "player": ref["player"], "team": ref.get("team"),
        "stat": ref["stat"], "side": _side_of(ref["category"]),
        "line": ref["line"],
        "n_sims": ref["n_sims"],
        "over": o, "under": u,
        "best": best,
        # The larger of the two edges, which is what the tab sorts on: a card
        # is interesting if *either* side of it is.
        "top_edge": max([x["edge_pct"] for x in (o, u) if x], default=0.0),
    }


def build_board(repo, day: date_type, **kwargs: Any) -> dict:
    """Every priced prop on the slate, grouped by stat, best edge first."""
    from .best_bets import build_best_bets

    kwargs.setdefault("per_category", _ALL)
    report = build_best_bets(repo, day, **kwargs)

    # One card per prop. Keyed on the line as well as the player and stat,
    # because a live line and its pregame version are genuinely different bets
    # on the same stat and must not collapse into one card.
    pairs: dict[tuple, dict] = {}
    for bet in report.bets:
        if bet["market"] not in ("prop_over", "prop_under"):
            continue
        key = (bet["game_id"], bet["player"], bet["stat"], bet["line"],
               bet["is_live"], bet["category"])
        slot = pairs.setdefault(key, {"over": None, "under": None})
        slot["over" if bet["market"] == "prop_over" else "under"] = bet

    # A quoted price can be shown as the payout it is; a break-even we derived
    # cannot, because there is no such payout on offer.
    multipliers = not getattr(report, "pricing_note", "")
    cards = [_card(v["over"], v["under"], multipliers) for v in pairs.values()]

    offered_by_stat = getattr(report, "offered_by_stat", {}) or {}
    unmatched_by_stat = getattr(report, "unmatched_by_stat", {}) or {}

    groups = []
    for side, stat, label in _STAT_ORDER:
        in_group = [c for c in cards if c["side"] == side and c["stat"] == stat]
        if not in_group:
            continue
        # Live first inside a tab — it's the most time-sensitive thing there —
        # then by the better of the two edges.
        in_group.sort(key=lambda c: (not c["is_live"], -c["top_edge"]))
        # How many PrizePicks quoted for this stat against how many we could
        # price. A tab showing one card out of sixteen offered is a completely
        # different fact from a tab where PrizePicks only posted one.
        key = f"{side}/{stat}"
        groups.append({
            "side": side, "stat": stat, "label": label,
            "cards": in_group,
            "count": len(in_group),
            "with_edge": sum(1 for c in in_group if c["best"]),
            "offered": offered_by_stat.get(key, len(in_group)),
            "unmatched": unmatched_by_stat.get(key, 0),
        })

    # The games strip. Built from the cards rather than from the schedule, so
    # it lists what actually has props on it — a game nobody priced would
    # otherwise sit in the filter row selecting nothing.
    by_game: dict[str, dict] = {}
    for c in cards:
        g = by_game.setdefault(c["game_id"], {
            "game_id": c["game_id"], "away": c["away"], "home": c["home"],
            "matchup": c["matchup"], "first_pitch": c["first_pitch"],
            "is_live": False, "cards": 0, "with_edge": 0,
        })
        g["cards"] += 1
        g["with_edge"] += 1 if c["best"] else 0
        g["is_live"] = g["is_live"] or c["is_live"]
    # Live first — it's the most time-sensitive thing on the page — then in
    # first-pitch order, which is how a slate is read everywhere else.
    games = sorted(by_game.values(),
                   key=lambda g: (not g["is_live"], g["first_pitch"] or "",
                                  g["matchup"]))

    # Anything priced whose stat isn't in the order above would vanish
    # silently, so it's reported rather than dropped.
    known = {(s, st) for s, st, _ in _STAT_ORDER}
    stray = sorted({(c["side"], c["stat"]) for c in cards
                    if (c["side"], c["stat"]) not in known})

    return {
        "date": report.date,
        "generated_at": report.generated_at,
        # Which feed built this board, and — for a pick'em source that posts no
        # odds — what the "needs" percentages were derived from. The page shows
        # both, because a percentage nobody quoted must not look like one
        # somebody did.
        "book": getattr(report, "book", ""),
        "pricing_note": getattr(report, "pricing_note", ""),
        "games_considered": report.games_considered,
        "games_priced": report.games_priced,
        "props_available": report.props_available,
        "live_games": report.live_games,
        "games": games,
        # {"<game_id>|<side>/<stat>": how many PrizePicks' public feed quoted}.
        # Per game, because that's the view anyone comparing against the app
        # is actually looking at.
        "coverage": dict(getattr(report, "offered_by_game_stat", {}) or {}),
        "groups": groups,
        "totals": {
            "cards": len(cards),
            "players": len({c["player"] for c in cards}),
            "with_edge": sum(1 for c in cards if c["best"]),
        },
        "unmapped_stats": [f"{s}/{st}" for s, st in stray],
        # Where props went that never became a card. Carried onto the page
        # itself rather than left to a probe URL, because "PrizePicks offers this
        # and you don't show it" should be answerable by looking.
        "source": {
            "quoted": getattr(report, "props_quoted", 0),
            "offered": getattr(report, "props_offered", 0),
            "priced": len(cards),
            "unmatched_player": getattr(report, "props_unmatched", 0),
            "dropped": dict(getattr(report, "prop_drops", {}) or {}),
            # What PrizePicks' public feed actually carries, per market, across
            # the whole slate. Pure reporting — no interpretation, which is
            # what three wrong theories from me have earned.
            "by_stat": dict(getattr(report, "offered_by_stat", {}) or {}),
        },
        "notes": list(report.notes),
    }
